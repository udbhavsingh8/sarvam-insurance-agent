"""
Product Structure Builder.

Orchestrates deterministic table extraction → GPT fallback → validation → JSON.

Outputs {name}.structure.json with quote capability level and all extracted data.

AUTO_APPROVE_DOCUMENTS=true (default) → status="approved" immediately.
AUTO_APPROVE_DOCUMENTS=false         → status="pending_review" (future workflow).
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from table_parser import parse_tables


# ── Configuration ─────────────────────────────────────────────────────────────

def _auto_approve() -> bool:
    return os.getenv("AUTO_APPROVE_DOCUMENTS", "true").lower() == "true"


# ── Actuarial validation ──────────────────────────────────────────────────────

_TERM_PREMIUM_MIN = 2000    # ₹/crore/year floor
_TERM_PREMIUM_MAX = 500000  # ₹/crore/year ceiling (very old, smoker edge case)


def _validate_premium_rows(rows: list[dict]) -> list[str]:
    """Return list of warning strings. Empty = all good."""
    warnings = []
    ages = [r["age"] for r in rows]
    premiums = [r["annual_premium"] for r in rows]

    # Range checks
    for r in rows:
        if not (15 <= r["age"] <= 75):
            warnings.append(f"Implausible age: {r['age']}")
        if not (_TERM_PREMIUM_MIN <= r["annual_premium"] <= _TERM_PREMIUM_MAX):
            warnings.append(
                f"Implausible premium {r['annual_premium']} for age {r['age']} term {r['term']}"
            )

    # Monotonicity: for same term, older age should cost more
    same_term: dict[int, list] = {}
    for r in rows:
        same_term.setdefault(r["term"], []).append(r)
    for term, term_rows in same_term.items():
        sorted_rows = sorted(term_rows, key=lambda x: x["age"])
        for i in range(1, len(sorted_rows)):
            if sorted_rows[i]["annual_premium"] < sorted_rows[i - 1]["annual_premium"]:
                warnings.append(
                    f"Non-monotonic premium at term {term}: "
                    f"age {sorted_rows[i]['age']} cheaper than {sorted_rows[i-1]['age']}"
                )

    return warnings


# ── Eligibility extraction ────────────────────────────────────────────────────

def _extract_eligibility(text: str) -> dict:
    """Extract eligibility criteria from document text using regex."""
    result = {
        "min_entry_age": None,
        "max_entry_age": None,
        "min_policy_term": None,
        "max_policy_term": None,
        "min_sum_assured_lakh": None,
        "max_sum_assured_lakh": None,
        "confidence": "extracted",
    }

    # Min/Max entry age
    m = re.search(r"min(?:imum)?\s+(?:entry\s+)?age\s*[:\-]?\s*(\d{1,2})", text, re.IGNORECASE)
    if m:
        result["min_entry_age"] = int(m.group(1))

    m = re.search(r"max(?:imum)?\s+(?:entry\s+)?age\s*[:\-]?\s*(\d{2,3})", text, re.IGNORECASE)
    if m:
        result["max_entry_age"] = int(m.group(1))

    # Policy term range
    m = re.search(r"min(?:imum)?\s+(?:policy\s+)?term\s*[:\-]?\s*(\d{1,2})\s*(?:year|yr)", text, re.IGNORECASE)
    if m:
        result["min_policy_term"] = int(m.group(1))

    m = re.search(r"max(?:imum)?\s+(?:policy\s+)?term\s*[:\-]?\s*(\d{1,2})\s*(?:year|yr)", text, re.IGNORECASE)
    if m:
        result["max_policy_term"] = int(m.group(1))

    # Sum assured bounds — look for lakh/crore values
    m = re.search(
        r"min(?:imum)?\s+sum\s+assured\s*[:\-]?\s*₹?\s*([\d,]+)\s*(lakh|crore|cr)",
        text, re.IGNORECASE
    )
    if m:
        val = int(m.group(1).replace(",", ""))
        unit = m.group(2).lower()
        result["min_sum_assured_lakh"] = val if "lakh" in unit else val * 100

    m = re.search(
        r"max(?:imum)?\s+sum\s+assured\s*[:\-]?\s*(?:no\s+limit|unlimited|as\s+per)",
        text, re.IGNORECASE
    )
    if m:
        result["max_sum_assured_lakh"] = None  # no limit

    return result


# ── Payment frequency extraction ──────────────────────────────────────────────

_DEFAULT_FREQUENCY_RULES = {
    "annual":      1.0000,
    "semi_annual": 0.5100,
    "quarterly":   0.2600,
    "monthly":     0.0883,
    "source": "industry_standard",
}


def _extract_frequency_rules(text: str) -> dict:
    """Look for explicit frequency loading factors in document text."""
    rules = dict(_DEFAULT_FREQUENCY_RULES)
    source_confirmed = False

    # Look for explicit mentions: "monthly mode: 8.83%" or "monthly factor: 0.0883"
    m = re.search(r"monthly\s+(?:mode|factor|loading)[:\s]+(\d+\.?\d*)\s*%", text, re.IGNORECASE)
    if m:
        rules["monthly"] = float(m.group(1)) / 100
        source_confirmed = True

    m = re.search(r"quarterly\s+(?:mode|factor|loading)[:\s]+(\d+\.?\d*)\s*%", text, re.IGNORECASE)
    if m:
        rules["quarterly"] = float(m.group(1)) / 100
        source_confirmed = True

    m = re.search(r"semi[\s\-]?annual\s+(?:mode|factor|loading)[:\s]+(\d+\.?\d*)\s*%", text, re.IGNORECASE)
    if m:
        rules["semi_annual"] = float(m.group(1)) / 100
        source_confirmed = True

    if source_confirmed:
        rules["source"] = "document_stated"

    return rules


# ── GPT fallback — extracts illustrative premium from text ───────────────────

def _gpt_extract_illustrative_premium(text: str, plan_name: str) -> list[dict]:
    """
    When no table is found, ask GPT-4o-mini to extract any example premiums from text.
    Returns list of {age, term, annual_premium} rows (confidence: inferred).
    Returns empty list on failure.
    """
    try:
        import os
        from openai import OpenAI

        key = os.getenv("OPENAI_API_KEY")
        if not key:
            return []

        # Find the most relevant section of text (premium-related)
        sections = []
        for line in text.splitlines():
            if re.search(r"premium|₹\s*\d|rs\.?\s*\d|annual\s+\d|\d+\s*/\s*year", line, re.IGNORECASE):
                sections.append(line.strip())
        snippet = "\n".join(sections[:40]) or text[:2000]

        prompt = f"""Extract premium information from this insurance document text.
