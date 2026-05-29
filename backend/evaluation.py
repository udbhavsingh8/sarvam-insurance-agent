"""Post-conversation evaluation using sarvam-m."""
from __future__ import annotations

import os
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory import SessionMemory

from llm import LLMClient
from prompts import EVALUATION_PROMPT


def _clean(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


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
    # Use lower temperature for evaluation — we want consistent, analytical output
    from llm import SARVAM_M
    from dataclasses import replace
    eval_config = replace(SARVAM_M, temperature=0.3, max_tokens=2048)
    from llm import LLMClient as _LC
    eval_llm = _LC(config=eval_config)

    raw = eval_llm.complete([{"role": "user", "content": prompt}])
    evaluation_text = _clean(raw)

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
