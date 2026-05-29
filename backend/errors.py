"""
Shared error types and retry utility for all Sarvam API calls.

All external calls (STT, LLM, TTS) go through retry_call() so that
transient network failures are handled uniformly without duplicating
backoff logic in every module.
"""

from __future__ import annotations

import time
import logging
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SarvamAPIError(Exception):
    """Wrapper for any Sarvam API call failure."""
    def __init__(self, service: str, message: str, retryable: bool = True):
        super().__init__(f"[{service}] {message}")
        self.service = service
        self.retryable = retryable


class STTError(SarvamAPIError):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__("STT", message, retryable)


class LLMError(SarvamAPIError):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__("LLM", message, retryable)


class TTSError(SarvamAPIError):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__("TTS", message, retryable)


# Errors that should never be retried
_NON_RETRYABLE_PATTERNS = (
    "context window",
    "prompt_tokens",
    "max_tokens",
    "invalid",
    "not found",
    "unauthorized",
    "forbidden",
    "400",
    "401",
    "403",
    "404",
    "422",
)


def is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    if any(p in msg for p in _NON_RETRYABLE_PATTERNS):
        return False
    if isinstance(exc, SarvamAPIError):
        return exc.retryable
    return True  # Unknown errors: optimistically retry once


def retry_call(
    fn: Callable[[], T],
    label: str,
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> T:
    """
    Call fn() with exponential backoff retry.
    Raises the last exception if all attempts fail.
    Non-retryable errors (4xx, context overflow) are raised immediately.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if not is_retryable(exc):
                logger.warning("%s: non-retryable error on attempt %d: %s", label, attempt, exc)
                raise
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning("%s: attempt %d failed (%s), retrying in %.1fs", label, attempt, exc, delay)
                time.sleep(delay)
            else:
                logger.error("%s: all %d attempts failed. Last error: %s", label, max_attempts, exc)

    raise last_exc  # type: ignore[misc]
