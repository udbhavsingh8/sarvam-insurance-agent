"""Speech-to-Text using Sarvam saaras:v3."""

import os

from sarvamai import SarvamAI

from errors import STTError, retry_call


def _get_client() -> SarvamAI:
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise RuntimeError("SARVAM_API_KEY is not set")
    return SarvamAI(api_subscription_key=key)


def transcribe(audio_bytes: bytes) -> dict:
    """
    Transcribe audio bytes with saaras:v3 in codemix mode.

    Always uses language_code='unknown' for auto-detection — passing specific
    codes to the SDK can return None for language_probability and cause errors.

    Returns
    -------
    dict
        {transcript: str, language_code: str, language_probability: float}
    """
    client = _get_client()

    def _call() -> dict:
        try:
            response = client.speech_to_text.transcribe(
                file=("audio.webm", audio_bytes, "audio/webm"),
                model="saaras:v3",
                mode="codemix",
                language_code="unknown",
            )
            return {
                "transcript": response.transcript or "",
                "language_code": getattr(response, "language_code", None) or "en-IN",
                "language_probability": getattr(response, "language_probability", None) or 0.0,
            }
        except STTError:
            raise
        except Exception as exc:
            raise STTError(str(exc)) from exc

    return retry_call(_call, label="STT")
