"""Session memory architecture for the Insurance Sales Voice Agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

EXPLAIN_SUBTOPICS = [
    "coverage", "premiums", "policy_term",
    "death_benefit", "maturity_benefit",
    "riders", "tax_benefits", "exclusions",
]


def choose_explain_topics(plan_type: str, profile: "CustomerProfile") -> list[str]:
    """
    Return 3–4 most relevant EXPLAIN topics for this customer and plan type.
    Replaces the fixed 8-topic curriculum with a profile-aware sequence.

    Term plans never include maturity_benefit (there is none in a pure term plan).
    Smokers get premium implications moved up — it's their biggest concern.
    """
    base: dict[str, list[str]] = {
        "term":    ["coverage_and_sum_assured", "premium_and_daily_cost",
                    "death_benefit_and_payout", "key_exclusions"],
        "health":  ["coverage_and_sum_insured", "hospitalisation_and_claims",
                    "exclusions_and_waiting_period", "tax_benefits"],
        "ulip":    ["coverage_amount", "fund_options_and_risk",
                    "charges_and_liquidity", "tax_benefits"],
        "savings": ["coverage_amount", "maturity_benefit_and_corpus",
                    "premium_and_payment_term", "tax_benefits"],
        "pension": ["corpus_building_and_growth", "annuity_payout_options",
                    "vesting_age_and_term", "tax_benefits"],
        "child":   ["corpus_at_maturity", "premium_waiver_on_death",
                    "policy_term_and_flexibility", "tax_benefits"],
        "other":   ["coverage_amount", "key_benefits",
                    "premium_structure", "exclusions"],
    }

    topics = list(base.get(plan_type, base["other"]))

    # Profile-based reordering: smoker needs to understand premium impact first
    if plan_type == "term" and profile.smoker:
        topics = ["premium_and_daily_cost", "coverage_and_sum_assured",
                  "death_benefit_and_payout", "key_exclusions"]

    return topics


@dataclass
class CustomerProfile:
    """Collected customer information, built progressively during PROFILE stage."""
    age: Optional[int] = None
    gender: Optional[str] = None          # male | female | other
    marital_status: Optional[str] = None  # single | married | divorced | widowed
    dependents: Optional[int] = None      # number of dependents
    smoker: Optional[bool] = None
    existing_coverage: Optional[str] = None   # none | some | adequate
    financial_goal: Optional[str] = None  # protection | savings | both | retirement | child
    income_range: Optional[str] = None    # monthly income bracket
    health_conditions: Optional[str] = None   # none | pre-existing
    # Quote-specific fields (Phase 1B/1C)
    policy_term: Optional[int] = None          # requested policy term in years
    payment_frequency: Optional[str] = None   # annual | semi_annual | quarterly | monthly
    liabilities_lakh: Optional[float] = None  # outstanding loans in lakh
    cover_amount_override_lakh: Optional[float] = None  # customer-stated explicit cover
    fields_collected: list[str] = field(default_factory=list)

    def is_sufficient(self, plan_type: str = "other") -> bool:
        """
        True once the minimum profile fields for a meaningful recommendation are known.

        Criteria are intentionally minimal — only fields a customer naturally states
        in conversation. Gender and financial_goal are not required; they are rarely
        volunteered and their absence should not block stage progression.
        """
        if self.age is None:
            return False

        has_family_context = (
            self.dependents is not None or self.marital_status is not None
        )

        if plan_type == "term":
            # Term plans need: age, smoker status, income, and family context.
            return (
                self.smoker is not None
                and self.income_range is not None
                and has_family_context
            )

        if plan_type == "health":
            # Health plans need: age, family context, income.
            return has_family_context and self.income_range is not None

        # All other plan types: age + income is sufficient to proceed.
        return self.income_range is not None

    def apply_updates(self, updates: dict) -> None:
        """Apply a dict of profile fields extracted by profile_extractor."""
        if "age" in updates and self.age is None:
            self.age = updates["age"]
            if "age" not in self.fields_collected:
                self.fields_collected.append("age")
        if "smoker" in updates and self.smoker is None:
            self.smoker = updates["smoker"]
            if "smoker" not in self.fields_collected:
                self.fields_collected.append("smoker")
        if "income_range" in updates and self.income_range is None:
            self.income_range = updates["income_range"]
            if "income_range" not in self.fields_collected:
                self.fields_collected.append("income_range")
        if "dependents" in updates and self.dependents is None:
            self.dependents = updates["dependents"]
            if "dependents" not in self.fields_collected:
                self.fields_collected.append("dependents")
        if "marital_status" in updates and self.marital_status is None:
            self.marital_status = updates["marital_status"]
            if "marital_status" not in self.fields_collected:
                self.fields_collected.append("marital_status")
        if "gender" in updates and self.gender is None:
            self.gender = updates["gender"]
            if "gender" not in self.fields_collected:
                self.fields_collected.append("gender")
        if "policy_term" in updates and self.policy_term is None:
            self.policy_term = updates["policy_term"]
            if "policy_term" not in self.fields_collected:
                self.fields_collected.append("policy_term")
        if "payment_frequency" in updates and self.payment_frequency is None:
            self.payment_frequency = updates["payment_frequency"]
            if "payment_frequency" not in self.fields_collected:
                self.fields_collected.append("payment_frequency")
        if "liabilities_lakh" in updates and self.liabilities_lakh is None:
            self.liabilities_lakh = updates["liabilities_lakh"]
            if "liabilities_lakh" not in self.fields_collected:
                self.fields_collected.append("liabilities_lakh")
        if "cover_amount_override_lakh" in updates and self.cover_amount_override_lakh is None:
            self.cover_amount_override_lakh = updates["cover_amount_override_lakh"]
            if "cover_amount_override_lakh" not in self.fields_collected:
                self.fields_collected.append("cover_amount_override_lakh")

    def summary(self) -> str:
        if not self.fields_collected:
            return "No customer profile collected yet."
        lines = []
        if self.age is not None:
            lines.append(f"Age: {self.age}")
        if self.gender:
            lines.append(f"Gender: {self.gender}")
        if self.marital_status:
            lines.append(f"Marital status: {self.marital_status}")
        if self.dependents is not None:
            lines.append(f"Dependents: {self.dependents}")
        if self.smoker is not None:
            lines.append(f"Smoker: {'yes' if self.smoker else 'no'}")
        if self.existing_coverage:
            lines.append(f"Existing coverage: {self.existing_coverage}")
        if self.financial_goal:
            lines.append(f"Financial goal: {self.financial_goal}")
        if self.income_range:
            lines.append(f"Income range: {self.income_range}")
        if self.health_conditions:
            lines.append(f"Health: {self.health_conditions}")
        if self.policy_term is not None:
            lines.append(f"Policy term: {self.policy_term} years")
        if self.payment_frequency:
            lines.append(f"Payment frequency: {self.payment_frequency}")
        if self.liabilities_lakh is not None:
            lines.append(f"Outstanding loans: ₹{self.liabilities_lakh:.0f} lakh")
        if self.cover_amount_override_lakh is not None:
            lines.append(f"Requested cover: ₹{self.cover_amount_override_lakh:.0f} lakh")
        return "\n".join(lines)


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
    stage: str = "INTRODUCE"  # INTRODUCE|PROFILE|PERSONALIZE|EXPLAIN|HANDLE|CLOSE|QUESTION_ANSWER

    previous_stage: Optional[str] = None
    return_to_stage: Optional[str] = None   # set when entering QUESTION_ANSWER
    turn_in_stage: int = 0

    # ── Close substage machine (active only when stage == "CLOSE") ──
    # SUMMARY → PURCHASE_INTENT → PROCEED or FEEDBACK → CLOSED
    close_substage: str = "SUMMARY"

    # ── Customer emotional state (updated every turn from META tag) ──
    emotional_state: str = "curious"  # curious | engaged | hesitant | resistant | anxious | satisfied

    # ── Customer profile (built during PROFILE stage) ───────────────
    customer_profile: CustomerProfile = field(default_factory=CustomerProfile)

    # ── Explanation progress ────────────────────────────────────────────
    explain_subtopic_index: int = 0
    # Dynamic topic list — set at EXPLAIN entry from plan_type + customer profile.
    # Empty until first EXPLAIN turn; agent._build_messages() initializes it.
    explain_topics: list[str] = field(default_factory=list)

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
        Commit a language change on reasonable evidence.

        Rules:
        - Single detection at confidence ≥ 0.70 → commit immediately.
        - Below 0.70 or empty code → ignored.
        """
        if not language_code or confidence < 0.7:
            return
        # Commit immediately at ≥ 0.70 — single detection is enough
        self.detected_language = language_code
        self.language_confidence = confidence
        self._language_candidate = ""
        self._language_candidate_confidence = 0.0

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

        # Customer profile
        profile_summary = self.customer_profile.summary()
        if profile_summary != "No customer profile collected yet.":
            lines.append(f"Customer profile:\n{profile_summary}")

        lead = self.intelligence.lead_score()
        close_hint = ""
        if lead >= 70:
            close_hint = " ← HIGH — move toward recommendation and close"
        elif lead >= 50:
            close_hint = " ← WARM — start building toward recommendation"

        lines.append(
            f"Interest: {self.intelligence.interest_level}/100  "
            f"Close readiness: {self.intelligence.close_readiness}/100  "
            f"Lead score: {lead}/100{close_hint}  "
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