Return ONLY a JSON array of objects, nothing else.
Each object must have: age (integer), term (integer, years), annual_premium (integer, rupees per year).
Only include values you can read directly from the text — do not estimate or calculate.
If the premium is per crore sum assured, use that basis.
If no clear premium data exists, return an empty array [].

Document text:
{snippet}

Return only the JSON array:"""

        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=400,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # Strip markdown code fences if present
        raw = re.sub(r"```(?:json)?", "", raw).strip("` \n")
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        # Validate each entry
        valid = []
        for entry in data:
            if (
                isinstance(entry, dict)
                and isinstance(entry.get("age"), int)
                and isinstance(entry.get("term"), int)
                and isinstance(entry.get("annual_premium"), int)
                and 15 <= entry["age"] <= 75
                and 5 <= entry["term"] <= 55
                and 1000 <= entry["annual_premium"] <= 1_000_000
            ):
                valid.append(entry)
        return valid
    except Exception:
        return []


# ── Quote capability level ────────────────────────────────────────────────────

def _assign_capability_level(premium_tables: list[dict]) -> int:
    """
    0 = no data
    1 = illustrative (1-2 rows, inferred)
    2 = table-based (3+ rows, exact or scaled)
    3 = full (multiple terms, multiple ages, exact)
    """
    if not premium_tables:
        return 0

    total_exact_rows = sum(
        t["row_count"] for t in premium_tables if t.get("confidence") == "exact"
    )
    total_inferred_rows = sum(
        t["row_count"] for t in premium_tables if t.get("confidence") == "inferred"
    )

    if total_exact_rows >= 6:
        # Check if multiple terms are covered
        all_terms = set()
        for t in premium_tables:
            if t.get("confidence") == "exact":
                for r in t.get("rows", []):
                    all_terms.add(r["term"])
        return 3 if len(all_terms) >= 3 else 2

    if total_exact_rows >= 3:
        return 2

    if total_inferred_rows >= 1 or total_exact_rows >= 1:
        return 1

    return 0


# ── Main builder ─────────────────────────────────────────────────────────────

def build_product_structure(
    text: str,
    pages_data: list[dict],
    meta: dict,
    doc_hash: str = "",
) -> dict:
    """
    Build the complete Product Structure JSON for a document.

    text:       Full document text
    pages_data: List of {"page_num", "tables", "text"} from pdfplumber
    meta:       Extracted metadata (plan_name, plan_type, etc.)
    doc_hash:   SHA-256 of original PDF

    Returns structure dict ready to save as {name}.structure.json.
    """
    plan_type = meta.get("plan_type", "other")
    extraction_notes: list[str] = []

    # ── Step 1: Deterministic table extraction ────────────────────────────
    premium_tables = parse_tables(pages_data)

    if premium_tables:
        extraction_notes.append(
            f"Deterministic parser extracted {len(premium_tables)} premium table(s)."
        )
    else:
        extraction_notes.append("No structured premium tables found by deterministic parser.")

        # ── Step 2: GPT fallback for illustrative premiums ────────────────
        gpt_rows = _gpt_extract_illustrative_premium(text, meta.get("plan_name", ""))
        if gpt_rows:
            premium_tables.append({
                "variant": "default",
                "basis": "per_crore_annual",
                "smoker": False,
                "rows": gpt_rows,
                "source_page": None,
                "confidence": "inferred",
                "row_count": len(gpt_rows),
            })
            extraction_notes.append(
                f"GPT fallback found {len(gpt_rows)} illustrative premium data point(s)."
            )
        else:
            extraction_notes.append("No premium data found in document.")

    # ── Step 3: Actuarial validation ─────────────────────────────────────
    validation_warnings: list[str] = []
    for table in premium_tables:
        if table.get("confidence") == "exact":
            warnings = _validate_premium_rows(table.get("rows", []))
            validation_warnings.extend(warnings)
            if warnings:
                # Downgrade confidence on validation failure
                table["confidence"] = "inferred"
                table["validation_warnings"] = warnings

    # ── Step 4: Supporting data ───────────────────────────────────────────
    eligibility = _extract_eligibility(text)
    frequency_rules = _extract_frequency_rules(text)

    # ── Step 5: Capability level ──────────────────────────────────────────
    capability_level = _assign_capability_level(premium_tables)

    # ── Step 6: Missing fields inventory ─────────────────────────────────
    missing: list[str] = []
    if not premium_tables:
        missing.append("all_premium_data")
    else:
        has_smoker = any(t["smoker"] for t in premium_tables)
        has_nonsmoker = any(not t["smoker"] for t in premium_tables)
        if plan_type == "term" and not has_smoker:
            missing.append("smoker_rates")
        if plan_type == "term" and not has_nonsmoker:
            missing.append("non_smoker_rates")

    if eligibility["min_entry_age"] is None:
        missing.append("min_entry_age")
    if eligibility["max_entry_age"] is None:
        missing.append("max_entry_age")

    # ── Step 7: Status ────────────────────────────────────────────────────
    status = "approved" if _auto_approve() else "pending_review"

    structure = {
        "schema_version": "1.0",
        "plan_name": meta.get("plan_name", ""),
        "plan_type": plan_type,
        "quote_capability_level": capability_level,
        "status": status,
        "auto_approved": _auto_approve(),
        "document_hash": doc_hash,
        "eligibility": eligibility,
        "premium_tables": premium_tables,
        "payment_frequency_rules": frequency_rules,
        "gst_rate": 0.18,
        "variants": list({t["variant"] for t in premium_tables}) or ["default"],
        "missing_fields": missing,
        "validation_warnings": validation_warnings,
        "extraction_notes": " | ".join(extraction_notes),
    }

    return structure
