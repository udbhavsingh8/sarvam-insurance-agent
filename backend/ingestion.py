import hashlib
import json
import os
import re
from pathlib import Path

import pdfplumber


def extract_text(pdf_path: str) -> str:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
    return "\n\n".join(pages)


def _extract_pages_data(pdf_path: str) -> list[dict]:
    """Extract per-page text and tables for structure builder."""
    pages_data = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            tables = page.extract_tables() or []
            pages_data.append({"page_num": i, "text": text, "tables": tables})
    return pages_data


def _sha256(pdf_path: str) -> str:
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_metadata(text: str) -> dict:
    """
    Extract plan_name, company_name, plan_type, one_line_pitch from the document.
    Uses OpenAI GPT-4o-mini on the first 1500 chars. Falls back to keyword extraction on failure.
    """
    import os
    from openai import OpenAI

    snippet = text[:1500].strip()

    prompt = (
        "You are reading an Indian insurance product brochure. "
        "Extract these four fields from the text below.\n\n"
        "Reply in EXACTLY this format (4 lines, nothing else):\n"
        "plan_name: <exact plan name>\n"
        "company_name: <insurance company or bank name>\n"
        "plan_type: <one of: term, health, savings, ulip, pension, child, other>\n"
        "one_line_pitch: <one spoken sentence, max 18 words, what this plan does for the customer>\n\n"
        f"Document:\n{snippet}\n\n"
        "Reply with the 4 lines only. No explanation. No markdown."
    )

    try:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("no key")
        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
        )
        raw = (resp.choices[0].message.content or "").strip()

        meta: dict = {}
        for line in raw.splitlines():
            if ":" in line:
                key_part, _, val_part = line.partition(":")
                k = key_part.strip().lower().replace(" ", "_")
                v = val_part.strip().strip('"').strip("'")
                if k in ("plan_name", "company_name", "plan_type", "one_line_pitch") and v:
                    meta[k] = v

        valid_types = {"term", "health", "savings", "ulip", "pension", "child", "other"}
        if meta.get("plan_type") not in valid_types:
            meta["plan_type"] = "other"

        if meta.get("plan_name") and meta.get("one_line_pitch"):
            return meta
    except Exception:
        pass

    # LLM failed — extract from text using keyword patterns
    return _extract_metadata_from_text(text)


def _extract_metadata_from_text(text: str) -> dict:
    """
    Keyword-based metadata extraction — no LLM, no API. Always returns real data.
    Used as fallback when LLM call fails or API key is missing.
    """
    snippet = text[:3000]
    lines = snippet.splitlines()

    # ── Company name ─────────────────────────────────────────────────
    known_companies = [
        ("HDFC Life", "HDFC Life"),
        ("HDFC", "HDFC Life"),
        ("Axis Max Life", "Axis Max Life"),
        ("Max Life", "Max Life Insurance"),
        ("ICICI Prudential", "ICICI Prudential Life Insurance"),
        ("ICICI Pru", "ICICI Prudential Life Insurance"),
        ("SBI Life", "SBI Life Insurance"),
        ("Bajaj Allianz", "Bajaj Allianz Life Insurance"),
        ("Tata AIA", "Tata AIA Life Insurance"),
        ("Kotak Life", "Kotak Life Insurance"),
        ("Kotak Mahindra", "Kotak Life Insurance"),
        ("Aditya Birla", "Aditya Birla Sun Life Insurance"),
        ("PNB MetLife", "PNB MetLife"),
        ("Reliance Nippon", "Reliance Nippon Life Insurance"),
        ("Canara HSBC", "Canara HSBC Life Insurance"),
        ("LIC", "LIC"),
        ("Life Insurance Corporation", "LIC"),
    ]
    company_name = ""
    for pattern, display in known_companies:
        if pattern.lower() in snippet.lower():
            company_name = display
            break

    # ── Plan name — look for "Introducing X" or first all-caps / title line ──
    plan_name = ""
    intro_match = re.search(r"Introducing\s+([A-Za-z0-9 &\-+]+)", snippet)
    if intro_match:
        plan_name = intro_match.group(1).strip()
    else:
        # Try lines that look like product names (mixed case, 2-6 words, not sentence)
        for line in lines[:30]:
            line = line.strip()
            if 10 < len(line) < 60 and not line.endswith(".") and not line.startswith("*"):
                words = line.split()
                if 2 <= len(words) <= 7 and any(w[0].isupper() for w in words):
                    plan_name = line
                    break

    if not plan_name:
        plan_name = company_name + " Insurance Plan" if company_name else "Insurance Plan"

    # ── Plan type ─────────────────────────────────────────────────────
    plan_type = _detect_plan_type(snippet, "other")

    # ── One-line pitch by plan type ───────────────────────────────────
    pitches = {
        "term": "provides a large life cover to protect your family financially if something happens to you",
        "health": "covers hospitalisation and medical expenses so your family never faces a financial crisis during illness",
        "ulip": "combines life insurance with market-linked investments to grow your wealth and protect your family",
        "savings": "helps you save systematically while keeping your family protected and earning guaranteed returns",
        "pension": "builds a retirement corpus so you have a steady income after you stop working",
        "child": "secures your child's future with a dedicated corpus for education or marriage",
        "other": "provides financial protection and security for you and your family",
    }
    one_line_pitch = pitches.get(plan_type, pitches["other"])

    return {
        "plan_name": plan_name,
        "company_name": company_name,
        "plan_type": plan_type,
        "one_line_pitch": one_line_pitch,
    }


