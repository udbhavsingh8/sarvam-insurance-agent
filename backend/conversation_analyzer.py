"""
ConversationAnalyzer — extracts structured signals from each conversation turn.

Parses [META ...] tags embedded in the primary LLM response and applies them
to session memory. Python always has final say on stage transitions — the LLM
signals intent, Python decides whether to honour it.

Stage machine (new design):
  Term:    GREET → DISCOVERY → GAP_CALC → POSITION → RECOMMEND → VARIANTS → CLOSE
  Savings: GREET → DISCOVERY → RECOMMEND → EXPLAIN → CLOSE
  Any:     → QUESTION_ANSWER (interrupt, returns to previous stage after 1 turn)
           → OBJECTIONS      (interrupt, returns to previous stage after 1 turn)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from memory import SessionMemory


VALID_STAGES = {
    "GREET",
    "DISCOVERY",
    "GAP_CALC",
    "POSITION",
    "RECOMMEND",
    "VARIANTS",
    "EXPLAIN",          # savings / non-term plans only
    "OBJECTIONS",
    "CLOSE",
    "QUESTION_ANSWER",
}

VALID_CLOSE_SUBSTAGES = {"PURCHASE_INTENT", "PROCEED", "FEEDBACK", "CLOSED"}

VALID_EMOTIONAL_STATES = {
    "curious", "engaged", "hesitant", "resistant", "anxious", "satisfied",
}

# Stages that are valid interrupt destinations
_INTERRUPT_STAGES = {"QUESTION_ANSWER", "OBJECTIONS"}

# For each stage, the only stages the LLM is allowed to request a transition to.
# Python-controlled transitions are handled separately in _auto_advance_stage().
_LLM_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "GREET":            {"DISCOVERY", "QUESTION_ANSWER"},
    "DISCOVERY":        {"QUESTION_ANSWER", "OBJECTIONS"},   # Python gates → GAP_CALC or RECOMMEND
    "GAP_CALC":         {"POSITION", "QUESTION_ANSWER", "OBJECTIONS"},
    "POSITION":         {"RECOMMEND", "QUESTION_ANSWER", "OBJECTIONS"},
    "RECOMMEND":        {"VARIANTS", "EXPLAIN", "QUESTION_ANSWER", "OBJECTIONS"},
    "VARIANTS":         {"CLOSE", "QUESTION_ANSWER", "OBJECTIONS"},
    "EXPLAIN":          {"CLOSE", "QUESTION_ANSWER", "OBJECTIONS"},
    "OBJECTIONS":       set(),    # Python always returns after 1 turn
    "QUESTION_ANSWER":  set(),    # Python always returns after 1 turn
    "CLOSE":            {"CLOSE", "QUESTION_ANSWER"},
}


@dataclass
class TurnAnalysis:
    stage: str
    interest_delta: int
    objection_category: Optional[str]
    objection_resolved: bool
    close_readiness_delta: int
    emotional_state: str = "curious"
    close_substage: str = ""      # populated only when stage == CLOSE
    position_skip: bool = False   # True if LLM signals POSITION should be skipped


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
    Returns (text, None) if no tag is present.
    """
    match = _META_PATTERN.search(text)
    if not match:
        return text.strip(), None

    raw_tag = match.group(1)
    clean = (text[: match.start()] + text[match.end():]).strip()

    category = _extract(raw_tag, "objection") or None
    if category == "none":
        category = None

    raw_stage = _extract(raw_tag, "stage").upper()
    stage = raw_stage if raw_stage in VALID_STAGES else ""

    raw_emotion = _extract(raw_tag, "emotional_state").lower()
    emotional_state = raw_emotion if raw_emotion in VALID_EMOTIONAL_STATES else "curious"

    raw_close_sub = _extract(raw_tag, "close_substage").upper()
    close_substage = raw_close_sub if raw_close_sub in VALID_CLOSE_SUBSTAGES else ""

    position_skip = _extract(raw_tag, "position_skip", "false").lower() == "true"

    analysis = TurnAnalysis(
        stage=stage,
        interest_delta=_int_val(raw_tag, "interest_delta", 0),
        objection_category=category,
        objection_resolved=_extract(raw_tag, "objection_resolved", "false").lower() == "true",
        close_readiness_delta=_int_val(raw_tag, "close_readiness_delta", 0),
        emotional_state=emotional_state,
        close_substage=close_substage,
        position_skip=position_skip,
    )
    return clean, analysis


