import os

import faiss
import numpy as np
from openai import OpenAI

from ingestion import EMBED_MODEL, load_index

TOP_K = 5


class RAGRetriever:
    """Wraps a FAISS index + chunk store; embeds queries and returns top-k chunks."""

    def __init__(self, index_dir: str, name: str) -> None:
        self.index, self.chunks = load_index(index_dir, name)
        self._openai: OpenAI | None = None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _client(self) -> OpenAI:
        if self._openai is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is not set")
            self._openai = OpenAI(api_key=api_key)
        return self._openai

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def retrieve(self, query: str, top_k: int = TOP_K) -> list[str]:
        """Embed *query* and return the top-k most similar chunks."""
        resp = self._client().embeddings.create(model=EMBED_MODEL, input=[query])
        q_vec = np.array([resp.data[0].embedding], dtype=np.float32)
        faiss.normalize_L2(q_vec)
        distances, indices = self.index.search(q_vec, top_k)
        return [
            self.chunks[idx]
            for idx, score in zip(indices[0], distances[0])
            if idx >= 0 and score > 0.0
        ]

    @staticmethod
    def format_context(chunks: list[str]) -> str:
        """Format retrieved chunks into a single context block for the LLM."""
        if not chunks:
            return "(No relevant content found in the document.)"
        return "\n\n---\n\n".join(
            f"[Excerpt {i + 1}]\n{chunk}" for i, chunk in enumerate(chunks)
        )
