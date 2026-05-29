import re
from ingestion import load_document

CHUNK_SIZE = 600    # chars per chunk
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
        self._chunks = _make_chunks(self.text)

    def retrieve(self, query: str, top_k: int = TOP_K) -> str:
        scored = sorted(
            self._chunks, key=lambda c: _score(c, query), reverse=True
        )
        top = scored[:top_k]
        if not any(_score(c, query) > 0 for c in top):
            # no keyword match — return first top_k chunks (product overview)
            top = self._chunks[:top_k]
        return "\n\n---\n\n".join(top)

    def get_context(self, query: str = "") -> str:
        return self.retrieve(query) if query else self.retrieve("insurance policy benefits coverage")
