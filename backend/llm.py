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
TEMPERATURE = 0.7


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

    def complete(self, messages: list[dict]) -> str:
        from errors import LLMError, retry_call

        def _call() -> str:
            try:
                resp = _client().chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    max_tokens=MAX_TOKENS,
                    temperature=TEMPERATURE,
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

    def stream(self, messages: list[dict]) -> Iterator[str]:
        from errors import LLMError

        try:
            stream = _client().chat.completions.create(
                model=MODEL,
                messages=messages,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
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
