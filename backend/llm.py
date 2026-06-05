"""
LLM client — OpenAI GPT-4o-mini.

Sarvam AI handles STT (saaras:v3) and TTS (bulbul:v3).
OpenAI handles reasoning — no token-budget wrestling, no think blocks.
"""

from __future__ import annotations

import os
from typing import Iterator

from openai import OpenAI


MODEL = "gpt-4o-mini"
MAX_TOKENS = 600       # voice responses are short; 600 is generous

# Lower temperature = fewer hallucinated numbers at factual stages.
# High temperature preserved for warm/empathetic stages.
_TEMP_BY_STAGE: dict[str, float] = {
    "GREET":         0.7,
    "DISCOVERY":     0.2,   # data collection — low creativity, no invented numbers
    "GAP_CALC":      0.1,   # deterministic math readout — almost no variance
    "POSITION":      0.7,   # reframe — needs natural language variation
    "RECOMMEND":     0.3,
    "VARIANTS":      0.3,
    "EXPLAIN":       0.4,
    "OBJECTIONS":    0.5,
    "CLOSE":         0.3,
    "QUESTION_ANSWER": 0.2,
}
_DEFAULT_TEMP = 0.5


def _temp_for_stage(stage: str) -> float:
    return _TEMP_BY_STAGE.get(stage, _DEFAULT_TEMP)


def _client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=key)


class LLMClient:
    """
    Thin wrapper over the OpenAI chat completions API.
    Exposes complete() and stream() — same interface as the old sarvam-m client.
    """

    def complete(self, messages: list[dict], stage: str = "") -> str:
        from errors import LLMError, retry_call

        temperature = _temp_for_stage(stage)

        def _call() -> str:
            try:
                resp = _client().chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    max_tokens=MAX_TOKENS,
                    temperature=temperature,
                )
                result = (resp.choices[0].message.content or "").strip()
                if not result:
                    raise LLMError("OpenAI returned empty content")
                return result
            except LLMError:
                raise
            except Exception as exc:
                raise LLMError(str(exc)) from exc

        return retry_call(_call, label="LLM")

    def stream(self, messages: list[dict], stage: str = "") -> Iterator[str]:
        from errors import LLMError

        temperature = _temp_for_stage(stage)

        try:
            stream = _client().chat.completions.create(
                model=MODEL,
                messages=messages,
                max_tokens=MAX_TOKENS,
                temperature=temperature,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(str(exc)) from exc
