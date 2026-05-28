"""
stt.py — Speech-to-Text using Sarvam saaras:v3.

Uses `codemix` mode so it handles Hindi-English (Hinglish) speech naturally,
which is the dominant register for insurance conversations in India.
"""

import os

from sarvamai import SarvamAI

# Use 'unknown' to let saaras auto-detect language within the codemix mode;
# callers may pass an explicit BCP-47 code when the UI language is known.
DEFAULT_LANGUAGE = "unknown"


def _get_client() -> SarvamAI:
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise RuntimeError("SARVAM_API_KEY is not set")
    return SarvamAI(api_subscription_key=key)


def transcribe(audio_bytes: bytes, language_code: str = DEFAULT_LANGUAGE) -> str:
    """
    Transcribe raw audio bytes with saaras:v3 in codemix mode.

    Parameters
    ----------
    audio_bytes : bytes
        PCM / WAV / WebM audio captured by the browser's MediaRecorder.
    language_code : str
        BCP-47 language hint (e.g. ``"hi-IN"``, ``"en-IN"``).
        Pass ``"unknown"`` for automatic language detection.

    Returns
    -------
    str
        Transcribed text (may contain Hindi-English code-mixed output).
    """
    client = _get_client()
    response = client.speech_to_text.transcribe(
        file=("audio.webm", audio_bytes, "audio/webm"),
        model="saaras:v3",
        mode="codemix",
        language_code=language_code,
    )
    return response.transcript or ""