def _extract_section(text: str, keywords: list[str], max_chars: int = 700) -> str:
    """
    Find the most relevant lines from document text for a given set of keywords.
    Groups consecutive matching lines into blocks, returns top matches.
    """
    lines = text.splitlines()
    kw_lower = [k.lower() for k in keywords]

    # Score each line
    scored_lines = []
    for i, line in enumerate(lines):
        ll = line.lower()
        score = sum(1 for kw in kw_lower if kw in ll)
        scored_lines.append((score, i, line))

    # Build context windows (line + 2 lines after) around top matches
    top_indices = sorted(
        [i for s, i, _ in scored_lines if s > 0],
        key=lambda i: -scored_lines[i][0]
    )

    included: set[int] = set()
    blocks: list[str] = []
    for idx in top_indices:
        window = list(range(max(0, idx - 1), min(len(lines), idx + 4)))
        new = [i for i in window if i not in included]
        if not new:
            continue
        block = "\n".join(lines[i] for i in sorted(new)).strip()
        if block and len("\n".join(blocks)) + len(block) < max_chars:
            blocks.append(block)
            included.update(new)
        if len("\n".join(blocks)) >= max_chars:
            break

    result = "\n\n".join(blocks)
    return result.strip() if result.strip() else "Refer to policy document for full details."


def _detect_plan_type(text: str, meta_type: str) -> str:
    """Detect plan type from document text — meta is a hint but text wins."""
    text_lower = text[:2000].lower()
    if any(kw in text_lower for kw in ["pure risk", "term plan", "term insurance", "death benefit only"]):
        return "term"
    if any(kw in text_lower for kw in ["unit linked", "ulip", "fund value", "nav"]):
        return "ulip"
    if any(kw in text_lower for kw in ["health insurance", "hospitalisation", "hospitalization", "medical expenses"]):
        return "health"
    if any(kw in text_lower for kw in ["pension", "annuity", "retirement", "vesting"]):
        return "pension"
    if any(kw in text_lower for kw in ["child plan", "children", "education fund", "child's future"]):
        return "child"
    if any(kw in text_lower for kw in ["endowment", "savings", "maturity benefit", "survival benefit", "money back"]):
        return "savings"
    return meta_type or "other"


def _generate_product_profile(text: str, meta: dict) -> str:
    """
    Generate advisor product brief. Tries LLM first for clean language;
    falls back to keyword extraction if the API call fails.
    """
    brief = _generate_brief_via_llm(text, meta)
    if brief:
        return brief
    return _generate_brief_via_keywords(text, meta)


