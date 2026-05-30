"""Session memory architecture for the Insurance Sales Voice Agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CustomerIntelligence:
    """Live scoring of customer interest and sales readiness, updated every turn."""

    interest_level: int = 50        # 0–100, starts neutral
    buying_intent: str = "unknown"  # cold | warm | hot
    engagement_score: int = 50      # 0–100
    close_readiness: int = 0        # 0–100

    objections: list[dict] = field(default_factory=list)
    # each entry: {text, category, turn, resolved}
    # category: price | trust | timing | need | comparison | family

    positive_signals: list[str] = field(default_factory=list)
    hesitation_count: int = 0
    deflection_count: int = 0

    def lead_score(self) -> int:
        raised = len(self.objections)
        resolved = sum(1 for o in self.objections if o.get("resolved"))
        score = (
            self.interest_level * 0.40
            + self.close_readiness * 0.30
            + (resolved / max(raised, 1)) * 100 * 0.15
            + min(len(self.positive_signals) * 10, 100) * 0.15
        )
        return int(score)

    def update_intent(self) -> None:
        if self.interest_level >= 75 and self.close_readiness >= 60:
            self.buying_intent = "hot"
        elif self.interest_level >= 50:
            self.buying_intent = "warm"
        else:
            self.buying_intent = "cold"


@dataclass
class SessionMemory:
    """All state for a single customer session."""

    # ── Character and language ──────────────────────────────────────
    character_id: str = "arjun"
    detected_language: str = "en-IN"
    language_confidence: float = 0.0
    _language_candidate: str = field(default="", repr=False)
    _language_candidate_confidence: float = field(default=0.0, repr=False)

    # ── Sales stage machine ─────────────────────────────────────────
    stage: str = "CONNECT"  # CONNECT | QUALIFY | PITCH | HANDLE | CLOSE | QUESTION_ANSWER
    previous_stage: Optional[str] = None
    return_to_stage: Optional[str] = None   # set when entering QUESTION_ANSWER
    turn_in_stage: int = 0

    # ── Customer emotional state (updated every turn from META tag) ──
    emotional_state: str = "curious"  # curious | engaged | hesitant | resistant | anxious | satisfied

    # ── Customer profile (built during DISCOVERY / QUALIFICATION) ───
    customer_name: Optional[str] = None
    primary_need: Optional[str] = None      # protection | savings | both
    family_context: Optional[str] = None
    existing_coverage: Optional[bool] = None

    # ── Conversation facts ──────────────────────────────────────────
    questions_asked: list[str] = field(default_factory=list)
    features_explained: list[str] = field(default_factory=list)

    # ── Intelligence ────────────────────────────────────────────────
    intelligence: CustomerIntelligence = field(default_factory=CustomerIntelligence)

    # ── Counters ────────────────────────────────────────────────────
    turn_count: int = 0

    # ── Full turn log (for evaluation and summary) ──────────────────
    turn_log: list[dict] = field(default_factory=list)

    # ─────────────────────────────────────────────────────────────────

    def update_language(self, language_code: str, confidence: float) -> None:
        """
        Commit a language change only when we have strong evidence.

        Rules:
        - Single detection at confidence ≥ 0.85 → commit immediately.
        - Detection at 0.7–0.84 → store as candidate; commit only if the
          next detection also matches (two consecutive agreements).
        - Below 0.7 or empty code → ignored.
        """
        if not language_code or confidence < 0.7:
            return
        if confidence >= 0.85:
            self.detected_language = language_code
            self.language_confidence = confidence
            self._language_candidate = ""
            self._language_candidate_confidence = 0.0
        elif language_code == self._language_candidate:
            # Second consecutive detection of the same language at ≥ 0.7 — commit
            self.detected_language = language_code
            self.language_confidence = confidence
            self._language_candidate = ""
            self._language_candidate_confidence = 0.0
        else:
            # First detection at 0.7–0.84 — hold as candidate, wait for confirmation
            self._language_candidate = language_code
            self._language_candidate_confidence = confidence

    def log_turn(self, role: str, text: str) -> None:
        self.turn_log.append({
            "role": role,
            "text": text,
            "stage": self.stage,
            "turn": self.turn_count,
        })

    def memory_summary(self) -> str:
        """
        Compact context block injected into every LLM system prompt.
        Kept under ~200 tokens regardless of conversation length.
        """
        lines: list[str] = []

        if self.primary_need:
            lines.append(f"Customer primary need: {self.primary_need}")
        if self.family_context:
            lines.append(f"Family context: {self.family_context}")
        if self.existing_coverage is not None:
            lines.append(f"Existing coverage: {'yes' if self.existing_coverage else 'no'}")

        if self.questions_asked:
            recent = self.questions_asked[-3:]
            lines.append(f"Questions asked: {' | '.join(recent)}")

        if self.features_explained:
            lines.append(f"Already explained: {', '.join(self.features_explained[-4:])}")

        open_obj = [o for o in self.intelligence.objections if not o.get("resolved")]
        if open_obj:
            o = open_obj[-1]
            lines.append(f"Active objection: [{o['category']}] {o['text'][:60]}")

        if self.intelligence.positive_signals:
            lines.append(f"Positive signals: {', '.join(self.intelligence.positive_signals[-2:])}")

        lines.append(
            f"Interest: {self.intelligence.interest_level}/100  "
            f"Close readiness: {self.intelligence.close_readiness}/100  "
            f"Intent: {self.intelligence.buying_intent}  "
            f"Emotional state: {self.emotional_state}"
        )

        return "\n".join(lines) if lines else "First interaction — no history yet."

    def stages_visited(self) -> list[str]:
        """Ordered unique list of stages visited during the session."""
        seen: dict[str, None] = {}
        for t in self.turn_log:
            s = t.get("stage", "")
            if s:
                seen[s] = None
        return list(seen)
