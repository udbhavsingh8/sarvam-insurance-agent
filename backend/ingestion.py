import os
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


def ingest(pdf_path: str, index_dir: str = "data") -> tuple[int, str]:
    """Extract text from PDF, save as .txt. Returns (page_count, name)."""
    name = Path(pdf_path).stem
    text = extract_text(pdf_path)
    if not text.strip():
        raise ValueError(f"No extractable text in {pdf_path}")

    os.makedirs(index_dir, exist_ok=True)
    out_path = os.path.join(index_dir, f"{name}.txt")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)

    page_count = len([p for p in text.split("\n\n") if p.strip()])
    return page_count, name


def load_document(index_dir: str, name: str) -> str:
    txt_path = os.path.join(index_dir, f"{name}.txt")
    with open(txt_path, encoding="utf-8") as fh:
        return fh.read()