def _generate_brief_via_llm(text: str, meta: dict) -> str:
    """
    One LLM call that rewrites raw document sections into clean advisor language.
    Returns empty string on any failure so the caller can fall back gracefully.
    """
    import os
    from openai import OpenAI

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return ""

    plan_name = meta.get("plan_name", "this plan")
    company = meta.get("company_name", "the insurer")
    plan_type = _detect_plan_type(text, meta.get("plan_type", "other"))

    sections = {
        "Overview": text[:800].strip(),
        "Coverage and variants": _extract_section(text,
            ["sum assured", "coverage", "plan option", "variant", "benefit amount"], 500),
        "Premiums": _extract_section(text,
            ["premium", "annual", "daily", "frequency", "loading", "non-smoker"], 500),
        "Eligibility and policy term": _extract_section(text,
            ["entry age", "minimum age", "maximum age", "policy term", "years"], 400),
        "Death benefit": _extract_section(text,
            ["death benefit", "nominee", "sum assured on death", "lump sum"], 400),
        "Maturity benefit": _extract_section(text,
            ["maturity benefit", "survival benefit", "return of premium", "money back"], 300),
        "Riders": _extract_section(text,
            ["rider", "add-on", "waiver", "accidental", "critical illness"], 300),
        "Tax": _extract_section(text,
            ["80c", "10(10d)", "80d", "tax benefit", "deduction"], 200),
        "Exclusions": _extract_section(text,
            ["exclusion", "not covered", "not payable", "suicide", "pre-existing"], 300),
    }

    digest = "\n\n".join(
        f"[{label}]\n{content}"
        for label, content in sections.items()
        if content and content != "Refer to policy document for full details."
    )

    prompt = f"""\
You are a senior insurance sales trainer writing a product brief for a sales advisor.

Study the document sections below and rewrite them as a clean advisor cheat-sheet.
The advisor will read this before every sales call — write in plain spoken English, not PDF language.

RULES:
- Plain English only. No markdown, no asterisks, no backtick characters.
- Replace backtick-R or grave-accent-R with the rupee symbol where it appears.
- Use the section labels exactly as shown below.
- Each section: 2-4 sentences maximum. Be specific — use actual numbers from the document.
- If a detail is absent from the document, write: not specified in document.
- Total output must stay under 1800 characters.

PLAN: {plan_name} | COMPANY: {company} | TYPE: {plan_type}

[DOCUMENT SECTIONS]
{digest}

Write the brief using exactly these section labels (one blank line between sections):

COVERAGE: what cover options exist, typical sum assured range, key variants
PREMIUMS: describe the premium payment structure only — frequency options (annual/monthly/single pay), any loading factors (smoker, age bands), and minimum premium if stated. Do NOT include illustrative rupee amounts, per-day costs, sample calculations, or "starting from" figures. Those belong in structured pricing data, not this brief.
ELIGIBILITY: entry age range, policy term options, key health conditions that affect acceptance
DEATH BENEFIT: how the nominee receives the payout, lump sum or income
MATURITY BENEFIT: what the customer gets if they survive the term (write "nil for pure term plans" if none)
RIDERS: optional add-ons available and what each covers in one phrase
TAX BENEFITS: which Income Tax sections apply and what deduction the customer gets
EXCLUSIONS: the two or three most important things this plan does not cover
PITCH: one sentence — the strongest reason a customer in their 30s with dependents should consider this plan today\
"""

    try:
        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=900,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if not raw or len(raw) < 200:
            return ""

        header = (
            f"PLAN: {plan_name} | COMPANY: {company}\n"
            f"TYPE: {plan_type.upper()}\n\n"
        )
        return header + raw

    except Exception:
        return ""


