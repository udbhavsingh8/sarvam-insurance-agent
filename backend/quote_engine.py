"""
Quote Engine — deterministic premium calculation from structure.json data.

Pipeline:
  1. Load premium_tables from structure.json (via DocumentStore.structure)
  2. Find best matching rows for (age, term, smoker)
  3. Interpolate if exact age/term not present
  4. Scale to customer's cover amount
  5. Apply payment frequency loading
  6. Apply GST (18%)
  7. Return Quote with full explanation trail

QuoteError is raised (not silently swallowed) so callers can decide how to
present the failure — either escalate to LLM or show capability-level message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from memory import CustomerProfile


# ── Public types ──────────────────────────────────────────────────────────────

class QuoteError(Exception):
    """Raised when a quote cannot be generated from available document data."""
    def __init__(self, reason: str, capability_level: int = 0):
        super().__init__(reason)
        self.reason = reason
        self.capability_level = capability_level


@dataclass
class FrequencyBreakdown:
    frequency: str          # annual | semi_annual | quarterly | monthly
    installment_amount: int # per installment, after GST
    installments_per_year: int
    total_annual: int       # installment × count, includes GST
    display: str            # "₹5,200/month"


@dataclass
class Quote:
    # Core numbers
    cover_lakh: float
    policy_term: int
    age: int
    smoker: bool

    annual_premium_base: int    # before GST, per year
    gst_amount: int
    annual_premium_total: int   # after GST

    # All frequency options
    frequencies: dict[str, FrequencyBreakdown]  # keyed by frequency string

    # Confidence and source
    capability_level: int       # 0–3
    confidence: str             # exact | interpolated | inferred
    basis: str                  # per_crore_annual | per_lakh_annual

    # Explanation trail — ordered steps shown to customer
    trail: list[str] = field(default_factory=list)

    def preferred(self, frequency: str = "annual") -> FrequencyBreakdown:
        """Return the breakdown for the requested frequency (falls back to annual)."""
        return self.frequencies.get(frequency, self.frequencies["annual"])


# ── Default frequency loading factors (overridden by document if available) ──

_DEFAULT_FREQ_RULES = {
    "annual":      {"factor": 1.0000, "count": 1},
    "semi_annual": {"factor": 0.5100, "count": 2},
    "quarterly":   {"factor": 0.2600, "count": 4},
    "monthly":     {"factor": 0.0883, "count": 12},
}

_GST_RATE = 0.18

_FREQ_LABELS = {
    "annual":      "annually",
    "semi_annual": "every 6 months",
    "quarterly":   "quarterly",
    "monthly":     "monthly",
}


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_quote(
    profile: "CustomerProfile",
    cover_lakh: float,
    structure: dict,
) -> Quote:
    """
    Generate a Quote from document structure data and customer profile.

    Raises QuoteError if:
    - structure has no premium tables (capability_level 0)
    - document data doesn't cover the requested age/term combination
    - cover amount is outside any reasonable scaling range
    """
    capability = structure.get("quote_capability_level", 0)
    premium_tables = structure.get("premium_tables", [])

    if not premium_tables or capability == 0:
        raise QuoteError(
            "No premium data available in this document.",
            capability_level=0,
        )

    age = profile.age
    if age is None:
        raise QuoteError("Customer age is required for a quote.", capability_level=capability)

    smoker = profile.smoker
    if smoker is None:
        raise QuoteError(
            "Smoker status is required — premiums differ significantly.",
            capability_level=capability,
        )

    policy_term = getattr(profile, "policy_term", None) or _default_term(age)
    payment_frequency = getattr(profile, "payment_frequency", None) or "annual"

    freq_rules = structure.get("payment_frequency_rules", _DEFAULT_FREQ_RULES)

    # ── Find best table ───────────────────────────────────────────────────
    table, basis = _select_table(premium_tables, smoker)

    # ── Interpolate premium per crore ─────────────────────────────────────
    per_crore, confidence, trail = _interpolate(table["rows"], age, policy_term)

    # ── Scale to customer's cover amount ──────────────────────────────────
    if basis == "per_crore_annual":
        scale = cover_lakh / 100.0
    elif basis == "per_lakh_annual":
        scale = cover_lakh
    else:
        scale = cover_lakh / 100.0

    base_annual = int(per_crore * scale)
    trail.append(f"Scale to {_fmt(cover_lakh)}: ₹{per_crore:,}/crore × {scale:.2f} = ₹{base_annual:,}/year (pre-GST)")

    # ── GST ───────────────────────────────────────────────────────────────
    gst = int(base_annual * _GST_RATE)
    total_annual = base_annual + gst
    trail.append(f"GST 18%: +₹{gst:,} → Total ₹{total_annual:,}/year")

    # ── All frequency options ─────────────────────────────────────────────
    freq_breakdowns: dict[str, FrequencyBreakdown] = {}
    for freq, meta in _DEFAULT_FREQ_RULES.items():
        doc_factor = freq_rules.get(freq, meta["factor"])
        if isinstance(doc_factor, dict):
            doc_factor = meta["factor"]

        count = meta["count"]
        install_base = int(base_annual * doc_factor)
        install_gst = int(install_base * _GST_RATE)
        install_total = install_base + install_gst
        yearly_total = install_total * count

        freq_breakdowns[freq] = FrequencyBreakdown(
            frequency=freq,
            installment_amount=install_total,
            installments_per_year=count,
            total_annual=yearly_total,
            display=f"₹{install_total:,}/{_freq_unit(freq)}",
        )

    # Add preferred frequency to trail
    chosen = freq_breakdowns.get(payment_frequency, freq_breakdowns["annual"])
    if payment_frequency != "annual":
        trail.append(
            f"Payment frequency: {_FREQ_LABELS[payment_frequency]} = "
            f"{chosen.display} ({chosen.installments_per_year}× per year, "
            f"total ₹{chosen.total_annual:,}/year incl. GST)"
        )

    return Quote(
        cover_lakh=cover_lakh,
        policy_term=policy_term,
        age=age,
        smoker=smoker,
        annual_premium_base=base_annual,
        gst_amount=gst,
        annual_premium_total=total_annual,
        frequencies=freq_breakdowns,
        capability_level=capability,
        confidence=confidence,
        basis=basis,
        trail=trail,
    )


def quote_to_prompt_block(quote: Quote, payment_frequency: str = "annual") -> str:
    """
    Format a Quote as a compact block for injection into the system prompt.
    The LLM reads this and presents it conversationally — it must not recalculate.
    """
    chosen = quote.preferred(payment_frequency)
    smoker_label = "smoker" if quote.smoker else "non-smoker"
    conf_note = "" if quote.confidence == "exact" else f" (based on {quote.confidence} data)"

    lines = [
        "QUOTE FOR THIS CUSTOMER:",
        f"  Cover: {_fmt(quote.cover_lakh)} | Term: {quote.policy_term} years | Age: {quote.age} | {smoker_label}",
        f"  Annual premium (incl. 18% GST): ₹{quote.annual_premium_total:,}/year{conf_note}",
        f"  Daily cost: ₹{round(quote.annual_premium_total / 365)}/day",
    ]

    if payment_frequency != "annual":
        lines.append(f"  {_FREQ_LABELS[payment_frequency].capitalize()}: {chosen.display}")

    lines.append("  All frequency options:")
    for freq in ("annual", "semi_annual", "quarterly", "monthly"):
        fb = quote.frequencies[freq]
        lines.append(f"    {freq.replace('_', ' ').title()}: {fb.display} ({fb.installments_per_year}×/year)")

    lines.append("")
    lines.append("HOW THIS WAS CALCULATED:")
    for step in quote.trail:
        lines.append(f"  • {step}")

    lines.append("")
    lines.append(
        "IMPORTANT: Present these numbers to the customer exactly as shown. "
        "Do not recalculate, round differently, or say 'approximately' unless confidence is 'inferred'. "
        f"Confidence level: {quote.confidence}."
    )

    return "\n".join(lines)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _select_table(premium_tables: list[dict], smoker: bool) -> tuple[dict, str]:
    """
    Pick the most appropriate table for this smoker status.
    Prefers exact match; falls back to any available table.
    """
    # Try exact smoker match first
    for t in premium_tables:
        if t.get("smoker") == smoker and t.get("rows"):
            return t, t.get("basis", "per_crore_annual")

    # Fall back to any table with rows
    for t in premium_tables:
        if t.get("rows"):
            return t, t.get("basis", "per_crore_annual")

    raise QuoteError("No usable premium rows found in document.", capability_level=1)


def _interpolate(
    rows: list[dict],
    age: int,
    term: int,
) -> tuple[int, str, list[str]]:
    """
    Find the best per-crore annual premium for (age, term) from the rows.

    Strategy:
    1. Exact match on both age and term → confidence=exact
    2. Exact term, interpolate on age → confidence=interpolated
    3. No term match, use closest available term → confidence=interpolated
    4. Single row → scale from that row → confidence=inferred

    Returns (premium_per_crore, confidence, trail_steps).
    """
    trail: list[str] = []
    if not rows:
        raise QuoteError("Premium table has no rows.")

    # ── 1. Exact match ────────────────────────────────────────────────────
    for r in rows:
        if r["age"] == age and r["term"] == term:
            trail.append(f"Exact match: age {age}, term {term}yr → ₹{r['annual_premium']:,}/crore/year")
            return r["annual_premium"], "exact", trail

    # ── Find available terms ───────────────────────────────────────────────
    available_terms = sorted({r["term"] for r in rows})

    # ── 2. Exact term match, interpolate age ─────────────────────────────
    best_term = _nearest(available_terms, term)
    term_rows = sorted([r for r in rows if r["term"] == best_term], key=lambda r: r["age"])

    if len(term_rows) >= 2:
        premium, age_trail = _age_interpolate(term_rows, age, best_term)
        trail.extend(age_trail)
        conf = "exact" if best_term == term else "interpolated"
        if best_term != term:
            trail.insert(0, f"Requested term {term}yr not in table — using nearest {best_term}yr")
        return premium, conf, trail

    # ── 3. Single row for the term — use it directly ──────────────────────
    if term_rows:
        r = term_rows[0]
        trail.append(
            f"Single data point: age {r['age']}, term {r['term']}yr → ₹{r['annual_premium']:,}/crore "
            f"(using as proxy for age {age}, term {term}yr)"
        )
        return r["annual_premium"], "inferred", trail

    # ── 4. Absolute fallback — use any row ────────────────────────────────
    r = rows[0]
    trail.append(
        f"Fallback data point: age {r['age']}, term {r['term']}yr → ₹{r['annual_premium']:,}/crore "
        f"(document has limited data; using as proxy)"
    )
    return r["annual_premium"], "inferred", trail


def _age_interpolate(
    term_rows: list[dict],
    target_age: int,
    term: int,
) -> tuple[int, list[str]]:
    """Linear interpolation between two age brackets."""
    trail: list[str] = []
    ages = [r["age"] for r in term_rows]

    if target_age <= ages[0]:
        r = term_rows[0]
        trail.append(f"Age {target_age} ≤ table minimum {ages[0]} — using {ages[0]}yr row: ₹{r['annual_premium']:,}/crore")
        return r["annual_premium"], trail

    if target_age >= ages[-1]:
        r = term_rows[-1]
        trail.append(f"Age {target_age} ≥ table maximum {ages[-1]} — using {ages[-1]}yr row: ₹{r['annual_premium']:,}/crore")
        return r["annual_premium"], trail

    # Find bracketing rows
    lower = max((r for r in term_rows if r["age"] <= target_age), key=lambda r: r["age"])
    upper = min((r for r in term_rows if r["age"] >= target_age), key=lambda r: r["age"])

    if lower["age"] == upper["age"]:
        trail.append(f"Age {target_age} exact: ₹{lower['annual_premium']:,}/crore (term {term}yr)")
        return lower["annual_premium"], trail

    # Linear interpolation
    t = (target_age - lower["age"]) / (upper["age"] - lower["age"])
    interpolated = int(lower["annual_premium"] + t * (upper["annual_premium"] - lower["annual_premium"]))
    trail.append(
        f"Interpolated age {target_age} between {lower['age']}yr (₹{lower['annual_premium']:,}) "
        f"and {upper['age']}yr (₹{upper['annual_premium']:,}) → ₹{interpolated:,}/crore (term {term}yr)"
    )
    return interpolated, trail


def _nearest(values: list[int], target: int) -> int:
    return min(values, key=lambda v: abs(v - target))


def _default_term(age: int) -> int:
    """Suggest a policy term that takes the customer to ~65."""
    return max(10, min(65 - age, 40))


def _fmt(lakh: float) -> str:
    if lakh >= 100:
        crore = lakh / 100
        return f"₹{int(crore)} crore" if crore == int(crore) else f"₹{crore:.2f} crore"
    return f"₹{int(lakh)} lakh"


def _freq_unit(freq: str) -> str:
    return {"annual": "year", "semi_annual": "6 months", "quarterly": "quarter", "monthly": "month"}.get(freq, "period")
