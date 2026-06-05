import os
import re
from ingestion import load_document, load_metadata, load_sales_brief

CHUNK_SIZE = 600    # chars per chunk (fallback keyword scorer)
TOP_K      = 4      # chunks to include in context


def _make_chunks(text: str, size: int = CHUNK_SIZE) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > size and current:
            chunks.append(current)
            current = para
        else:
            current = (current + "\n\n" + para).strip() if current else para
    if current:
        chunks.append(current)
    return chunks


def _score(chunk: str, query: str) -> int:
    words = set(re.findall(r"\w+", query.lower()))
    chunk_lower = chunk.lower()
    return sum(1 for w in words if w in chunk_lower)


class DocumentStore:
    def __init__(self, index_dir: str, name: str) -> None:
        self.text = load_document(index_dir, name)
        self.name = name
        self.metadata: dict = load_metadata(index_dir, name)
        self.sales_brief: str = load_sales_brief(index_dir, name)

        # Load BM25 index if available; otherwise fall back to keyword scorer.
        self._bm25: object | None = None
        chunks_path = os.path.join(index_dir, f"{name}.chunks.json")
        if os.path.exists(chunks_path):
            try:
                from bm25_store import BM25Store
                self._bm25 = BM25Store.load(chunks_path)
            except Exception:
                pass

        # Fallback: simple keyword scorer over plain chunks
        self._chunks = _make_chunks(self.text) if self._bm25 is None else []

        # Load structure.json for quote engine (optional)
        structure_path = os.path.join(index_dir, f"{name}.structure.json")
        if os.path.exists(structure_path):
            try:
                import json
                with open(structure_path, encoding="utf-8") as fh:
                    self.structure: dict = json.load(fh)
            except Exception:
                self.structure = {}
        else:
            self.structure = {}

    def retrieve(self, query: str, top_k: int = TOP_K) -> str:
        if self._bm25 is not None:
            return self._bm25.retrieve(query, top_k=top_k)

        # Keyword scorer fallback
        scored = sorted(
            self._chunks, key=lambda c: _score(c, query), reverse=True
        )
        top = scored[:top_k]
        if not any(_score(c, query) > 0 for c in top):
            top = self._chunks[:top_k]
        return "\n\n---\n\n".join(top)

    def get_context(self, query: str = "", top_k: int = TOP_K) -> str:
        q = query if query else "insurance policy benefits coverage"
        return self.retrieve(q, top_k=top_k)