def _generate_brief_via_keywords(text: str, meta: dict) -> str:
    """
    Keyword-based fallback brief — used when LLM is unavailable.
    Produces raw but complete document sections.
    """
    plan_name = meta.get("plan_name", "this plan")
    company = meta.get("company_name", "the insurer")
    plan_type = _detect_plan_type(text, meta.get("plan_type", "other"))

    type_labels = {
        "term": "Term Insurance (Pure Risk Life Cover)",
        "health": "Health Insurance",
        "ulip": "Unit Linked Insurance Plan (ULIP)",
        "savings": "Savings / Endowment Plan",
        "pension": "Pension / Retirement Plan",
        "child": "Child Plan",
        "other": "Life Insurance Plan",
    }

    coverage_text = _extract_section(text,
        ["sum assured", "coverage", "cover", "benefit amount", "death benefit", "variants", "plan option"])
    premium_text = _extract_section(text,
        ["premium", "payment", "frequency", "annual", "monthly", "discount", "loading"])
    term_text = _extract_section(text,
        ["policy term", "entry age", "maximum age", "maturity age", "tenure", "years"])
    death_text = _extract_section(text,
        ["death benefit", "nominee", "death", "claim", "sum assured on death"])
    maturity_text = _extract_section(text,
        ["maturity benefit", "survival benefit", "maturity value", "money back", "return of premium"])
    riders_text = _extract_section(text,
        ["rider", "add-on", "optional", "additional cover", "waiver", "accidental"])
    tax_text = _extract_section(text,
        ["80c", "10(10d)", "80d", "tax", "section 10", "income tax", "deduction"])
    exclusions_text = _extract_section(text,
        ["exclusion", "not covered", "not payable", "suicide", "war", "pre-existing"])

    return (
        f"PLAN: {plan_name} | COMPANY: {company}\n"
        f"TYPE: {type_labels.get(plan_type, 'Life Insurance Plan').upper()}\n\n"
        f"COVERAGE: {coverage_text}\n\n"
        f"PREMIUMS: {premium_text}\n\n"
        f"ELIGIBILITY: {term_text}\n\n"
        f"DEATH BENEFIT: {death_text}\n\n"
        f"MATURITY BENEFIT: {maturity_text}\n\n"
        f"RIDERS: {riders_text}\n\n"
        f"TAX BENEFITS: {tax_text}\n\n"
        f"EXCLUSIONS: {exclusions_text}\n\n"
        f"OBJECTION HANDLING:\n{_objection_handling_for_type(plan_type, plan_name)}"
    )


def _objection_handling_for_type(plan_type: str, plan_name: str) -> str:
    shared = (
        f"Price objection: Translate the annual premium into daily cost (divide by 365). "
        f"Mention that premiums qualify for tax deduction under Section 80C, reducing the real cost. "
        f"Ask: 'What were you expecting to pay?'\n"
        f"Trust/Claims: Focus on the specific claim features in the document (e.g. Insta Payment, claim ratio). "
        f"If claim settlement ratio is in the document, cite it. "
        f"If not: 'I can't quote a number without the document, but I can tell you exactly how the claim process works here.'\n"
        f"Already have coverage: Ask 'Do you know what your current policy covers if you were hospitalised for 3 months or couldn't work?' "
        f"Then differentiate using the document's specific features.\n"
        f"Too complicated: 'Let me take it one part at a time. We'll start with the one thing that matters most for your situation.'"
    )
    return shared


