"""
Model-agnostic LLM client.

Switching models requires changing ACTIVE_CONFIG — no other code changes.
Adding a new model requires adding a new LLMConfig entry.

Current selection: sarvam-m
Reason: only model with T3 < 4s on starter tier (sarvam-105b needs ~17s thinking phase).
Re-evaluate when Sarvam adds thinking_budget control to sarvam-105b.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterator

from sarvamai import SarvamAI


@dataclass
class LLMConfig:
    model_id: str
    max_tokens: int
    temperature: float
    strip_think_tags: bool   # True for models that embed <think>...</think> in content


SARVAM_M = LLMConfig(
    model_id="sarvam-m",
    max_tokens=1800,  # starter tier cap is 2048; 1800 leaves headroom for think block + response
    temperature=0.7,
    strip_think_tags=True,
)

SARVAM_105B = LLMConfig(
    model_id="sarvam-105b",
    max_tokens=4096,
    temperature=0.7,
    strip_think_tags=False,  # 105b uses reasoning_content field, not inline tags
)

# Change this one line to switch the active model globally
ACTIVE_CONFIG: LLMConfig = SARVAM_M


def _slim_messages(messages: list[dict]) -> list[dict]:
    """
    Produce a stripped-down version of the message list for a think-block-overflow retry.
    Keeps only: first 800 chars of the system prompt + last 2 history turns + current user turn.
    Reduces input tokens by ~60%, giving the think block room to breathe.
    """
    result = []
    for msg in messages:
        if msg["role"] == "system":
            content = msg["content"]
            # Keep up to 800 chars — enough for core identity + stage intent
            result.append({"role": "system", "content": content[:800] + "\n[Context trimmed for brevity. Respond naturally.]"})
        else:
            result.append(msg)
    # Keep only last 2 user/assistant pairs + current user turn
    non_system = [m for m in result if m["role"] != "system"]
    system = [m for m in result if m["role"] == "system"]
    return system + non_system[-5:]


def _strip_think(text: str) -> str:
    """
    Remove <think>...</think> blocks from sarvam-m output.
    If the tag is unclosed (think block consumed all tokens before </think>),
    the entire text is junk — raise so the caller uses the fallback.
    """
    from errors import LLMError
    if "<think>" in text and "</think>" not in text:
        raise LLMError("sarvam-m think block truncated — no content produced")
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


class LLMClient:
    """
    Thin wrapper over the Sarvam SDK chat completions API.
    Exposes complete() and stream() — both return clean text with think blocks removed.
    """

    def __init__(self, config: LLMConfig = ACTIVE_CONFIG) -> None:
        self.config = config
        self._sdk: SarvamAI | None = None

    def _client(self) -> SarvamAI:
        if self._sdk is None:
            key = os.getenv("SARVAM_API_KEY")
            if not key:
                raise RuntimeError("SARVAM_API_KEY is not set")
            self._sdk = SarvamAI(api_subscription_key=key)
        return self._sdk

    def complete(self, messages: list[dict]) -> str:
        from errors import LLMError, retry_call

        def _call(msgs: list[dict]) -> str:
            try:
                resp = self._client().chat.completions(
                    messages=msgs,
                    model=self.config.model_id,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
                raw = resp.choices[0].message.content or ""
                result = _strip_think(raw) if self.config.strip_think_tags else raw.strip()
                if not result:
                    raise LLMError("sarvam-m produced no content after think block")
                return result
            except LLMError:
                raise
            except Exception as exc:
                raise LLMError(str(exc)) from exc

        try:
            return retry_call(lambda: _call(messages), label="LLM")
        except LLMError as first_err:
            # Think block exhausted tokens — retry with a minimal prompt
            if "no content after think block" in str(first_err):
                slim = _slim_messages(messages)
                return retry_call(lambda: _call(slim), label="LLM-slim")
            raise

    def stream(self, messages: list[dict]) -> Iterator[str]:
        """
        Yields clean content tokens only.
        For sarvam-m: buffers until </think> tag then yields content tokens.
        For other models: yields content tokens directly.
        """
        from errors import LLMError

        try:
            sdk_stream = self._client().chat.completions(
                messages=messages,
                model=self.config.model_id,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                stream=True,
            )
        except Exception as exc:
            raise LLMError(str(exc)) from exc

        if not self.config.strip_think_tags:
            try:
                for chunk in sdk_stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
            except LLMError:
                raise
            except Exception as exc:
                raise LLMError(str(exc)) from exc
            return

        # sarvam-m: buffer tokens until </think> marker, then stream content
        buffer: list[str] = []
        past_think = False
        yielded_any = False

        try:
            for chunk in sdk_stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if not delta:
                    continue

                if past_think:
                    yield delta
                    yielded_any = True
                    continue

                buffer.append(delta)
                combined = "".join(buffer)
                if "</think>" in combined:
                    past_think = True
                    after = combined.split("</think>", 1)[1]
                    buffer = []
                    if after.strip():
                        yield after
                        yielded_any = True
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(str(exc)) from exc

        if not yielded_any:
            raise LLMError("sarvam-m produced no content after think block")
