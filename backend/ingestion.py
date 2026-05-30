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
    Call the LLM on the first ~1000 chars of document text to extract
    plan_name, company_name, plan_type, and one_line_pitch.
    Falls back to safe defaults if the call fails.
    """
    import os
    from sarvamai import SarvamAI

    snippet = text[:1000].strip()

    prompt = f"""You are reading the beginning of an Indian insurance product document.
Extract the following fields from the text below. Reply ONLY with a valid JSON object — no explanation, no markdown.

Fields:
- plan_name: the exact name of the insurance plan (string)
- company_name: the insurance company or bank offering this plan (string)
- plan_type: one of exactly these values: term | health | savings | ulip | pension | child | other
- one_line_pitch: one natural spoken sentence (max 20 words) describing what this plan does for the customer — written as an advisor would say it aloud, not as marketing copy

Document text:
{snippet}

Reply with JSON only. Example:
{{"plan_name": "Click 2 Protect Plus", "company_name": "HDFC Life", "plan_type": "term", "one_line_pitch": "it gives your family a financial safety net of up to one crore rupees if something were to happen to you"}}"""

    try:
        key = os.getenv("SARVAM_API_KEY")
        if not key:
            raise RuntimeError("no key")
        client = SarvamAI(api_subscription_key=key)
        resp = client.chat.completions(
            messages=[{"role": "user", "content": prompt}],
            model="sarvam-m",
            temperature=0.1,
            max_tokens=200,
        )
        raw = resp.choices[0].message.content or ""
        # strip think tags if present
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        # extract JSON block
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            meta = json.loads(json_match.group())
            # validate plan_type
            valid_types = {"term", "health", "savings", "ulip", "pension", "child", "other"}
            if meta.get("plan_type") not in valid_types:
                meta["plan_type"] = "other"
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


def ingest(pdf_path: str, index_dir: str = "data") -> tuple[int, str]:
    """Extract text from PDF, save as .txt and .meta.json. Returns (page_count, name)."""
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

    page_count = len([p for p in text.split("\n\n") if p.strip()])
    return page_count, name


def load_document(index_dir: str, name: str) -> str:
    txt_path = os.path.join(index_dir, f"{name}.txt")
    with open(txt_path, encoding="utf-8") as fh:
        return fh.read()


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