def _profiling_questions_for_type(plan_type: str) -> str:
    """Return ordered profiling questions based on plan type — no LLM call needed."""
    base = {
        "term": (
            "1. How old are you?\n"
            "2. Are you married? Do you have any dependents?\n"
            "3. Do you smoke or use tobacco?\n"
            "4. Do you currently have any life insurance coverage?\n"
            "5. Roughly what is your monthly income — so I can suggest an appropriate coverage amount?\n"
            "6. Are there any specific financial commitments you want to protect — like a home loan or children's education?"
        ),
        "health": (
            "1. How old are you?\n"
            "2. How many family members would you want covered?\n"
            "3. Do you currently have any health insurance — employer or personal?\n"
            "4. Does anyone in the family have a pre-existing condition?\n"
            "5. What is your approximate monthly income — to help suggest an appropriate cover amount?"
        ),
        "savings": (
            "1. How old are you?\n"
            "2. What is your primary financial goal — building a corpus, saving for a specific goal, or both?\n"
            "3. How many years can you commit to this plan?\n"
            "4. How comfortable are you with market-linked returns versus guaranteed returns?\n"
            "5. Do you have any existing savings or investment plans?"
        ),
        "ulip": (
            "1. How old are you?\n"
            "2. What is your investment horizon — how many years?\n"
            "3. How comfortable are you with market risk?\n"
            "4. What is your primary goal — wealth creation, life cover, or both?\n"
            "5. Do you have existing market-linked investments?"
        ),
        "pension": (
            "1. How old are you and when do you plan to retire?\n"
            "2. What monthly income would you like after retirement?\n"
            "3. Do you have any existing retirement savings or pension plans?\n"
            "4. What is your approximate current monthly income?\n"
            "5. Are you open to a lump sum plus annuity structure, or do you prefer pure regular income?"
        ),
        "child": (
            "1. How old is your child?\n"
            "2. What are you saving toward — education, marriage, or a general corpus?\n"
            "3. How many years before you need the money?\n"
            "4. Do you have any existing savings for your child?\n"
            "5. What is your approximate monthly income — to suggest a suitable premium level?"
        ),
    }
    return base.get(plan_type, base["term"])


def ingest(pdf_path: str, index_dir: str = "data") -> tuple[int, str]:
    """
    Extract text from PDF, save .txt, .meta.json, .brief.txt, .structure.json, .chunks.json.
    Returns (page_count, name).
    """
    name = Path(pdf_path).stem
    text = extract_text(pdf_path)
    if not text.strip():
        raise ValueError(f"No extractable text in {pdf_path}")

    os.makedirs(index_dir, exist_ok=True)

    out_path = os.path.join(index_dir, f"{name}.txt")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)

    meta_path = os.path.join(index_dir, f"{name}.meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
    else:
        meta = _extract_metadata(text)
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)

    brief_path = os.path.join(index_dir, f"{name}.brief.txt")
    if not os.path.exists(brief_path):
        brief = _generate_product_profile(text, meta)
        with open(brief_path, "w", encoding="utf-8") as fh:
            fh.write(brief)

    # ── Product Structure JSON (premium tables + eligibility) ─────────────
    try:
        from structure_builder import build_product_structure
        pages_data = _extract_pages_data(pdf_path)
        doc_hash = _sha256(pdf_path)
        structure = build_product_structure(text, pages_data, meta, doc_hash)
        structure_path = os.path.join(index_dir, f"{name}.structure.json")
        with open(structure_path, "w", encoding="utf-8") as fh:
            json.dump(structure, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass  # structure.json is optional — quote engine handles missing file

    # ── BM25 chunks JSON (section-aware retrieval) ────────────────────────
    try:
        from bm25_store import BM25Store
        store = BM25Store.build(text)
        chunks_path = os.path.join(index_dir, f"{name}.chunks.json")
        store.save(chunks_path)
    except Exception:
        pass  # chunks.json is optional — rag.py falls back to keyword scorer

    page_count = len([p for p in text.split("\n\n") if p.strip()])
    return page_count, name


def load_document(index_dir: str, name: str) -> str:
    txt_path = os.path.join(index_dir, f"{name}.txt")
    with open(txt_path, encoding="utf-8") as fh:
        return fh.read()


def load_sales_brief(index_dir: str, name: str) -> str:
    brief_path = os.path.join(index_dir, f"{name}.brief.txt")
    try:
        with open(brief_path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def load_metadata(index_dir: str, name: str) -> dict:
    meta_path = os.path.join(index_dir, f"{name}.meta.json")
    try:
        with open(meta_path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "plan_name": "this plan",
            "company_name": "",
            "plan_type": "other",
            "one_line_pitch": "it provides financial protection for you and your family",
        }
