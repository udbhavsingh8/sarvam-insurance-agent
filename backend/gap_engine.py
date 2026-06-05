"""
Gap Calculation Engine — deterministic income-replacement gap for term plans.

Called at GAP_CALC stage. Produces a structured dict AND a ready-to-speak
text block that Arjun reads out loud to show the customer their protection gap.

Inputs (all from CustomerProfile):
  income_range        — "25 LPA", "₹2,00,000/month", etc. (parsed to LPA float)
  years_of_support    — how many years family needs income (default: 20)
  liabilities_lakh    — outstanding loans (default: 0)
  existing_cover_lakh — numeric existing life cover (default: 0)
  dependents          — number of dependents (used for commentary, not calc)
  age                 — used for commentary

Output dict keys:
  income_lpa              float
  years_of_support        int
  income_protection_lakh  float   (income_lpa × years × 100)
  liabilities_lakh        float
  existing_cover_lakh     float
  gap_lakh                float   (protection + liabilities - existing)
  gap_display             str     ("₹X crore" or "₹X lakh")
  spoken_walkthrough      str     (ready-to-read text for Arjun)
  assumptions_made        list    (list of defaults applied — for transparency)
"""

from __future__ import annotations
import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from memory import CustomerProfile

_DEFAULT_YEARS = 20          # years of income replacement if not stated
_DEFAULT_EXISTING = 0.0      # lakh existing cover if not stated
_DEFAULT_LIABILITIES = 0.0   # lakh loans if not stated


def _parse_income_lpa(income_range: Optional[str]) -> Optional[float]:
    """Convert income_range string to LPA float. Returns None if unparseable."""
    if not income_range:
        return None
    s = income_range.lower().replace(",", "").replace("₹", "").strip()

    # "25 LPA", "25 lpa"
    m = re.search(r"([\d.]+)\s*lpa", s)
    if m:
        return float(m.group(1))

    # "25 lakh per annum / year / annual", "25 lakh"
    m = re.search(r"([\d.]+)\s*lakh", s)
    if m:
        return float(m.group(1))

    # "25 crore" (edge case — very high income)
    m = re.search(r"([\d.]+)\s*crore", s)
    if m:
        return float(m.group(1)) * 100

    # Monthly: "₹200000/month", "2,00,000 per month"
    m = re.search(r"([\d.]+)\s*(?:/month|per month|monthly|pm\b)", s)
    if m:
        monthly = float(m.group(1))
        return round(monthly * 12 / 100_000, 1)  # convert to LPA

    # Plain number ≥ 5 digits → assume annual rupees
    m = re.search(r"(\d{5,})", s)
    if m:
        return round(float(m.group(1)) / 100_000, 1)

    return None


def _fmt_lakh(lakh: float) -> str:
    """Format a lakh amount as crore or lakh string."""
    if lakh >= 100:
        crore = lakh / 100
        if crore == int(crore):
            return f"₹{int(crore)} crore"
        return f"₹{crore:.1f} crore"
    return f"₹{int(lakh)} lakh" if lakh == int(lakh) else f"₹{lakh:.0f} lakh"


def build_gap_calculation(profile: "CustomerProfile") -> Optional[dict]:
    """
    Compute the protection gap from the customer profile.
    Returns None if income is unknown (can't compute gap without it).
    """
    income_lpa = _parse_income_lpa(profile.income_range)
    if income_lpa is None:
        return None

    assumptions: list[str] = []

    years = profile.years_of_support
    if years is None:
        years = _DEFAULT_YEARS
        assumptions.append(f"assuming {_DEFAULT_YEARS} years of income replacement (you didn't specify)")

    liabilities = profile.liabilities_lakh or _DEFAULT_LIABILITIES
    if profile.liabilities_lakh is None:
        assumptions.append("assuming no outstanding loans (you didn't mention any)")

    existing = profile.existing_cover_lakh or _DEFAULT_EXISTING
    if profile.existing_cover_lakh is None and (
        profile.existing_coverage is None or profile.existing_coverage == "none"
    ):
        assumptions.append("assuming no existing life cover")
    elif profile.existing_cover_lakh is None and profile.existing_coverage in ("some", "adequate"):
        assumptions.append("existing cover amount not specified — treated as zero in this calculation")

    income_protection = income_lpa * years * 100 / 100  # income_lpa is in lakh per year * 100 = lakh... wait

    # income_lpa = 25 (lakhs per year)
    # years = 20
    # income protection needed = 25 × 20 = 500 lakh = ₹5 crore
    income_protection_lakh = income_lpa * years  # in lakh

    gap_lakh = income_protection_lakh + liabilities - existing
    gap_lakh = max(0.0, gap_lakh)

    # Build the spoken walkthrough
    lines = []
    lines.append(f"Income: {_fmt_lakh(income_lpa)} per year × {years} years = {_fmt_lakh(income_protection_lakh)}")
    if liabilities > 0:
        lines.append(f"Outstanding loans: + {_fmt_lakh(liabilities)}")
    if existing > 0:
        lines.append(f"Existing cover: − {_fmt_lakh(existing)}")
    lines.append(f"─────────────────────────────")
    lines.append(f"Protection gap: {_fmt_lakh(gap_lakh)}")
    if assumptions:
        lines.append(f"\n(Assumptions made: {'; '.join(assumptions)})")

    spoken = "\n".join(lines)

    return {
        "income_lpa": income_lpa,
        "years_of_support": years,
        "income_protection_lakh": income_protection_lakh,
        "liabilities_lakh": liabilities,
        "existing_cover_lakh": existing,
        "gap_lakh": gap_lakh,
        "gap_display": _fmt_lakh(gap_lakh),
        "spoken_walkthrough": spoken,
        "assumptions_made": assumptions,
    }


def gap_to_prompt_block(gap: dict) -> str:
    """
    Format the gap dict into a prompt block injected into the system prompt at GAP_CALC stage.
    Arjun reads this calculation out loud to the customer.
    """
    block = (
        f"\nPROTECTION GAP CALCULATION FOR THIS CUSTOMER:\n"
        f"{gap['spoken_walkthrough']}\n\n"
        f"INSTRUCTION: Walk through this calculation with the customer exactly as shown above.\n"
        f"Use simple spoken language — not rupee symbols, not bullet points.\n"
        f"Say 'income of {_fmt_lakh(gap['income_lpa'])} per year, over {gap['years_of_support']} years, gives us {_fmt_lakh(gap['income_protection_lakh'])}' etc.\n"
        f"End by stating the gap clearly: 'So the protection you actually need is around {gap['gap_display']}.'\n"
        f"Do NOT compute different numbers. Use ONLY the numbers in this block.\n"
    )
    return block
