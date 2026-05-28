"""
tts.py — Text-to-Speech using Sarvam bulbul:v3.

Supports 4 languages:  en-IN  hi-IN  ta-IN  te-IN

Provides two entry points:
  synthesize()        → bytes  (full WAV, for short utterances)
  synthesize_stream() → Iterator[bytes]  (chunked stream, for FastAPI StreamingResponse)
"""

import base64
import os
from typing import Iterator

from sarvamai import SarvamAI

TTS_MODEL = "bulbul:v3"
SAMPLE_RATE = 22050   # Hz — good quality for voice; 8 000 is telephone grade

# One natural-sounding speaker per supported language.
# These are all from the bulbul:v3 speaker catalogue.
_SPEAKERS: dict[str, str] = {
    "en-IN": "anushka",   # clear Indian-English female voice
    "hi-IN": "manisha",   # natural Hindi female voice
    "ta-IN": "arya",      # Tamil female voice
    "te-IN": "vidya",     # Telugu female voice
}

SUPPORTED_LANGUAGES = list(_SPEAKERS.keys())


def _get_client() -> SarvamAI:
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise RuntimeError("SARVAM_API_KEY is not set")
    return SarvamAI(api_subscription_key=key)


def _speaker(language_code: str) -> str:
    return _SPEAKERS.get(language_code, "anushka")


def synthesize(text: str, language_code: str = "en-IN") -> bytes:
    """
    Non-streaming TTS.  Returns the full WAV audio as raw bytes.

    Suitable for short responses or fallback when streaming isn't needed.
    """
    client = _get_client()
    response = client.text_to_speech.convert(
        text=text,
        target_language_code=language_code,
        speaker=_speaker(language_code),
        model=TTS_MODEL,
        output_audio_codec="wav",
        speech_sample_rate=SAMPLE_RATE,
        enable_preprocessing=True,
    )
    # audios[0] is a base64-encoded WAV string
    return base64.b64decode(response.audios[0])


def synthesize_stream(text: str, language_code: str = "en-IN") -> Iterator[bytes]:
    """
    Streaming TTS.  Yields raw audio byte chunks as they arrive from the API.

    Pipe directly into a FastAPI ``StreamingResponse`` so the browser can
    start playing audio before the full synthesis is complete.
    """
    client = _get_client()
    yield from client.text_to_speech.convert_stream(
        text=text,
        target_language_code=language_code,
        speaker=_speaker(language_code),
        model=TTS_MODEL,
        output_audio_codec="wav",
        speech_sample_rate=SAMPLE_RATE,
        enable_preprocessing=True,
    )
