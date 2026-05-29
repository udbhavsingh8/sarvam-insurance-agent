"""Text-to-Speech using Sarvam bulbul:v3."""

import base64
import os
from typing import Iterator

from sarvamai import SarvamAI

from errors import TTSError, retry_call

TTS_MODEL = "bulbul:v3"
SAMPLE_RATE = 22050

# bulbul:v3 rejects inputs over ~500 chars; stay well under that.
MAX_TTS_CHARS = 400

# All 10 languages confirmed working with bulbul:v3.
# Any speaker works with any language — speaker identity is consistent across languages.
# Default speakers used when no character-specific speaker is passed.
_DEFAULT_SPEAKERS: dict[str, str] = {
    "en-IN": "anushka",
    "hi-IN": "anushka",
    "ta-IN": "anushka",
    "te-IN": "anushka",
    "kn-IN": "anushka",
    "ml-IN": "anushka",
    "mr-IN": "anushka",
    "bn-IN": "anushka",
    "gu-IN": "anushka",
    "pa-IN": "anushka",
}

SUPPORTED_LANGUAGES = list(_DEFAULT_SPEAKERS.keys())


def _get_client() -> SarvamAI:
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise RuntimeError("SARVAM_API_KEY is not set")
    return SarvamAI(api_subscription_key=key)


def _truncate_for_tts(text: str) -> str:
    """Trim to MAX_TTS_CHARS at the last sentence boundary, falling back to hard cut."""
    if len(text) <= MAX_TTS_CHARS:
        return text
    for sep in (". ", "? ", "! "):
        idx = text.rfind(sep, 0, MAX_TTS_CHARS)
        if idx > 0:
            return text[: idx + 1]
    return text[:MAX_TTS_CHARS]


def synthesize(text: str, language_code: str = "en-IN", speaker: str | None = None) -> bytes:
    """Non-streaming TTS. Returns full WAV audio as raw bytes."""
    if language_code not in SUPPORTED_LANGUAGES:
        language_code = "en-IN"
    spk = speaker or _DEFAULT_SPEAKERS[language_code]
    client = _get_client()
    text = _truncate_for_tts(text)

    def _call() -> bytes:
        try:
            response = client.text_to_speech.convert(
                text=text,
                target_language_code=language_code,
                speaker=spk,
                model=TTS_MODEL,
                output_audio_codec="wav",
                speech_sample_rate=SAMPLE_RATE,
                enable_preprocessing=True,
            )
            return base64.b64decode(response.audios[0])
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(str(exc)) from exc

    return retry_call(_call, label="TTS")


def synthesize_stream(
    text: str, language_code: str = "en-IN", speaker: str | None = None
) -> Iterator[bytes]:
    """Streaming TTS. Yields raw audio byte chunks."""
    if language_code not in SUPPORTED_LANGUAGES:
        language_code = "en-IN"
    spk = speaker or _DEFAULT_SPEAKERS[language_code]
    client = _get_client()
    text = _truncate_for_tts(text)

    try:
        yield from client.text_to_speech.convert_stream(
            text=text,
            target_language_code=language_code,
            speaker=spk,
            model=TTS_MODEL,
            output_audio_codec="wav",
            speech_sample_rate=SAMPLE_RATE,
            enable_preprocessing=True,
        )
    except TTSError:
        raise
    except Exception as exc:
        raise TTSError(str(exc)) from exc
