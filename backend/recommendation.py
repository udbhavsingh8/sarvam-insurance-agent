"""
Recommendation engine — calculates personalised cover amount and estimated
premium from the customer's profile and the ingested product brief.

This is deterministic Python arithmetic, not LLM inference.
The output is injected into the system prompt at EXPLAIN and CLOSE stages
so the advisor uses real profile-derived numbers instead of inventing them.

Output block (< 200 chars) example:
    Suggested cover: ₹1.5 crore  (15 LPA income × 10x rule + 2 dependents)
    Estimated premium: approx. ₹28/day (₹10,200/year)  — age 29, non-smoker
    Always say "approximately" — actual premium requires full underwriting.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from memory import CustomerProfile


# ── Term plan actuarial constants ─────────────────────────────────────────
# These are industry benchmarks for Indian term insurance.
# Source: publicly available rate cards from HDFC Life, LIC, Max Life (2023-24).

_TERM_BASE_PREMIUM_PER_CRORE = 8500   # ₹/year for 25-yr non-smoker, 30-yr term, ₹1 crore
_TERM_BASE_AGE = 25
_AGE_LOADING_PER_YEAR = 0.035         # 3.5% compound per year above base age
_SMOKER_LOADING = 0.65                # 65% extra for smokers
_COVER_MULTIPLIER_WITH_DEPENDENTS = 15   # income × 15 when customer has dependents
_COVER_MULTIPLIER_NO_DEPENDENTS = 10     # income × 10 when no dependents

# ── Health plan benchmarks ────────────────────────────────────────────────
_HEALTH_BASE_PREMIUM = 8000           # ₹/year for ₹5 lakh family floater, age ~35
_HEALTH_BASE_COVER_LAKH = 5


def build_recommendation_block(
    profile: "CustomerProfile",
    plan_meta: dict,
    brief_text: str = "",
) -> str:
    """
    Return a compact text block (< 220 chars) for injection into the system prompt.
    Returns empty string if the profile has too little data to be meaningful.
    """
    plan_type = plan_meta.get("plan_type", "other")

    rec = _compute(profile, plan_type, brief_text)
    if not rec:
        return ""

    lines = [
        f"Suggested cover: {rec['cover_display']}  ({rec['cover_rationale']})",
        f"Estimated premium: approx. {rec['premium_display']}  ({rec['premium_rationale']})",
        "Always say \"approximately\" — actual premium requires full underwriting by the insurer.",
    ]
    return "\n".join(lines)


# ── Internal computation ──────────────────────────────────────────────────

def _compute(
    profile: "CustomerProfile",
    plan_type: str,
    brief_text: str,
) -> Optional[dict]:
    if plan_type in ("term", "other"):
        return _term_rec(profile, brief_text)
    if plan_type == "health":
        return _health_rec(profile)
    # For ULIP, savings, pension, child — too product-specific for generic estimates.
    # Return None and let the LLM reference the brief instead.
    return None


def _term_rec(profile: "CustomerProfile", brief_text: str) -> Optional[dict]:
    age = profile.age or 30  # assume 30 if unknown — typical first-time buyer
    income_lpa = _parse_income_lpa(profile.income_range)
    has_dependents = (profile.dependents is not None and profile.dependents > 0) or (
        profile.marital_status == "married"
    )

    # ── Cover recommendation ────────────────────────────────────────────
    if income_lpa:
        multiplier = _COVER_MULTIPLIER_WITH_DEPENDENTS if has_dependents else _COVER_MULTIPLIER_NO_DEPENDENTS
        cover_lakh = round(income_lpa * multiplier / 25) * 25  # round to nearest 25L
        cover_rationale = (
            f"{income_lpa} LPA × {multiplier}x income rule"
            + (" + dependents" if has_dependents else "")
        )
    else:
        cover_lakh = 100  # ₹1 crore default
        cover_rationale = "standard minimum for income protection"

    cover_lakh = max(50, min(cover_lakh, 500))  # floor ₹50L, cap ₹5Cr

    # ── Premium estimate ────────────────────────────────────────────────
    # Try to extract a reference rate from the brief for this product;
    # fall back to industry benchmark.
    base_per_crore = _extract_reference_premium(brief_text) or _TERM_BASE_PREMIUM_PER_CRORE

    age_factor = (1 + _AGE_LOADING_PER_YEAR) ** max(0, age - _TERM_BASE_AGE)
    smoker_factor = (1 + _SMOKER_LOADING) if profile.smoker else 1.0

    annual_per_crore = base_per_crore * age_factor * smoker_factor
    annual_premium = int(annual_per_crore * cover_lakh / 100)
    daily_premium = round(annual_premium / 365)

    profile_parts: list[str] = [f"age {age}"]
    if profile.smoker is not None:
        profile_parts.append("smoker" if profile.smoker else "non-smoker")

    premium_rationale = ", ".join(profile_parts)

    return {
        "cover_lakh": cover_lakh,
        "cover_display": _format_cover(cover_lakh),
        "cover_rationale": cover_rationale,
        "annual_premium": annual_premium,
        "daily_premium": daily_premium,
        "premium_display": f"₹{daily_premium}/day (₹{annual_premium:,}/year)",
        "premium_rationale": premium_rationale,
    }


def _health_rec(profile: "CustomerProfile") -> Optional[dict]:
    if profile.age is None:
        return None

    age = profile.age
    family_size = 1 + (profile.dependents or 0)
    if profile.marital_status == "married" and family_size == 1:
        family_size = 2  # assume spouse

    # Cover: ₹5 lakh per person, capped at ₹20 lakh for family floater
    cover_lakh = min(5 * family_size, 20)
    age_factor = (1 + _AGE_LOADING_PER_YEAR) ** max(0, age - 30)
    family_factor = 1.0 + (family_size - 1) * 0.4  # each additional member adds ~40%
    annual_premium = int(_HEALTH_BASE_PREMIUM * age_factor * family_factor)
    daily_premium = round(annual_premium / 365)

    return {
        "cover_lakh": cover_lakh,
        "cover_display": _format_cover(cover_lakh),
        "cover_rationale": f"₹5 lakh per person for {family_size} member(s)",
        "annual_premium": annual_premium,
        "daily_premium": daily_premium,
        "premium_display": f"₹{daily_premium}/day (₹{annual_premium:,}/year)",
        "premium_rationale": f"age {age}, {family_size}-member family",
    }


# ── Helpers ───────────────────────────────────────────────────────────────

def _parse_income_lpa(income_range: Optional[str]) -> Optional[float]:
    """Parse CustomerProfile.income_range string into a float LPA value."""
    if not income_range:
        return None
    s = income_range.lower().replace(",", "")

    # "15 LPA", "15.5 LPA"
    m = re.search(r"([\d.]+)\s*lpa", s)
    if m:
        return float(m.group(1))

    # "15 lakh", "20 lakh per annum"
    m = re.search(r"([\d.]+)\s*lakh", s)
    if m:
        return float(m.group(1))

    # "₹50000/month" or "50000/month"
    m = re.search(r"([\d.]+)/month", s)
    if m:
        monthly = float(m.group(1))
        return round(monthly * 12 / 100000, 1)

    # Plain number — treat as annual if >= 100000, monthly if < 100000
    m = re.search(r"₹?([\d.]+)$", s.strip())
    if m:
        val = float(m.group(1))
        if val >= 100000:
            return round(val / 100000, 1)
        if val >= 1000:
            return round(val * 12 / 100000, 1)  # likely monthly

    return None


def _extract_reference_premium(brief_text: str) -> Optional[int]:
    """
    Extract a base annual premium per ₹1 crore from the brief's PREMIUMS section.
    Returns None if no reliable number found.
    """
    if not brief_text:
        return None

    # Find PREMIUMS section
    m = re.search(r"PREMIUMS?:(.*?)(?:\n[A-Z]|\Z)", brief_text, re.DOTALL | re.IGNORECASE)
    section = m.group(1) if m else brief_text

    # "₹22/day" → annual = 22 * 365 = 8030, then scale to per-crore (assume 1Cr reference)
    m_day = re.search(r"₹\s*(\d+)/day", section)
    if m_day:
        daily = int(m_day.group(1))
        if 5 <= daily <= 500:   # sanity check
            return daily * 365

    # "₹8,060/year" or "₹8060/year"
    m_yr = re.search(r"₹\s*([\d,]+)/year", section)
    if m_yr:
        annual = int(m_yr.group(1).replace(",", ""))
        if 1000 <= annual <= 200000:
            return annual

    # "₹X,XXX/year" with comma thousands
    m_yr2 = re.search(r"₹\s*([\d,]+)\s*per\s*year", section, re.IGNORECASE)
    if m_yr2:
        annual = int(m_yr2.group(1).replace(",", ""))
        if 1000 <= annual <= 200000:
            return annual

    return None


def _format_cover(cover_lakh: float) -> str:
    """Format a cover amount in lakh to a readable rupee string."""
    if cover_lakh >= 100:
        crore = cover_lakh / 100
        # Show one decimal if not a whole number
        if crore == int(crore):
            return f"₹{int(crore)} crore"
        return f"₹{crore:.1f} crore"
    return f"₹{int(cover_lakh)} lakh"
