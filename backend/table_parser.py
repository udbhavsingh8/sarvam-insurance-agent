"""
Deterministic premium table parser.

Reads raw table objects from pdfplumber and classifies them as premium tables.
GPT is never called here — this is pure deterministic logic.

Handles the most common Indian term insurance table formats:
  Format A — age as rows, policy terms as columns (most common)
  Format B — policy terms as rows, ages as columns (less common)
  Format C — age as rows, smoker/non-smoker as column pairs

Returns a list of structured premium_table dicts ready for structure.json.
"""

from __future__ import annotations

import re
from typing import Optional


# ── Scoring patterns ──────────────────────────────────────────────────────────

_AGE_HEADER_PATTERNS = re.compile(
    r"\bage\b|entry\s+age|age\s+at\s+entry|age\s*\(years?\)",
    re.IGNORECASE,
)

_TERM_HEADER_PATTERNS = re.compile(
    r"\b(\d{1,2})\s*(?:yr|year|years?)\b|"
    r"policy\s+term|term\s*\(years?\)",
    re.IGNORECASE,
)

_PREMIUM_HEADER_PATTERNS = re.compile(
    r"premium|annual|₹|rs\.?|amount|rate",
    re.IGNORECASE,
)

_SMOKER_PATTERNS = re.compile(
    r"smoker|tobacco|non[\s\-]?smoker|non[\s\-]?tobacco",
    re.IGNORECASE,
)

_GENDER_PATTERNS = re.compile(r"\bmale\b|\bfemale\b|\bm\b|\bf\b", re.IGNORECASE)

_PER_CRORE_PATTERNS = re.compile(
    r"per\s+(?:₹\s*)?(?:1\s+)?crore|per\s+crore|₹\s*1\s*cr",
    re.IGNORECASE,
)

_PER_LAKH_PATTERNS = re.compile(
    r"per\s+(?:₹\s*)?(?:1\s+)?lakh|per\s+lakh|₹\s*1\s*l\b",
    re.IGNORECASE,
)


def _clean_cell(cell) -> str:
    """Normalise a pdfplumber cell value to a string."""
    if cell is None:
        return ""
    return str(cell).strip().replace("\n", " ")