def apply_analysis(
    memory: "SessionMemory", analysis: TurnAnalysis, user_text: str
) -> None:
    """Apply a TurnAnalysis to the session memory in place."""
    intel = memory.intelligence

    # ── Stage transition logic ─────────────────────────────────────────────
    if analysis.stage and analysis.stage != memory.stage:
        current = memory.stage
        requested = analysis.stage

        # Interrupt stages (QUESTION_ANSWER, OBJECTIONS) are always allowed
        if requested in _INTERRUPT_STAGES:
            memory.previous_stage = current
            memory.return_to_stage = current
            memory.stage = requested
            memory.turn_in_stage = 0

        # DISCOVERY → next: LLM cannot advance out of DISCOVERY.
        # Python gates this via discovery_sufficient() in _auto_advance_stage().
        elif current == "DISCOVERY":
            memory.turn_in_stage += 1  # block LLM, keep collecting

        # POSITION skip: LLM signals position_skip=true → advance to RECOMMEND
        elif current == "POSITION" and analysis.position_skip and requested == "RECOMMEND":
            memory.position_skipped = True
            memory.previous_stage = current
            memory.stage = "RECOMMEND"
            memory.turn_in_stage = 0

        # LLM-allowed transitions
        elif requested in _LLM_ALLOWED_TRANSITIONS.get(current, set()):
            memory.previous_stage = current
            memory.stage = requested
            memory.turn_in_stage = 0

        # All other LLM transition requests are blocked
        else:
            memory.turn_in_stage += 1

    else:
        memory.turn_in_stage += 1

    # ── Close substage ─────────────────────────────────────────────────────
    if memory.stage == "CLOSE" and analysis.close_substage:
        _apply_close_substage(memory, analysis.close_substage)

    # ── Emotional state ────────────────────────────────────────────────────
    if analysis.emotional_state:
        memory.emotional_state = analysis.emotional_state

    # ── Explain subtopic advance (savings plans only) ──────────────────────
    if memory.stage == "EXPLAIN" and memory.turn_in_stage > 0:
        if memory.explain_topics and memory.explain_subtopic_index < len(memory.explain_topics) - 1:
            memory.explain_subtopic_index += 1

    # ── Interest / close readiness ─────────────────────────────────────────
    intel.interest_level = max(0, min(100, intel.interest_level + analysis.interest_delta))
    intel.close_readiness = max(0, min(100, intel.close_readiness + analysis.close_readiness_delta))

    # ── Objection tracking ─────────────────────────────────────────────────
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

    # ── Derived intent ─────────────────────────────────────────────────────
    intel.update_intent()

    # ── Track questions ────────────────────────────────────────────────────
    if "?" in user_text and user_text.strip() not in memory.questions_asked:
        memory.questions_asked.append(user_text.strip()[:80])


# ── Close substage machine ─────────────────────────────────────────────────────

def _apply_close_substage(memory: "SessionMemory", requested: str) -> None:
    """Advance close_substage only to valid next states."""
    current = memory.close_substage
    allowed_next: dict[str, set[str]] = {
        "PURCHASE_INTENT": {"PROCEED", "FEEDBACK"},
        "PROCEED":         {"CLOSED"},
        "FEEDBACK":        {"CLOSED"},
        "CLOSED":          set(),
    }
    if requested in allowed_next.get(current, set()):
        memory.close_substage = requested
        memory.turn_in_stage = 0
