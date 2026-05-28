"""
agent.py — LLM logic for the Insurance Sales Voice Agent.

Modes
-----
  pitch  Agent proactively pitches the insurance product from the document.
  qa     Agent answers only questions that can be answered from the document.

Both modes use dynamic RAG: on every turn the user query is embedded,
top-k chunks are retrieved from FAISS, and injected into the system prompt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterator

from sarvamai import SarvamAI

from rag import RAGRetriever

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

LLM_MODEL = "sarvam-m"   # sarvam-105b / 128 K context
MAX_TOKENS = 512
TEMPERATURE = 0.7

# Internal RAG trigger for the opening pitch (no real user query yet)
_PITCH_RAG_SEED = "insurance policy overview benefits coverage premium exclusions"

# ------------------------------------------------------------------ #
# Prompt templates
# ------------------------------------------------------------------ #

_PITCH_SYSTEM = """\
You are an expert insurance sales agent for an Indian insurance company.
Your job is to proactively pitch the product described in the document excerpts below
to a potential customer over a voice call.

DOCUMENT EXCERPTS:
{context}

RULES:
1. Highlight the most compelling benefits, coverage, and value propositions from the excerpts.
2. After presenting 2-3 key points, invite the customer to ask questions or share concerns.
3. Handle objections calmly — always support your response with specific details from the excerpts.
4. If a question cannot be answered from the document, say:
   "I don't have that specific detail in front of me, but I can find out for you."
5. Never fabricate premium amounts, coverage limits, or policy terms.
6. Keep every response concise — 2-4 sentences — suitable for voice delivery.
7. Use a warm, professional, conversational tone appropriate for India.\
"""

_QA_SYSTEM = """\
You are a knowledgeable insurance product specialist answering customer questions over a voice call.
Answer strictly from the document excerpts below.

DOCUMENT EXCERPTS:
{context}

RULES:
1. Answer ONLY from the excerpts provided above.
2. If the answer is not in the excerpts, explicitly say:
   "That information is not available in the current product document."
3. Be precise — quote or closely paraphrase the document when relevant.
4. Keep every response concise — 2-4 sentences — suitable for voice delivery.
5. Never guess or fabricate policy details.
6. Use a warm, professional, conversational tone appropriate for India.\
"""

_SUMMARY_TEMPLATE = """\
Below is a conversation between an insurance sales agent and a customer.
Produce a concise structured summary.

CONVERSATION:
{conversation}

Format your summary as:
1. Product discussed — name or type of insurance product
2. Key points covered — bullet list of main features/benefits discussed
3. Customer questions & concerns — what the customer asked or objected to
4. Outcome — apparent interest level and any agreed next steps

Be factual and concise.\
"""


# ------------------------------------------------------------------ #
# AgentSession
# ------------------------------------------------------------------ #


@dataclass
class AgentSession:
    """
    Manages a single customer conversation session.

    Parameters
    ----------
    retriever : RAGRetriever
        Loaded FAISS retriever for the uploaded insurance document.
    mode : str
        Starting mode — ``"pitch"`` or ``"qa"``.
    """

    retriever: RAGRetriever
    mode: str = "pitch"
    history: list[dict] = field(default_factory=list)
    _sarvam: SarvamAI | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _get_sarvam(self) -> SarvamAI:
        if self._sarvam is None:
            key = os.getenv("SARVAM_API_KEY")
            if not key:
                raise RuntimeError("SARVAM_API_KEY is not set")
            self._sarvam = SarvamAI(api_subscription_key=key)
        return self._sarvam

    def _system_prompt(self, rag_query: str) -> str:
        chunks = self.retriever.retrieve(rag_query)
        context = RAGRetriever.format_context(chunks)
        template = _PITCH_SYSTEM if self.mode == "pitch" else _QA_SYSTEM
        return template.format(context=context)

    def _build_messages(self, system: str) -> list[dict]:
        return [{"role": "system", "content": system}] + self.history

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def set_mode(self, mode: str) -> None:
        """Switch between ``"pitch"`` and ``"qa"`` modes."""
        if mode not in ("pitch", "qa"):
            raise ValueError(f"Unknown mode '{mode}'. Choose 'pitch' or 'qa'.")
        self.mode = mode

    def open_pitch(self) -> str:
        """
        Generate the agent's opening pitch (no prior user message).
        Use this to kick off a Pitch-mode session.
        """
        system = self._system_prompt(_PITCH_RAG_SEED)
        messages = self._build_messages(system) + [
            {"role": "user", "content": "Please introduce me to this insurance product."}
        ]
        resp = self._get_sarvam().chat.completions(
            messages=messages,
            model=LLM_MODEL,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
        reply: str = resp.choices[0].message.content or ""
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def chat(self, user_message: str) -> str:
        """
        Single-turn exchange — returns the full assistant reply.
        Suitable for non-streaming use (text / REST response).
        """
        self.history.append({"role": "user", "content": user_message})
        system = self._system_prompt(user_message)
        messages = self._build_messages(system)

        resp = self._get_sarvam().chat.completions(
            messages=messages,
            model=LLM_MODEL,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
        reply: str = resp.choices[0].message.content or ""
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def chat_stream(self, user_message: str) -> Iterator[str]:
        """
        Streaming version — yields text tokens as they arrive from the LLM.
        Full reply is appended to history once streaming is complete.
        Used by the FastAPI ``/chat`` SSE endpoint to feed TTS chunk-by-chunk.
        """
        self.history.append({"role": "user", "content": user_message})
        system = self._system_prompt(user_message)
        messages = self._build_messages(system)

        stream = self._get_sarvam().chat.completions(
            messages=messages,
            model=LLM_MODEL,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=True,
        )

        full_reply: list[str] = []
        for chunk in stream:
            delta: str | None = chunk.choices[0].delta.content
            if delta:
                full_reply.append(delta)
                yield delta

        self.history.append({"role": "assistant", "content": "".join(full_reply)})

    def summarize(self) -> str:
        """
        Generate a structured end-of-session summary from conversation history.
        Returns plain text — used by the ``/summary`` endpoint.
        """
        if not self.history:
            return "No conversation to summarize."

        conversation_text = "\n".join(
            f"{msg['role'].upper()}: {msg['content']}" for msg in self.history
        )
        messages = [
            {
                "role": "user",
                "content": _SUMMARY_TEMPLATE.format(conversation=conversation_text),
            }
        ]
        resp = self._get_sarvam().chat.completions(
            messages=messages,
            model=LLM_MODEL,
            temperature=0.3,
            max_tokens=600,
        )
        return resp.choices[0].message.content or "Summary unavailable."

    def reset(self) -> None:
        """Clear conversation history (keep mode and retriever)."""
        self.history.clear()
