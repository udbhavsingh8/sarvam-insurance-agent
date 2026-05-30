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
    """
    # Annual: "15 LPA", "15 lakhs per annum", "15 lakh per year"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:lpa|lakh(?:s)?\s+(?:per\s+annum|per\s+year|annual))", t)
    if m:
        return f"{m.group(1)} LPA"

    # "15 lakhs" / "15 lakh" (standalone, likely annual)
    m = re.search(r"(\d+(?:\.\d+)?)\s*lakh(?:s)?", t)
    if m:
        return f"{m.group(1)} lakh"

    # Monthly: "50,000 per month", "50k per month", "50000 monthly"
    m = re.search(r"([\d,]+)(?:k)?\s*(?:per\s+month|monthly|\/month|pm\b)", t)
    if m:
        raw = m.group(1).replace(",", "")
        return f"₹{raw}/month"

    # "my salary is X" / "earn X" — catch remaining patterns
    m = re.search(r"(?:earn|salary|income|make)\s+(?:around\s+|about\s+|rs\.?\s*|₹\s*)?([\d,]+)", t)
    if m:
        raw = m.group(1).replace(",", "")
        if len(raw) >= 5:  # likely monthly (50000) not age
            return f"₹{raw}"

    return None


def _extract_dependents(t: str) -> Optional[int]:
    # "2 kids", "two kids", "3 children", "one child", "no kids", "no children"
    word_nums = {"no": 0, "zero": 0, "one": 1, "two": 2, "three": 3,
                 "four": 4, "five": 5, "six": 6}

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
    # Infer from pronouns/context — only set when unambiguous
    if any(p in t for p in ["i'm a woman", "i am a woman", "i'm female", "i am female"]):
        return "female"
    if any(p in t for p in ["i'm a man", "i am a man", "i'm male", "i am male"]):
        return "male"
    # "my wife" / "my husband" doesn't tell us about the customer — skip
    return None
