"""Session memory architecture for the Insurance Sales Voice Agent.

Stage machine (new design):
  Term plans:    GREET → DISCOVERY → GAP_CALC → POSITION → RECOMMEND → VARIANTS → CLOSE
  Savings plans: GREET → DISCOVERY → RECOMMEND → EXPLAIN → CLOSE
  Any stage:     → QUESTION_ANSWER (interrupt, returns to previous)
                 → OBJECTIONS (interrupt, returns to previous)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Explain topics for savings/non-term plans (EXPLAIN stage) ─────────────────
# Term plans use the VARIANTS stage instead — these are only for savings/ULIP/pension/health.

def choose_explain_topics(plan_type: str, profile: "CustomerProfile") -> list[str]:
    """Return ordered EXPLAIN topics for non-term plans."""
    base: dict[str, list[str]] = {
        "health":  ["coverage_and_sum_insured", "hospitalisation_and_claims",
                    "exclusions_and_waiting_period", "tax_benefits"],
        "ulip":    ["coverage_amount", "fund_options_and_risk",
                    "charges_and_liquidity", "tax_benefits"],
        "savings": ["how_the_plan_works", "death_benefit_and_nominee_payout",
                    "maturity_benefit_and_bonuses", "tax_benefits"],
        "pension": ["corpus_building_and_growth", "annuity_payout_options",
                    "vesting_age_and_term", "tax_benefits"],
        "child":   ["corpus_at_maturity", "premium_waiver_on_death",
                    "policy_term_and_flexibility", "tax_benefits"],
        "other":   ["how_the_plan_works", "key_benefits",
                    "premium_structure", "exclusions"],
    }
    return list(base.get(plan_type, base["other"]))


@dataclass
class CustomerProfile:
    """
    Collected customer information — built progressively during DISCOVERY stage.

    New fields vs old design:
      years_of_support   — how many years family needs income if customer is gone
      existing_cover_lakh — numeric existing life cover (replaces categorical string)
      chosen_variant      — which product variant the customer chose (VARIANTS stage)

    Old field kept for backward compat:
      existing_coverage  — categorical "none|some|adequate" (still updated by LLM signals)
    """
    age: Optional[int] = None
    gender: Optional[str] = None           # male | female | other
    marital_status: Optional[str] = None   # single | married | divorced | widowed
    dependents: Optional[int] = None       # number of financially dependent people
    smoker: Optional[bool] = None
    existing_coverage: Optional[str] = None    # none | some | adequate (categorical)
    existing_cover_lakh: Optional[float] = None  # numeric existing cover in lakh
    financial_goal: Optional[str] = None   # protection | savings | both | retirement | child
    income_range: Optional[str] = None     # human-readable, e.g. "25 LPA"
    health_conditions: Optional[str] = None    # none | pre-existing
    years_of_support: Optional[int] = None    # years of income replacement needed
    chosen_variant: Optional[str] = None      # "life_protect" | "ci_rebalance" | "income_plus"

    # Quote-specific fields
    policy_term: Optional[int] = None
    payment_frequency: Optional[str] = None   # annual | semi_annual | quarterly | monthly
    liabilities_lakh: Optional[float] = None  # outstanding loans in lakh
    cover_amount_override_lakh: Optional[float] = None  # customer-stated explicit cover

    fields_collected: list[str] = field(default_factory=list)

    # ── Stage gate ────────────────────────────────────────────────────────────

    def discovery_sufficient(self, plan_type: str = "other") -> bool:
        """
        True when DISCOVERY has collected enough to move to the next stage.

        Gate: age + income_range only. Family context (dependents/marital) is
        collected conversationally but NOT a gate — regex extractors are too
        brittle for the infinite ways people describe family ("my son", "mera
        beta", "we are a family of four"). Gating on it causes stage lockup.

        Smoker, liabilities, existing cover, years_of_support are optional
        enrichment — the gap engine has sensible defaults for all of them.
        """
        return self.age is not None and self.income_range is not None

    def gap_calc_inputs_ready(self) -> bool:
        """True if we have enough for the gap calculation (age + income at minimum)."""
        return self.age is not None and self.income_range is not None

    def apply_updates(self, updates: dict) -> None:
        """Apply a dict of profile fields extracted by profile_extractor."""
        simple_fields = [
            "age", "smoker", "income_range", "dependents", "marital_status",
            "gender", "policy_term", "payment_frequency", "liabilities_lakh",
            "cover_amount_override_lakh", "existing_cover_lakh", "years_of_support",
            "health_conditions", "financial_goal", "chosen_variant",
        ]
        for f in simple_fields:
            if f in updates and getattr(self, f) is None:
                setattr(self, f, updates[f])
                if f not in self.fields_collected:
                    self.fields_collected.append(f)

        # existing_coverage categorical (allow overwrite if "none" → "some")
        if "existing_coverage" in updates:
            self.existing_coverage = updates["existing_coverage"]
            if "existing_coverage" not in self.fields_collected:
                self.fields_collected.append("existing_coverage")

    def summary(self) -> str:
        """Compact profile block injected into every system prompt."""
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
        if self.income_range:
            lines.append(f"Annual income: {self.income_range}")
        if self.liabilities_lakh is not None:
            lines.append(f"Outstanding loans: ₹{self.liabilities_lakh:.0f} lakh")
        if self.existing_coverage:
            lines.append(f"Existing coverage (category): {self.existing_coverage}")
        if self.existing_cover_lakh is not None:
            lines.append(f"Existing cover (numeric): ₹{self.existing_cover_lakh:.0f} lakh")
        if self.years_of_support is not None:
            lines.append(f"Years of support needed: {self.years_of_support}")
        if self.financial_goal:
            lines.append(f"Financial goal: {self.financial_goal}")
        if self.health_conditions:
            lines.append(f"Health: {self.health_conditions}")
        if self.policy_term is not None:
            lines.append(f"Preferred policy term: {self.policy_term} years")
        if self.payment_frequency:
            lines.append(f"Payment frequency: {self.payment_frequency}")
        if self.cover_amount_override_lakh is not None:
            lines.append(f"Requested cover: ₹{self.cover_amount_override_lakh:.0f} lakh")
        if self.chosen_variant:
            lines.append(f"Chosen variant: {self.chosen_variant}")
        return "\n".join(lines)


@dataclass
class CustomerIntelligence:
    """Live scoring of customer engagement and sales readiness."""

    interest_level: int = 50         # 0–100, starts neutral
    buying_intent: str = "unknown"   # cold | warm | hot
    engagement_score: int = 50       # 0–100
    close_readiness: int = 0         # 0–100
    gap_lakh: Optional[float] = None # computed protection gap in lakh (set at GAP_CALC)

    objections: list[dict] = field(default_factory=list)
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

    # ── Character and language ─────────────────────────────────────────────
    character_id: str = "arjun"
    detected_language: str = "en-IN"
    language_confidence: float = 0.0
    _language_candidate: str = field(default="", repr=False)
    _language_candidate_confidence: float = field(default=0.0, repr=False)

    # ── Sales stage machine ────────────────────────────────────────────────
    # Term:    GREET → DISCOVERY → GAP_CALC → POSITION → RECOMMEND → VARIANTS → CLOSE
    # Savings: GREET → DISCOVERY → RECOMMEND → EXPLAIN → CLOSE
    # Any:     → QUESTION_ANSWER | OBJECTIONS (both return to previous stage)
    stage: str = "GREET"

    previous_stage: Optional[str] = None
    return_to_stage: Optional[str] = None   # set when entering QUESTION_ANSWER / OBJECTIONS
    turn_in_stage: int = 0

    # ── Close substage machine (active only when stage == "CLOSE") ─────────
    close_substage: str = "PURCHASE_INTENT"

    # ── Customer emotional state (updated every turn from META tag) ────────
    emotional_state: str = "curious"

    # ── Customer profile ───────────────────────────────────────────────────
    customer_profile: CustomerProfile = field(default_factory=CustomerProfile)
    customer_name: Optional[str] = None

    # ── Explanation progress (savings/non-term plans only) ─────────────────
    explain_subtopic_index: int = 0
    explain_topics: list[str] = field(default_factory=list)

    # ── Conversation tracking ──────────────────────────────────────────────
    questions_asked: list[str] = field(default_factory=list)
    features_explained: list[str] = field(default_factory=list)
    position_skipped: bool = False   # True if POSITION stage was bypassed

    # ── Intelligence ───────────────────────────────────────────────────────
    intelligence: CustomerIntelligence = field(default_factory=CustomerIntelligence)

    # ── Counters ───────────────────────────────────────────────────────────
    turn_count: int = 0

    # ── Full turn log ──────────────────────────────────────────────────────
    turn_log: list[dict] = field(default_factory=list)

    # ──────────────────────────────────────────────────────────────────────

    def update_language(self, language_code: str, confidence: float) -> None:
        if not language_code or confidence < 0.7:
            return
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
        """Compact context block injected into every LLM system prompt."""
        lines: list[str] = []

        if self.customer_name:
            lines.append(f"Customer name: {self.customer_name}")

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

        profile_summary = self.customer_profile.summary()
        if profile_summary != "No customer profile collected yet.":
            lines.append(f"CUSTOMER PROFILE COLLECTED SO FAR:\n{profile_summary}")

        if self.intelligence.gap_lakh is not None:
            lines.append(f"Computed protection gap: ₹{self.intelligence.gap_lakh:.0f} lakh")

        lead = self.intelligence.lead_score()
        close_hint = ""
        if lead >= 70:
            close_hint = " ← HIGH"
        elif lead >= 50:
            close_hint = " ← WARM"

        lines.append(
            f"Interest: {self.intelligence.interest_level}/100  "
            f"Close readiness: {self.intelligence.close_readiness}/100  "
            f"Lead score: {lead}/100{close_hint}  "
            f"Intent: {self.intelligence.buying_intent}  "
            f"Emotional state: {self.emotional_state}"
        )

        return "\n".join(lines) if lines else "First interaction — no history yet."

    def stages_visited(self) -> list[str]:
        seen: dict[str, None] = {}
        for t in self.turn_log:
            s = t.get("stage", "")
            if s:
                seen[s] = None
        return list(seen)
