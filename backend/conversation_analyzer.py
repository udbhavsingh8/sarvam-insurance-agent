"""
ConversationAnalyzer — extracts structured signals from each conversation turn.

CURRENT IMPLEMENTATION: Parses [META ...] tags embedded in the primary LLM response.
This is intentionally a temporary mechanism.

DESIGNED FOR REPLACEMENT:
This module has a narrow interface: parse_meta_tag() + apply_analysis().
Future replacements can swap the internals without changing any calling code:
  Option A: Dedicated lightweight classification model (e.g. sarvam-m with a
            classification-only system prompt, fired in parallel with the main LLM).
  Option B: Rule-based heuristics (keyword matching on user text for objection detection).
  Option C: A fine-tuned intent/stage classifier.

The calling code in agent.py only sees:
    clean_text, analysis = parse_meta_tag(raw_llm_output)
    if analysis:
        apply_analysis(memory, analysis, user_text)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from memory import SessionMemory


VALID_STAGES = {
    "INTRODUCE", "PROFILE", "PERSONALIZE",
    "NEED_DEVELOPMENT",
    "EXPLAIN",
    "RECOMMENDATION",
    "HANDLE", "CLOSE", "QUESTION_ANSWER",
}

VALID_CLOSE_SUBSTAGES = {"SUMMARY", "PURCHASE_INTENT", "PROCEED", "FEEDBACK", "CLOSED"}

VALID_EMOTIONAL_STATES = {
    "curious", "engaged", "hesitant", "resistant", "anxious", "satisfied",
}


@dataclass
class TurnAnalysis:
    stage: str
    interest_delta: int
    objection_category: Optional[str]
    objection_resolved: bool
    close_readiness_delta: int
    emotional_state: str = "curious"
    close_substage: str = ""  # populated only when stage == CLOSE


_META_PATTERN = re.compile(r'\[META([^\]]*)\]', re.IGNORECASE)


def _extract(raw: str, key: str, default: str = "") -> str:
    m = re.search(rf'\b{key}=(\S+)', raw)
    return m.group(1) if m else default


def _int_val(raw: str, key: str, default: int = 0) -> int:
    v = _extract(raw, key, str(default))
    try:
        return int(v.lstrip('+'))
    except ValueError:
        return default


def parse_meta_tag(text: str) -> tuple[str, Optional[TurnAnalysis]]:
    """
    Strip [META ...] tag from text and return (clean_text, analysis).
    Returns (text, None) if no tag is present — caller must handle gracefully.
    """
    match = _META_PATTERN.search(text)
    if not match:
        return text.strip(), None

    raw_tag = match.group(1)
    clean = (text[: match.start()] + text[match.end() :]).strip()

    category = _extract(raw_tag, "objection") or None
    if category == "none":
        category = None

    raw_stage = _extract(raw_tag, "stage").upper()
    stage = raw_stage if raw_stage in VALID_STAGES else ""

    raw_emotion = _extract(raw_tag, "emotional_state").lower()
    emotional_state = raw_emotion if raw_emotion in VALID_EMOTIONAL_STATES else "curious"

    raw_close_sub = _extract(raw_tag, "close_substage").upper()
    close_substage = raw_close_sub if raw_close_sub in VALID_CLOSE_SUBSTAGES else ""

    analysis = TurnAnalysis(
        stage=stage,
        interest_delta=_int_val(raw_tag, "interest_delta", 0),
        objection_category=category,
        objection_resolved=_extract(raw_tag, "objection_resolved", "false").lower() == "true",
        close_readiness_delta=_int_val(raw_tag, "close_readiness_delta", 0),
        emotional_state=emotional_state,
        close_substage=close_substage,
    )
    return clean, analysis


def apply_analysis(
    memory: "SessionMemory", analysis: TurnAnalysis, user_text: str
) -> None:
    """Apply a TurnAnalysis to the session memory in place."""
    intel = memory.intelligence

    # Stage transition
    if analysis.stage and analysis.stage != memory.stage:
        # I-9: Block the LLM from skipping PROFILE → EXPLAIN/CLOSE prematurely.
        # Python's _auto_advance_stage() is the only allowed path out of PROFILE.
        if memory.stage == "PROFILE" and analysis.stage in ("EXPLAIN", "CLOSE", "RECOMMENDATION"):
            memory.turn_in_stage += 1
        # Gate PROFILE → PERSONALIZE: only allow if minimum fields are collected.
        # Without this gate, the LLM can exit PROFILE mid-collection.
        elif memory.stage == "PROFILE" and analysis.stage == "PERSONALIZE":
            p = memory.customer_profile
            has_minimum = (
                p.age is not None
                and (p.smoker is not None or p.income_range is not None)
            )
            if not has_minimum:
                memory.turn_in_stage += 1  # block — keep collecting
            else:
                memory.previous_stage = memory.stage
                memory.stage = "PERSONALIZE"
                memory.turn_in_stage = 0
        # Block LLM from jumping NEED_DEVELOPMENT → anything other than EXPLAIN.
        # Python controls the NEED_DEVELOPMENT → EXPLAIN escape after 2 turns.
        elif memory.stage == "NEED_DEVELOPMENT" and analysis.stage not in ("EXPLAIN", "QUESTION_ANSWER", "HANDLE"):
            memory.turn_in_stage += 1
        # Block LLM from jumping EXPLAIN → CLOSE directly.
        # EXPLAIN must pass through RECOMMENDATION first.
        elif memory.stage == "EXPLAIN" and analysis.stage == "CLOSE":
            # Treat as RECOMMENDATION intent instead
            memory.previous_stage = memory.stage
            memory.stage = "RECOMMENDATION"
            memory.turn_in_stage = 0
        elif memory.stage == "QUESTION_ANSWER" and memory.return_to_stage:
            memory.previous_stage = memory.stage
            memory.stage = memory.return_to_stage
            memory.return_to_stage = None
            memory.turn_in_stage = 0
        else:
            memory.previous_stage = memory.stage
            if analysis.stage == "QUESTION_ANSWER":
                memory.return_to_stage = memory.stage
            memory.stage = analysis.stage
            memory.turn_in_stage = 0
    else:
        memory.turn_in_stage += 1

    # Close substage transition — LLM signals PROCEED or FEEDBACK after purchase intent
    if memory.stage == "CLOSE" and analysis.close_substage:
        _apply_close_substage(memory, analysis.close_substage)

    # Emotional state update
    if analysis.emotional_state:
        memory.emotional_state = analysis.emotional_state

    # Advance EXPLAIN subtopic after every turn spent in EXPLAIN.
    # Do NOT advance on QA or HANDLE interruptions (those stages return after 1 turn).
    if (memory.stage == "EXPLAIN" and memory.turn_in_stage > 0):
        if memory.explain_topics and memory.explain_subtopic_index < len(memory.explain_topics) - 1:
            memory.explain_subtopic_index += 1

    # Interest update
    intel.interest_level = max(0, min(100, intel.interest_level + analysis.interest_delta))

    # Objection tracking
    if analysis.objection_category:
        existing = next(
            (o for o in intel.objections
             if o["category"] == analysis.objection_category and not o["resolved"]),
            None,
        )
        if existing:
            if analysis.objection_resolved:
                existing["resolved"] = True
        else:
            intel.objections.append({
                "text": user_text[:100],
                "category": analysis.objection_category,
                "turn": memory.turn_count,
                "resolved": analysis.objection_resolved,
            })

    # Close readiness
    intel.close_readiness = max(
        0, min(100, intel.close_readiness + analysis.close_readiness_delta)
    )

    # Derived intent
    intel.update_intent()

    # Track questions in memory
    if "?" in user_text and user_text.strip() not in memory.questions_asked:
        memory.questions_asked.append(user_text.strip()[:80])


_CLOSE_SUBSTAGE_ORDER = ["SUMMARY", "PURCHASE_INTENT", "PROCEED", "FEEDBACK", "CLOSED"]


def _apply_close_substage(memory: "SessionMemory", requested: str) -> None:
    """
    Advance the close_substage only to valid next states.
    Prevents the LLM from skipping substages.

    Allowed transitions:
      SUMMARY        → PURCHASE_INTENT (Python auto-advances; LLM cannot skip)
      PURCHASE_INTENT → PROCEED | FEEDBACK (LLM signals based on user response)
      PROCEED        → CLOSED (Python auto-advances)
      FEEDBACK       → CLOSED (Python auto-advances after 1 turn)
      CLOSED         → CLOSED (terminal)
    """
    current = memory.close_substage

    allowed_next: dict[str, set[str]] = {
        "SUMMARY":         {"PURCHASE_INTENT"},
        "PURCHASE_INTENT": {"PROCEED", "FEEDBACK"},
        "PROCEED":         {"CLOSED"},
        "FEEDBACK":        {"CLOSED"},
        "CLOSED":          set(),
    }

    if requested in allowed_next.get(current, set()):
        memory.close_substage = requested
        memory.turn_in_stage = 0  # reset so auto-advance doesn't fire in the same turn
