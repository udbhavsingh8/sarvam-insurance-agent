"""
BM25-based document retrieval with section-aware chunking.

Replaces the existing keyword bag-of-words scorer in rag.py.
Same external interface — callers see no difference.

Section-aware chunking:
  - Detects insurance document section headers (COVERAGE, EXCLUSIONS, etc.)
  - Keeps semantically coherent sections together
  - Splits large sections at paragraph boundaries
  - Prepends section header to every chunk for context

BM25 retrieval:
  - rank_bm25 BM25Okapi scoring
  - Falls back to first N chunks when query matches nothing
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from rank_bm25 import BM25Okapi


# ── Section header detection ──────────────────────────────────────────────────

_SECTION_KEYWORDS = [
    "coverage", "sum assured", "sum insured", "benefits", "key benefits",
    "death benefit", "maturity benefit", "survival benefit",
    "premiums", "premium payment", "mode of payment", "payment frequency",
    "eligibility", "entry age", "policy term", "tenure",
    "riders", "add-on", "optional benefit", "additional benefit",
    "exclusions", "exclusion", "not covered", "not payable",
    "tax", "tax benefit", "section 80", "income tax",
    "claims", "claim process", "claim settlement", "claim procedure",
    "definitions", "terms and conditions", "general conditions",
    "surrender", "revival", "lapse", "grace period",
    "free look", "nomination", "assignment",
]

_MIN_CHUNK_CHARS = 100
_MAX_CHUNK_CHARS = 800
_TARGET_CHUNK_CHARS = 500


def _is_section_header(line: str) -> bool:
    """Detect if a line looks like a section header."""
    line = line.strip()
    if not line or len(line) > 100:
        return False
    if line.endswith("."):
        return False

    line_lower = line.lower()
    # Match known insurance section keywords
    if any(kw in line_lower for kw in _SECTION_KEYWORDS):
        return True

    # ALL CAPS short lines are likely headers
    if line.isupper() and len(line) > 3:
        return True

    # Title Case lines that are short and don't end with punctuation
    words = line.split()
    if (
        3 <= len(words) <= 8
        and all(w[0].isupper() for w in words if w.isalpha() and len(w) > 2)
        and not re.search(r"[,;:]$", line)
    ):
        return True

    return False


def chunk_document(text: str) -> list[str]:
    """
    Split document into semantically coherent chunks.
    Returns list of chunk strings, each with its section label prepended.
    """
    lines = text.splitlines()
    chunks: list[str] = []

    current_section = "Document"
    current_block: list[str] = []

    def flush_block():
        nonlocal current_block
        block_text = "\n".join(current_block).strip()
        if len(block_text) < _MIN_CHUNK_CHARS:
            current_block = []
            return

        # Split large blocks at paragraph boundaries
        paragraphs = re.split(r"\n{2,}", block_text)
        running = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(running) + len(para) + 2 <= _MAX_CHUNK_CHARS:
                running = (running + "\n\n" + para).strip() if running else para
            else:
                if running:
                    chunks.append(f"[{current_section}]\n{running}")
                running = para

        if running:
            chunks.append(f"[{current_section}]\n{running}")

        current_block = []

    for line in lines:
        stripped = line.strip()
        if _is_section_header(stripped):
            flush_block()
            current_section = stripped or current_section
        else:
            current_block.append(line)

    flush_block()  # flush final block

    # If no section structure detected, fall back to paragraph chunking
    if not chunks:
        chunks = _fallback_paragraph_chunks(text)

    return [c for c in chunks if c.strip()]


def _fallback_paragraph_chunks(text: str) -> list[str]:
    """Simple paragraph-based chunking as fallback."""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > _MAX_CHUNK_CHARS and current:
            chunks.append(current)
            current = para
        else:
            current = (current + "\n\n" + para).strip() if current else para
    if current:
        chunks.append(current)
    return chunks


# ── BM25 index ────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Simple tokeniser — lowercase, alphanumeric tokens."""
    return re.findall(r"[a-z0-9₹]+", text.lower())


class BM25Store:
    """
    BM25 index over section-aware document chunks.

    Usage:
        store = BM25Store.build(document_text)
        store.save(path)
        store = BM25Store.load(path)
        chunks = store.retrieve("what happens on death", top_k=3)
    """

    def __init__(self, chunks: list[str], bm25: BM25Okapi) -> None:
        self.chunks = chunks
        self._bm25 = bm25

    @classmethod
    def build(cls, text: str) -> "BM25Store":
        chunks = chunk_document(text)
        if not chunks:
            chunks = [text[:1000]]  # last resort
        tokenized = [_tokenize(c) for c in chunks]
        bm25 = BM25Okapi(tokenized)
        return cls(chunks, bm25)

    def save(self, path: str) -> None:
        """Save chunks to JSON (BM25 is rebuilt from chunks on load)."""
        Path(path).write_text(json.dumps(self.chunks, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "BM25Store":
        """Load from saved chunks file and rebuild BM25 index."""
        chunks = json.loads(Path(path).read_text(encoding="utf-8"))
        tokenized = [_tokenize(c) for c in chunks]
        bm25 = BM25Okapi(tokenized)
        return cls(chunks, bm25)

    def retrieve(self, query: str, top_k: int = 3) -> str:
        """Return top-k chunks joined by separator."""
        if not query.strip():
            # No query — return opening chunks (product overview)
            top = self.chunks[:top_k]
        else:
            tokenized_query = _tokenize(query)
            scores = self._bm25.get_scores(tokenized_query)
            ranked = sorted(range(len(scores)), key=lambda i: -scores[i])
            top_indices = ranked[:top_k]

            # If all scores are zero (no keyword overlap), fall back to first chunks
            if all(scores[i] == 0 for i in top_indices):
                top = self.chunks[:top_k]
            else:
                top = [self.chunks[i] for i in top_indices]

        return "\n\n---\n\n".join(top)
