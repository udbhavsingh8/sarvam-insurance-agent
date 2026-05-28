import os
import pickle
import re
from pathlib import Path

import faiss
import numpy as np
import pdfplumber
from openai import OpenAI

CHUNK_SIZE = 1000       # characters per chunk
CHUNK_OVERLAP = 150     # overlap between consecutive chunks
EMBED_MODEL = "text-embedding-3-small"
EMBED_BATCH = 96        # max chunks per embedding API call


def extract_text(pdf_path: str) -> str:
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
    return "\n\n".join(pages)


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            # prefer breaking at a sentence boundary
            boundary = max(
                text.rfind(". ", start, end),
                text.rfind(".\n", start, end),
                text.rfind("! ", start, end),
                text.rfind("? ", start, end),
            )
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return chunks


def embed_chunks(chunks: list[str], client: OpenAI) -> np.ndarray:
    all_embeddings: list[list[float]] = []
    for i in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[i : i + EMBED_BATCH]
        response = client.embeddings.create(model=EMBED_MODEL, input=batch)
        all_embeddings.extend(item.embedding for item in response.data)
    return np.array(all_embeddings, dtype=np.float32)


def build_faiss_index(embeddings: np.ndarray) -> faiss.IndexFlatIP:
    # Normalize so inner-product == cosine similarity
    faiss.normalize_L2(embeddings)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    return index


def save_index(
    index: faiss.IndexFlatIP,
    chunks: list[str],
    out_dir: str,
    name: str,
) -> None:
    os.makedirs(out_dir, exist_ok=True)
    faiss.write_index(index, os.path.join(out_dir, f"{name}.faiss"))
    with open(os.path.join(out_dir, f"{name}.pkl"), "wb") as fh:
        pickle.dump(chunks, fh)


def load_index(index_dir: str, name: str) -> tuple[faiss.IndexFlatIP, list[str]]:
    index = faiss.read_index(os.path.join(index_dir, f"{name}.faiss"))
    with open(os.path.join(index_dir, f"{name}.pkl"), "rb") as fh:
        chunks: list[str] = pickle.load(fh)
    return index, chunks


def ingest(pdf_path: str, index_dir: str = "data") -> tuple[int, str]:
    """PDF → text → chunks → embeddings → FAISS. Returns (chunk_count, index_name)."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=api_key)
    name = Path(pdf_path).stem

    text = extract_text(pdf_path)
    if not text.strip():
        raise ValueError(f"No extractable text in {pdf_path}")

    chunks = chunk_text(text)
    embeddings = embed_chunks(chunks, client)
    index = build_faiss_index(embeddings)
    save_index(index, chunks, index_dir, name)

    return len(chunks), name


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    load_dotenv()
    pdf = sys.argv[1] if len(sys.argv) > 1 else "data/sample.pdf"
    count, idx_name = ingest(pdf)
    print(f"Ingested {count} chunks → index '{idx_name}'")
