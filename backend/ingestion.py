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


def _extract_metadata(text: str) -> dict:
    """
    Extract plan_name, company_name, plan_type, one_line_pitch from the document.
    Uses the LLM on the first 1500 chars. Falls back to safe defaults on any failure.
    """
    import os
    from sarvamai import SarvamAI

    snippet = text[:1500].strip()

    # Ask for a simple key:value format — more LLM-friendly than JSON under token pressure
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
        key = os.getenv("SARVAM_API_KEY")
        if not key:
            raise RuntimeError("no key")
        client = SarvamAI(api_subscription_key=key)
        resp = client.chat.completions(
            messages=[{"role": "user", "content": prompt}],
            model="sarvam-m",
            temperature=0.1,
            max_tokens=400,
        )
        raw = resp.choices[0].message.content or ""
        # strip think tags — sarvam-m emits these, they can eat token budget
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

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

        # Return only if we got the key fields
        if meta.get("plan_name") and meta.get("one_line_pitch"):
            return meta
    except Exception:
        pass

    # safe fallback — caller always gets a usable dict
    return {
        "plan_name": "this plan",
        "company_name": "",
        "plan_type": "other",
        "one_line_pitch": "it provides financial protection for you and your family",
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
    Build a structured advisor product profile directly from the document text.
    Uses keyword extraction — no LLM calls, no API dependency, instant and reliable.
    The profile is structured for the advisor to study before a sales call.
    """
    plan_name = meta.get("plan_name", "this plan")
    company = meta.get("company_name", "the insurer")
    plan_type = _detect_plan_type(text, meta.get("plan_type", "other"))

    # Product type label
    type_labels = {
        "term": "Term Insurance (Pure Risk Life Cover)",
        "health": "Health Insurance",
        "ulip": "Unit Linked Insurance Plan (ULIP)",
        "savings": "Savings / Endowment Plan",
        "pension": "Pension / Retirement Plan",
        "child": "Child Plan",
        "other": "Life Insurance Plan",
    }
    product_type_label = type_labels.get(plan_type, "Life Insurance Plan")

    # Extract relevant sections from document text
    overview = text[:1200].strip()

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

    eligibility_text = _extract_section(text,
        ["entry age", "minimum age", "maximum age", "eligibility", "age at entry", "health"])

    special_text = _extract_section(text,
        ["special", "unique", "exclusive", "female", "women", "maternity", "return of premium",
         "insta payment", "accelerated", "double", "bharosa"])

    # Objection handling — generic but grounded in plan type
    objection_text = _objection_handling_for_type(plan_type, plan_name)

    profiling_q = _profiling_questions_for_type(plan_type)

    return (
        f"PLAN: {plan_name} | COMPANY: {company}\n\n"
        f"PRODUCT TYPE:\n{product_type_label}\n\n"
        f"PRODUCT OVERVIEW (first section of document):\n{overview}\n\n"
        f"COVERAGE AND SUM ASSURED:\n{coverage_text}\n\n"
        f"PREMIUM STRUCTURE:\n{premium_text}\n\n"
        f"POLICY TERM AND ELIGIBILITY:\n{term_text}\n{eligibility_text}\n\n"
        f"DEATH BENEFIT:\n{death_text}\n\n"
        f"MATURITY / SURVIVAL BENEFIT:\n{maturity_text}\n\n"
        f"RIDERS AND ADD-ONS:\n{riders_text}\n\n"
        f"TAX BENEFITS:\n{tax_text}\n\n"
        f"KEY EXCLUSIONS:\n{exclusions_text}\n\n"
        f"SPECIAL FEATURES:\n{special_text}\n\n"
        f"OBJECTION HANDLING:\n{objection_text}\n\n"
        f"CUSTOMER PROFILING QUESTIONS:\n{profiling_q}"
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
    """Extract text from PDF, save as .txt, .meta.json, and .brief.txt. Returns (page_count, name)."""
    name = Path(pdf_path).stem
    text = extract_text(pdf_path)
    if not text.strip():
        raise ValueError(f"No extractable text in {pdf_path}")

    os.makedirs(index_dir, exist_ok=True)

    out_path = os.path.join(index_dir, f"{name}.txt")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)

    meta = _extract_metadata(text)
    meta_path = os.path.join(index_dir, f"{name}.meta.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    brief = _generate_product_profile(text, meta)
    brief_path = os.path.join(index_dir, f"{name}.brief.txt")
    with open(brief_path, "w", encoding="utf-8") as fh:
        fh.write(brief)

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
