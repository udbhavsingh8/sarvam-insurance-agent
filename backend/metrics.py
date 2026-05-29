"""Structured JSONL logging for turn and session metrics."""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from memory import SessionMemory

_LOGS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))


@dataclass
class TurnMetrics:
    session_id: str
    turn_id: int
    timestamp: float
    stt_latency_ms: int
    llm_latency_ms: int
    tts_latency_ms: int
    transcript_chars: int
    response_chars: int
    detected_language: str
    stage: str
    character: str
    stt_error: bool = False
    llm_error: bool = False
    tts_error: bool = False
    error_detail: Optional[str] = None


def log_turn(m: TurnMetrics) -> None:
    os.makedirs(_LOGS_DIR, exist_ok=True)
    _append(os.path.join(_LOGS_DIR, "turns.jsonl"), asdict(m))


def log_session(session_id: str, memory: "SessionMemory", duration_s: float) -> None:
    os.makedirs(_LOGS_DIR, exist_ok=True)
    record = {
        "session_id": session_id,
        "timestamp": time.time(),
        "duration_s": round(duration_s, 1),
        "character": memory.character_id,
        "turn_count": memory.turn_count,
        "final_stage": memory.stage,
        "final_language": memory.detected_language,
        "lead_score": memory.intelligence.lead_score(),
        "interest_level": memory.intelligence.interest_level,
        "buying_intent": memory.intelligence.buying_intent,
        "objections_raised": len(memory.intelligence.objections),
        "objections_resolved": sum(
            1 for o in memory.intelligence.objections if o.get("resolved")
        ),
    }
    _append(os.path.join(_LOGS_DIR, "sessions.jsonl"), record)


def _append(path: str, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
