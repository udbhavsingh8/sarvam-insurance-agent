"""
Deterministic profile extractor — pulls customer facts from plain user text.

Runs on every user message BEFORE the LLM call. Does not replace the LLM
for stage transitions or interest scoring — only handles fields that appear
literally in what the user says (age, income, smoker status, dependents).

Calling code in agent.py:
    from profile_extractor import extract_profile_fields
    updates = extract_profile_fields(user_text)
    memory.customer_profile.apply_updates(updates)
"""

from __future__ import annotations

import re
from typing import Optional


def extract_profile_fields(text: str) -> dict:
    """
    Parse user text and return a dict of any profile fields found.
    Only returns keys that were actually matched — callers must check presence.

    Supported fields: age, smoker, income_range, dependents, marital_status, gender
    """
    t = text.lower()
    result: dict = {}

    # ── Age ──────────────────────────────────────────────────────────────
    # Matches: "I'm 29", "I am 32 years old", "age is 45", "29-year-old", "29 year old"
    age = _extract_age(t)
    if age is not None:
        result["age"] = age

    # ── Smoker status ─────────────────────────────────────────────────────
    smoker = _extract_smoker(t)
    if smoker is not None:
        result["smoker"] = smoker

    # ── Income ────────────────────────────────────────────────────────────
    income = _extract_income(t)
    if income is not None:
        result["income_range"] = income

    # ── Dependents ────────────────────────────────────────────────────────
    dependents = _extract_dependents(t)
    if dependents is not None:
        result["dependents"] = dependents

    # ── Marital status ────────────────────────────────────────────────────
    marital = _extract_marital(t)
    if marital is not None:
        result["marital_status"] = marital

    # ── Gender ────────────────────────────────────────────────────────────
    gender = _extract_gender(t)
    if gender is not None:
        result["gender"] = gender

    # ── Policy term ───────────────────────────────────────────────────────
    policy_term = _extract_policy_term(t)
    if policy_term is not None:
        result["policy_term"] = policy_term

    # ── Payment frequency ─────────────────────────────────────────────────
    frequency = _extract_payment_frequency(t)
    if frequency is not None:
        result["payment_frequency"] = frequency

    # ── Liabilities ───────────────────────────────────────────────────────
    liabilities = _extract_liabilities(t)
    if liabilities is not None:
        result["liabilities_lakh"] = liabilities

    # ── Cover override ────────────────────────────────────────────────────
    cover = _extract_cover_override(t)
    if cover is not None:
        result["cover_amount_override_lakh"] = cover

    return result


# ── Extractors ────────────────────────────────────────────────────────────

