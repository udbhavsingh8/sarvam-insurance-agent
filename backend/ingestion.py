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


def _generate_sales_brief(text: str, meta: dict) -> str:
    """
    Generate a structured advisor sales brief from the full document.
    This gives the advisor pre-processed product knowledge — not raw PDF text.
    Falls back to a minimal brief on failure.
    """
    import os
    from sarvamai import SarvamAI

    # Use up to 3000 chars of the document for the brief
    snippet = text[:3000].strip()
    plan_name = meta.get("plan_name", "this plan")
    company = meta.get("company_name", "the insurer")

    prompt = (
        f"You are a senior insurance sales trainer. "
        f"Read this product document for '{plan_name}' by '{company}' and write a concise advisor briefing sheet.\n\n"
        f"The briefing sheet will be given to an advisor BEFORE their sales call. "
        f"It must be factual, grounded only in the document, and immediately useful for selling.\n\n"
        f"Write the briefing sheet under EXACTLY these headings:\n\n"
        f"WHAT THIS PLAN IS:\n"
        f"<2 sentences. Plain language. What it does and who it is for.>\n\n"
        f"TOP SELLING POINTS:\n"
        f"<3 to 4 bullet points. Each must include a specific number, benefit, or feature from the document. Lead with the strongest.>\n\n"
        f"BEST SUITED FOR:\n"
        f"<1-2 sentences. Describe the ideal customer profile based on the document.>\n\n"
        f"HANDLING OBJECTIONS:\n"
        f"Price: <specific counter using document facts>\n"
        f"Trust/Claims: <specific counter using document facts>\n"
        f"Already have coverage: <specific counter using document facts>\n\n"
        f"CLOSING ARGUMENT:\n"
        f"<1 sentence. The single most compelling reason to buy this plan, grounded in the document.>\n\n"
        f"Document:\n{snippet}\n\n"
        f"Write only the briefing sheet. Use only facts from the document. No invented numbers."
    )

    try:
        key = os.getenv("SARVAM_API_KEY")
        if not key:
            raise RuntimeError("no key")
        client = SarvamAI(api_subscription_key=key)
        resp = client.chat.completions(
            messages=[{"role": "user", "content": prompt}],
            model="sarvam-m",
            temperature=0.2,
            max_tokens=900,
        )
        raw = resp.choices[0].message.content or ""
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        if len(raw) > 100:
            return raw
    except Exception:
        pass

    return (
        f"WHAT THIS PLAN IS:\n{plan_name} by {company} — a life insurance plan.\n\n"
        f"TOP SELLING POINTS:\n- Provides life cover for the policyholder\n\n"
        f"BEST SUITED FOR:\nAnyone looking for financial protection for their family.\n\n"
        f"HANDLING OBJECTIONS:\n"
        f"Price: Focus on daily cost equivalent.\n"
        f"Trust/Claims: Refer to the insurer's track record.\n"
        f"Already have coverage: Ask if current cover is sufficient.\n\n"
        f"CLOSING ARGUMENT:\nThis plan gives your family a guaranteed safety net."
    )


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

    brief = _generate_sales_brief(text, meta)
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
