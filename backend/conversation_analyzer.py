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
    "INTRODUCE", "PROFILE", "PERSONALIZE", "EXPLAIN",
    "HANDLE", "CLOSE", "QUESTION_ANSWER",
}

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

    analysis = TurnAnalysis(
        stage=stage,
        interest_delta=_int_val(raw_tag, "interest_delta", 0),
        objection_category=category,
        objection_resolved=_extract(raw_tag, "objection_resolved", "false").lower() == "true",
        close_readiness_delta=_int_val(raw_tag, "close_readiness_delta", 0),
        emotional_state=emotional_state,
    )
    return clean, analysis


def apply_analysis(
    memory: "SessionMemory", analysis: TurnAnalysis, user_text: str
) -> None:
    """Apply a TurnAnalysis to the session memory in place."""
    intel = memory.intelligence

    # Stage transition
    if analysis.stage and analysis.stage != memory.stage:
        memory.previous_stage = memory.stage
        if memory.stage == "QUESTION_ANSWER" and memory.return_to_stage:
            memory.stage = memory.return_to_stage
            memory.return_to_stage = None
        else:
            if analysis.stage == "QUESTION_ANSWER":
                memory.return_to_stage = memory.stage
            memory.stage = analysis.stage
        memory.turn_in_stage = 0
    else:
        memory.turn_in_stage += 1

    # Emotional state update
    if analysis.emotional_state:
        memory.emotional_state = analysis.emotional_state

    # Advance EXPLAIN subtopic only when the advisor deliberately stayed in EXPLAIN
    # and completed a topic (LLM set stage=EXPLAIN and turn_in_stage incremented).
    # Do NOT advance on QA or HANDLE interruptions.
    if (memory.stage == "EXPLAIN"
            and analysis.stage == "EXPLAIN"
            and memory.turn_in_stage > 0):   # turn_in_stage > 0 means we stayed, not just entered
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