def _extract_age(t: str) -> Optional[int]:
    patterns = [
        r"\bi(?:'?m| am)\s+(\d{1,2})\b",          # "I'm 29", "I am 32"
        r"\bage(?:\s+is)?\s*[:\-]?\s*(\d{1,2})\b", # "age is 29", "age: 29"
        r"\b(\d{1,2})[\s-]year(?:s)?[\s-]old\b",   # "29-year-old", "32 years old"
        r"\bturned\s+(\d{1,2})\b",                  # "just turned 35"
        r"\b(\d{1,2})\s+years?\s+of\s+age\b",       # "29 years of age"
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            val = int(m.group(1))
            if 18 <= val <= 75:
                return val
    return None


def _extract_smoker(t: str) -> Optional[bool]:
    # Explicit non-smoker first (longer phrases win over "smoke")
    non_smoker_phrases = [
        "non-smoker", "non smoker", "nonsmoker",
        "don't smoke", "do not smoke", "never smoked",
        "not a smoker", "i don't smoke", "i do not smoke",
        "no tobacco", "no smoking",
    ]
    for phrase in non_smoker_phrases:
        if phrase in t:
            return False

    smoker_phrases = [
        "i smoke", "i'm a smoker", "i am a smoker",
        "yes, smoker", "yes smoker", "smoker",
        "use tobacco", "chew tobacco", "tobacco user",
    ]
    for phrase in smoker_phrases:
        if phrase in t:
            return True

    return None


def _extract_income(t: str) -> Optional[str]:
    """
    Returns a human-readable income range string, e.g. "15 LPA", "50,000/month".
    Keeps the original phrasing from the user — stored for display + LLM context.

    Handles both English ("lakh") and Devanagari ("लाख") spellings, and
    Hindi annual markers like "सालाना", "वार्षिक", "प्रति वर्ष".
    """
    # Normalise: treat Devanagari "लाख" as "lakh" and Hindi annual words as "per annum"
    t_norm = t
    t_norm = re.sub(r"लाख(?:ों)?", "lakh", t_norm)          # लाख / लाखों → lakh
    t_norm = re.sub(r"(?:सालाना|वार्षिक|प्रति\s+वर्ष)", "per annum", t_norm)
    t_norm = re.sub(r"(?:प्रति\s+माह|महीने\s+में)", "per month", t_norm)
    t_norm = re.sub(r"करोड़|करोड", "crore", t_norm)

    # Annual: "15 LPA", "15 lakhs per annum", "15 lakh per year"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:lpa|lakh(?:s)?\s+(?:per\s+annum|per\s+year|annual))", t_norm)
    if m:
        return f"{m.group(1)} LPA"

    # "15 lakhs" / "15 lakh" (standalone, likely annual) — skip if preceded by loan/liability words
    m = re.search(r"(\d+(?:\.\d+)?)\s*lakh(?:s)?", t_norm)
    if m:
        start = max(0, m.start() - 30)
        context = t_norm[start:m.start()]
        if not re.search(r"loan|emi|debt|mortgage|liability|outstanding", context):
            return f"{m.group(1)} lakh"

    # Monthly: "50,000 per month", "50k per month", "50000 monthly"
    m = re.search(r"([\d,]+)(?:k)?\s*(?:per\s+month|monthly|\/month|pm\b)", t_norm)
    if m:
        raw = m.group(1).replace(",", "")
        return f"₹{raw}/month"

    # "my salary is X" / "earn X" — catch remaining patterns
    m = re.search(r"(?:earn|salary|income|make)\s+(?:around\s+|about\s+|rs\.?\s*|₹\s*)?([\d,]+)", t_norm)
    if m:
        raw = m.group(1).replace(",", "")
        if len(raw) >= 5:  # likely monthly (50000) not age
            return f"₹{raw}"

    return None


def _extract_dependents(t: str) -> Optional[int]:
    # "2 kids", "two kids", "3 children", "one child", "no kids", "no children"
    word_nums = {"no": 0, "zero": 0, "one": 1, "two": 2, "three": 3,
                 "four": 4, "five": 5, "six": 6}

    # Family-member phrases that imply exactly 1 dependent
    # e.g. "my father is dependent on me", "my mother depends on me"
    one_dependent_phrases = [
        "my father", "my mother", "my parent", "my spouse", "my wife", "my husband",
        "my sister", "my brother", "my grandmother", "my grandfather",
        "मेरे पिता", "मेरी माँ", "मेरी माता", "मेरे माता-पिता",
    ]
    # Only count as 1 dependent if also "dependent on me / depends on me / rely on me"
    dependency_markers = ["dependent on me", "depends on me", "rely on me", "relies on me",
                          "निर्भर है", "dependent hai", "support karta"]
    text_lower_full = t  # already lowercased
    has_dependency_marker = any(m in text_lower_full for m in dependency_markers)
    if has_dependency_marker:
        for phrase in one_dependent_phrases:
            if phrase.lower() in text_lower_full:
                return 1

    # Explicit zero-dependent phrases (check BEFORE generic patterns)
    zero_phrases = [
        "nobody is dependent", "no one is dependent", "none are dependent",
        "no dependents", "no dependent", "nobody depends on me",
        "no one depends on me", "i have no dependent", "i don't have any dependent",
        "i do not have any dependent", "no family dependent", "koi dependent nahi",
        "कोई dependent", "कोई निर्भर नहीं",
    ]
    for phrase in zero_phrases:
        if phrase in t:
            return 0

    # Digit form: "2 kids", "3 children", "4 dependents"
    m = re.search(r"(\d)\s+(?:kid|child|children|dependent)", t)
    if m:
        return int(m.group(1))

    # Word form: "two kids", "no children"
    m = re.search(r"(no|zero|one|two|three|four|five|six)\s+(?:kid|child|children|dependent)", t)
    if m:
        return word_nums.get(m.group(1), None)

    # "married with two kids" — dependent count implied
    m = re.search(r"married\s+(?:and\s+have|with)\s+(\d|no|zero|one|two|three|four|five|six)\s+(?:kid|child|children)", t)
    if m:
        raw = m.group(1)
        return int(raw) if raw.isdigit() else word_nums.get(raw)

    return None


def _extract_marital(t: str) -> Optional[str]:
    if any(p in t for p in ["married", "have a wife", "have a husband", "my wife", "my husband", "my spouse"]):
        return "married"
    if any(p in t for p in ["single", "not married", "unmarried", "bachelor", "bachelorette"]):
        return "single"
    if "divorced" in t:
        return "divorced"
    if "widowed" in t or "widow" in t:
        return "widowed"
    return None


def _extract_gender(t: str) -> Optional[str]:
    if any(p in t for p in ["i'm a woman", "i am a woman", "i'm female", "i am female"]):
        return "female"
    if any(p in t for p in ["i'm a man", "i am a man", "i'm male", "i am male"]):
        return "male"
    return None


def _extract_policy_term(t: str) -> Optional[int]:
    """Extract policy term in years from utterances like '20 year term', 'for 30 years', '15 साल'."""
    patterns = [
        r"(\d{1,2})[- ]year(?:s)?[- ](?:term|policy|plan|cover)",
        r"(?:term|policy|cover)\s+(?:of\s+)?(\d{1,2})\s+years?",
        r"for\s+(\d{1,2})\s+years?\s+(?:term|policy|plan|cover)",
        r"(\d{1,2})\s+yr\s+(?:term|plan|policy)",
        # Hindi: "15 साल", "20 वर्ष", "15 साल का", "15 साल के लिए"
        r"(\d{1,2})\s*(?:साल|वर्ष)(?:\s+(?:का|के\s+लिए|तक|last|चाहिए))?",
        # "coverage 15 साल last करेगा" style
        r"(\d{1,2})\s*(?:साल|वर्ष)\s+(?:last|चलेगा|रहेगा|होगा)",
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            val = int(m.group(1))
            if 5 <= val <= 50:
                return val
    return None


def _extract_payment_frequency(t: str) -> Optional[str]:
    """Detect payment frequency preference."""
    if any(p in t for p in ["monthly", "every month", "per month", "month by month"]):
        return "monthly"
    if any(p in t for p in ["quarterly", "every quarter", "every three months"]):
        return "quarterly"
    if any(p in t for p in ["semi-annual", "semi annual", "half yearly", "half-yearly", "every six months", "twice a year"]):
        return "semi_annual"
    if any(p in t for p in ["annual", "yearly", "once a year", "every year", "per year"]):
        return "annual"
    return None


def _extract_liabilities(t: str) -> Optional[float]:
    """Extract outstanding loans or liabilities in lakh."""
    patterns = [
        r"(?:home\s+loan|loan|emi|liability|liabilities|mortgage|debt)\s+of\s+(?:₹\s*)?([\d.]+)\s*(lakh|crore|cr|l\b)",
        r"(?:₹\s*)?([\d.]+)\s*(lakh|crore|cr)\s+(?:loan|emi|debt|mortgage)",
        r"outstanding\s+(?:₹\s*)?([\d.]+)\s*(lakh|crore|cr)",
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            val = float(m.group(1))
            unit = m.group(2).lower()
            if "crore" in unit or unit == "cr":
                return val * 100
            return val
    return None


def _extract_cover_override(t: str) -> Optional[float]:
    """Extract explicit cover amount stated by customer ('I want 2 crore cover')."""
    patterns = [
        r"(?:want|need|looking\s+for|give\s+me)\s+(?:₹\s*)?([\d.]+)\s*(crore|cr|lakh|l\b)\s+(?:cover|sum\s+assured|life\s+cover|insurance)",
        r"(?:cover|sum\s+assured)\s+of\s+(?:₹\s*)?([\d.]+)\s*(crore|cr|lakh|l\b)",
        r"(?:₹\s*)?([\d.]+)\s*(crore|cr|lakh)\s+(?:cover|sum\s+assured|life\s+cover)",
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            val = float(m.group(1))
            unit = m.group(2).lower()
            if "crore" in unit or unit == "cr":
                return val * 100
            return val
    return None