def _to_int(s: str) -> Optional[int]:
    """Parse a cell value to int, handling commas and ₹ prefix."""
    s = re.sub(r"[₹,\s]", "", s)
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _extract_term_from_header(header: str) -> Optional[int]:
    """Extract numeric policy term (years) from a column header string."""
    m = re.search(r"(\d{1,2})\s*(?:yr|year|years?)", header, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 5 <= val <= 50:
            return val
    return None


def _is_age(val: int) -> bool:
    return 15 <= val <= 75


def _is_term(val: int) -> bool:
    return 5 <= val <= 55


def _is_premium(val: int) -> bool:
    # Indian term insurance: ₹3,000–₹5,00,000 per crore per year
    return 1000 <= val <= 1_000_000


def _find_header_row(table: list[list]) -> int:
    """
    Find the index of the last header row.
    Header rows contain text; data rows contain mostly numbers.
    Returns -1 if not found.
    """
    for i, row in enumerate(table):
        cells = [_clean_cell(c) for c in row if _clean_cell(c)]
        if not cells:
            continue
        # A header row has mostly non-numeric content
        numeric_count = sum(1 for c in cells if _to_int(c) is not None)
        text_count = len(cells) - numeric_count
        if text_count >= len(cells) * 0.5:
            last_header = i
    try:
        return last_header
    except UnboundLocalError:
        return -1


def _score_as_premium_table(table: list[list], page_text: str) -> float:
    """
    Score 0–1 how likely this table is a premium table.
    A score >= 0.4 is treated as a premium table.
    """
    if len(table) < 3:
        return 0.0

    # Flatten all cells to strings
    all_cells = [_clean_cell(c) for row in table for c in row if _clean_cell(c)]
    if not all_cells:
        return 0.0

    score = 0.0

    # Check for age-related header
    age_found = any(_AGE_HEADER_PATTERNS.search(c) for c in all_cells)
    if age_found:
        score += 0.4

    # Check for term-related headers
    term_headers = sum(1 for c in all_cells if _extract_term_from_header(c) is not None)
    if term_headers >= 2:
        score += 0.3

    # Check for premium-related keywords
    premium_kw = any(_PREMIUM_HEADER_PATTERNS.search(c) for c in all_cells)
    if premium_kw:
        score += 0.15

    # Check for numeric values in plausible premium range
    numeric_vals = [_to_int(c) for c in all_cells if _to_int(c) is not None]
    if any(_is_premium(v) for v in numeric_vals):
        score += 0.15

    # Nearby page text boosts confidence
    if re.search(r"premium|annual\s+premium|sum\s+assured", page_text, re.IGNORECASE):
        score = min(1.0, score + 0.1)

    return score


def _detect_basis(table: list[list], page_text: str) -> str:
    """Detect whether the table is per_crore, per_lakh, or absolute."""
    # Check all cells + surrounding page text
    combined = page_text
    for row in table:
        for cell in row:
            combined += " " + _clean_cell(cell)

    if _PER_CRORE_PATTERNS.search(combined):
        return "per_crore_annual"
    if _PER_LAKH_PATTERNS.search(combined):
        return "per_lakh_annual"
    # Default for term insurance
    return "per_crore_annual"


def _detect_smoker(header: str) -> Optional[bool]:
    """Return True=smoker, False=non-smoker, None=not specified."""
    h = header.lower()
    if re.search(r"non[\s\-]?smoker|non[\s\-]?tobacco", h):
        return False
    if re.search(r"\bsmoker\b|\btobacco\b", h):
        return True
    return None


def _parse_format_a(table: list[list], header_row: int, page_text: str) -> list[dict]:
    """
    Format A: age as rows, policy terms as columns.
    Returns list of {age, term, annual_premium} dicts.
    """
    headers = [_clean_cell(c) for c in table[header_row]]
    if not headers:
        return []

    # Find age column index
    age_col = None
    for i, h in enumerate(headers):
        if _AGE_HEADER_PATTERNS.search(h) or h.lower() in ("age", ""):
            # Verify by checking data rows
            data_vals = [
                _to_int(_clean_cell(table[r][i]))
                for r in range(header_row + 1, len(table))
                if i < len(table[r])
            ]
            if any(_is_age(v) for v in data_vals if v is not None):
                age_col = i
                break

    if age_col is None:
        # Try first column as age
        data_vals = [
            _to_int(_clean_cell(table[r][0]))
            for r in range(header_row + 1, len(table))
            if table[r]
        ]
        if any(_is_age(v) for v in data_vals if v is not None):
            age_col = 0

    if age_col is None:
        return []

    # Find term columns
    term_cols: list[tuple[int, int]] = []  # (col_index, term_years)
    for i, h in enumerate(headers):
        if i == age_col:
            continue
        term = _extract_term_from_header(h)
        if term is not None:
            term_cols.append((i, term))

    if not term_cols:
        return []

    # Extract data rows
    rows = []
    for r in range(header_row + 1, len(table)):
        row = table[r]
        if age_col >= len(row):
            continue
        age = _to_int(_clean_cell(row[age_col]))
        if age is None or not _is_age(age):
            continue
        for col_idx, term in term_cols:
            if col_idx >= len(row):
                continue
            premium = _to_int(_clean_cell(row[col_idx]))
            if premium is not None and _is_premium(premium):
                rows.append({"age": age, "term": term, "annual_premium": premium})

    return rows


def _parse_format_b(table: list[list], header_row: int, page_text: str) -> list[dict]:
    """
    Format B: policy term as rows, age as columns.
    Returns list of {age, term, annual_premium} dicts.
    """
    headers = [_clean_cell(c) for c in table[header_row]]
    if not headers:
        return []

    # Find term column (first column likely)
    term_col = None
    for i, h in enumerate(headers):
        if _TERM_HEADER_PATTERNS.search(h) or h.lower() in ("term", "policy term", ""):
            data_vals = [
                _to_int(_clean_cell(table[r][i]))
                for r in range(header_row + 1, len(table))
                if i < len(table[r])
            ]
            if any(_is_term(v) for v in data_vals if v is not None):
                term_col = i
                break

    if term_col is None:
        # Try first column as term
        data_vals = [
            _to_int(_clean_cell(table[r][0]))
            for r in range(header_row + 1, len(table))
            if table[r]
        ]
        if any(_is_term(v) for v in data_vals if v is not None):
            term_col = 0

    if term_col is None:
        return []

    # Find age columns
    age_cols: list[tuple[int, int]] = []
    for i, h in enumerate(headers):
        if i == term_col:
            continue
        age = _to_int(h)
        if age is not None and _is_age(age):
            age_cols.append((i, age))

    if not age_cols:
        return []

    # Extract data rows
    rows = []
    for r in range(header_row + 1, len(table)):
        row = table[r]
        if term_col >= len(row):
            continue
        term = _to_int(_clean_cell(row[term_col]))
        if term is None or not _is_term(term):
            continue
        for col_idx, age in age_cols:
            if col_idx >= len(row):
                continue
            premium = _to_int(_clean_cell(row[col_idx]))
            if premium is not None and _is_premium(premium):
                rows.append({"age": age, "term": term, "annual_premium": premium})

    return rows


def _detect_smoker_split(headers: list[str]) -> dict[int, bool]:
    """
    Detect if columns are split by smoker/non-smoker.
    Returns {col_index: is_smoker} for all smoker-labelled columns.
    """
    result = {}
    for i, h in enumerate(headers):
        s = _detect_smoker(h)
        if s is not None:
            result[i] = s
    return result


def parse_tables(
    pages_data: list[dict],
) -> list[dict]:
    """
    Main entry point.

    pages_data: list of {"page_num": int, "tables": [raw_table, ...], "text": str}
    raw_table:  list[list[str|None]] from pdfplumber page.extract_tables()

    Returns list of premium_table dicts suitable for structure.json.
    """
    results: list[dict] = []

    for page in pages_data:
        page_num = page["page_num"]
        page_text = page.get("text", "")

        for raw_table in page.get("tables", []):
            if not raw_table or len(raw_table) < 3:
                continue

            score = _score_as_premium_table(raw_table, page_text)
            if score < 0.35:
                continue

            header_row = _find_header_row(raw_table)
            if header_row < 0:
                header_row = 0

            basis = _detect_basis(raw_table, page_text)
            headers = [_clean_cell(c) for c in raw_table[header_row]]

            # Detect smoker split within columns
            smoker_map = _detect_smoker_split(headers)

            # Try Format A first (most common), then Format B
            rows = _parse_format_a(raw_table, header_row, page_text)
            if not rows:
                rows = _parse_format_b(raw_table, header_row, page_text)

            if not rows:
                continue

            if smoker_map:
                # Table has smoker/non-smoker columns — split into two tables
                # This is handled in structure_builder via separate tables
                # For now, tag all rows as the most common type (non-smoker)
                smoker_val = False  # default to non-smoker
                for col_idx, is_smoker in smoker_map.items():
                    if not is_smoker:
                        smoker_val = False
                        break
                    smoker_val = is_smoker
            else:
                # Check page/table context for smoker declaration
                combined = page_text
                for row in raw_table:
                    for cell in row:
                        combined += " " + _clean_cell(cell)
                s = _detect_smoker(combined[:500])
                smoker_val = s if s is not None else False  # default to non-smoker

            table_entry = {
                "variant": "default",
                "basis": basis,
                "smoker": smoker_val,
                "rows": rows,
                "source_page": page_num,
                "confidence": "exact",
                "row_count": len(rows),
            }
            results.append(table_entry)

    return results
