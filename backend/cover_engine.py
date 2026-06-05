"""
Cover Amount Engine — deterministic cover recommendation from customer profile.

Separates cover calculation from premium calculation so each can evolve
independently. The quote_engine consumes CoverRecommendation.cover_lakh.

Rules (term insurance):
  base = income_lpa × multiplier
  + liabilities_lakh (home loan, etc.)
  - existing_coverage_lakh (what they already have)
  = recommended_lakh  (clamped ₹25L – ₹10Cr)

  multiplier = 20 if dependents and income < 10 LPA  (high vulnerability)
             = 15 if dependents
             = 10 if no dependents

  If customer provides explicit cover override, that takes precedence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from memory import CustomerProfile


@dataclass
class CoverRecommendation:
    cover_lakh: float           # recommended cover in lakh
    cover_display: str          # "₹1.5 crore" or "₹75 lakh"
    rationale_steps: list[str]  # ordered explanation for quote trail
    is_override: bool = False   # True when customer explicitly stated a cover amount


_COVER_CAP_LAKH = 1000   # ₹10 crore max
_COVER_FLOOR_LAKH = 25   # ₹25 lakh min


def recommend_cover(profile: "CustomerProfile") -> Optional[CoverRecommendation]:
    """
    Return a CoverRecommendation or None if profile has too little data.
    Called before CLOSE so the quote engine has a cover amount to work with.
    """
    # ── Explicit override wins ──────────────────────────────────────────
    if getattr(profile, "cover_amount_override_lakh", None):
        lakh = float(profile.cover_amount_override_lakh)
        return CoverRecommendation(
            cover_lakh=lakh,
            cover_display=_fmt(lakh),
            rationale_steps=[f"Customer requested {_fmt(lakh)} cover"],
            is_override=True,
        )

    if profile.age is None:
        return None

    income_lpa = _parse_income_lpa(getattr(profile, "income_range", None))
    if income_lpa is None:
        return None

    has_dependents = (
        (profile.dependents is not None and profile.dependents > 0)
        or profile.marital_status == "married"
    )

    # ── Multiplier ──────────────────────────────────────────────────────
    if has_dependents and income_lpa < 10:
        multiplier = 20
    elif has_dependents:
        multiplier = 15
    else:
        multiplier = 10

    steps: list[str] = []
    base = income_lpa * multiplier
    steps.append(f"Income {income_lpa} LPA × {multiplier}x = ₹{base:.0f} lakh base cover")

    # ── Add liabilities ─────────────────────────────────────────────────
    liabilities = float(getattr(profile, "liabilities_lakh", None) or 0)
    if liabilities > 0:
        base += liabilities
        steps.append(f"+ ₹{liabilities:.0f} lakh outstanding loans")

    # ── Subtract existing coverage ──────────────────────────────────────
    existing_lakh = _parse_existing_coverage_lakh(profile.existing_coverage)
    if existing_lakh > 0:
        base -= existing_lakh
        steps.append(f"− ₹{existing_lakh:.0f} lakh existing coverage")

    # ── Round and clamp ─────────────────────────────────────────────────
    cover_lakh = round(base / 25) * 25  # round to nearest ₹25 lakh
    cover_lakh = max(_COVER_FLOOR_LAKH, min(cover_lakh, _COVER_CAP_LAKH))

    steps.append(f"Recommended cover: {_fmt(cover_lakh)}")

    return CoverRecommendation(
        cover_lakh=cover_lakh,
        cover_display=_fmt(cover_lakh),
        rationale_steps=steps,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_income_lpa(income_range: Optional[str]) -> Optional[float]:
    if not income_range:
        return None
    s = income_range.lower().replace(",", "")
    m = re.search(r"([\d.]+)\s*lpa", s)
    if m:
        return float(m.group(1))
    m = re.search(r"([\d.]+)\s*lakh", s)
    if m:
        return float(m.group(1))
    m = re.search(r"([\d.]+)/month", s)
    if m:
        return round(float(m.group(1)) * 12 / 100000, 1)
    m = re.search(r"₹?([\d.]+)$", s.strip())
    if m:
        val = float(m.group(1))
        if val >= 100000:
            return round(val / 100000, 1)
        if val >= 1000:
            return round(val * 12 / 100000, 1)
    return None


def _parse_existing_coverage_lakh(existing: Optional[str]) -> float:
    """Convert profile.existing_coverage string to a lakh value."""
    if not existing:
        return 0
    s = existing.lower()
    if "none" in s or "no " in s:
        return 0
    # "some" / "adequate" → treat as ₹25 lakh placeholder
    if "some" in s:
        return 25
    if "adequate" in s:
        return 50
    # Numeric — "50 lakh" / "1 crore" / "25L"
    m = re.search(r"([\d.]+)\s*crore", s)
    if m:
        return float(m.group(1)) * 100
    m = re.search(r"([\d.]+)\s*(?:lakh|l\b)", s)
    if m:
        return float(m.group(1))
    return 0


def _fmt(lakh: float) -> str:
    if lakh >= 100:
        crore = lakh / 100
        return f"₹{int(crore)} crore" if crore == int(crore) else f"₹{crore:.2f} crore"
    return f"₹{int(lakh)} lakh"
