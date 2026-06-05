"""Post-conversation evaluation."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory import SessionMemory

from llm import LLMClient
from prompts import EVALUATION_PROMPT


def evaluate_session(memory: "SessionMemory", character_name: str) -> dict:
    """
    Generate a structured post-conversation evaluation.
    Called once at session end (via POST /evaluate endpoint).
    Returns a dict with evaluation text and key metrics.
    """
    transcript = "\n".join(
        f"{t['role'].upper()} (turn {t['turn']}): {t['text']}"
        for t in memory.turn_log
    )

    objections_detail = (
        "; ".join(
            f"{o['category']} — {'resolved' if o['resolved'] else 'unresolved'}: {o['text'][:50]}"
            for o in memory.intelligence.objections
        )
        or "none raised"
    )

    prompt = EVALUATION_PROMPT.format(
        transcript=transcript or "(no turns recorded)",
        character_name=character_name,
        turn_count=memory.turn_count,
        stages_visited=", ".join(memory.stages_visited()) or "GREETING",
        interest_level=memory.intelligence.interest_level,
        close_readiness=memory.intelligence.close_readiness,
        buying_intent=memory.intelligence.buying_intent,
        objections_detail=objections_detail,
        lead_score=memory.intelligence.lead_score(),
    )

    llm = LLMClient()
    raw = llm.complete([{"role": "user", "content": prompt}])
    evaluation_text = raw.strip()

    return {
        "evaluation": evaluation_text,
        "lead_score": memory.intelligence.lead_score(),
        "interest_level": memory.intelligence.interest_level,
        "close_readiness": memory.intelligence.close_readiness,
        "buying_intent": memory.intelligence.buying_intent,
        "stages_visited": memory.stages_visited(),
        "objections_raised": len(memory.intelligence.objections),
        "objections_resolved": sum(
            1 for o in memory.intelligence.objections if o.get("resolved")
        ),
        "positive_signals": memory.intelligence.positive_signals,
        "turn_count": memory.turn_count,
    }
