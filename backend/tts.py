"""Text-to-Speech using Sarvam bulbul:v3."""

import base64
import os
import re
from typing import Iterator

from sarvamai import SarvamAI

from errors import TTSError, retry_call


# ── TTS speech normalization ──────────────────────────────────────────────────

_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _int_to_words(n: int) -> str:
    """Convert integer 0–99 to English words."""
    if n < 20:
        return _ONES[n]
    t, o = divmod(n, 10)
    return _TENS[t] + (" " + _ONES[o] if o else "")


def _rupee_amount(m: re.Match) -> str:
    """Convert ₹ amount match to spoken form."""
    num_str = m.group(1).replace(",", "")
    suffix = (m.group(2) or "").strip().lower()
    try:
        val = float(num_str)
    except ValueError:
        return m.group(0)

    def _num_word(v: float) -> str:
        n = int(v) if v == int(v) else v
        if isinstance(n, int) and 1 <= n < 100:
            return _int_to_words(n)
        return str(n)

    if suffix in ("crore", "cr"):
        spoken = f"{_num_word(val)} crore"
    elif suffix in ("lakh", "lac", "l", "lpa"):
        spoken = f"{_num_word(val)} lakh"
    elif suffix in ("thousand", "k"):
        n = int(val)
        spoken = f"{_int_to_words(n) if n < 20 else n} thousand"
    else:
        n = int(val)
        if n >= 10_000_000:
            spoken = f"{n // 10_000_000} crore"
        elif n >= 100_000:
            spoken = f"{n // 100_000} lakh"
        elif n >= 1000:
            t, r = divmod(n, 1000)
            t_words = _int_to_words(t) if t < 20 else str(t)
            spoken = f"{t_words} thousand" + (f" {r}" if r else "")
        elif n >= 100:
            h, r = divmod(n, 100)
            spoken = f"{_ONES[h]} hundred" + (f" {r}" if r else "")
        elif n < 100:
            spoken = _int_to_words(n) if n > 0 else "zero"
        else:
            spoken = str(n)

    per = ""
    per_match = re.search(r'/\s*(day|month|year|annum|p\.?a\.?)', m.group(0), re.IGNORECASE)
    if per_match:
        per_map = {"day": "per day", "month": "per month", "year": "per year",
                   "annum": "per annum", "pa": "per annum", "p.a.": "per annum"}
        per = " " + per_map.get(per_match.group(1).lower().replace(".", ""), "")

    return f"{spoken} rupees{per}"


def normalize_for_tts(text: str) -> str:
    """
    Convert TTS-hostile patterns to natural spoken forms.
    Called on each sentence before it reaches bulbul:v3.

    Pass order (matters — run early passes first):
      1. Email addresses
      2. Devanagari unit words → English equivalents  (so downstream regexes work)
      3. Decimal space fix ("1. 5" → "1.5")
      4. Decimal crore/lakh amounts (range then single)
      5. Acronyms / abbreviations
      6. Product names
      7. Age hyphen patterns
      8. LPA
      9. ₹ amounts (plain integers)
      10. Percentages
      11. Large plain numbers
    """
    # ── 1. Email addresses ────────────────────────────────────────────────
    def _email(m: re.Match) -> str:
        local, domain = m.group(1), m.group(2)
        domain_spoken = domain.replace(".", " dot ")
        return f"{local} at {domain_spoken}"
    text = re.sub(r'([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})', _email, text)

    # ── 2. Devanagari unit normalisation (must run BEFORE all amount regexes) ──
    # Replace Devanagari currency/unit words with their English equivalents so
    # the downstream amount regexes can match them uniformly.
    text = re.sub(r'करोड़(?:ों)?', 'crore', text)          # करोड़ / करोड़ों
    text = re.sub(r'लाख(?:ों)?', 'lakh', text)              # लाख / लाखों
    text = re.sub(r'रुपय(?:े|ों)|रुपये?', 'rupees', text)   # रुपये / रुपयों
    text = re.sub(r'(?:प्रति\s+)?वर्ष|सालाना|वार्षिक', 'per year', text)
    text = re.sub(r'(?:प्रति\s+)?माह|महीन(?:े|ा)', 'per month', text)
    text = re.sub(r'प्रतिदिन|प्रति\s+दिन', 'per day', text)

    # ── 3. Decimal space fix: "1. 5" → "1.5" ────────────────────────────
    text = re.sub(r'(\d+)\.\s+(\d+)', r'\1.\2', text)

    # ── 4. Decimal amount helpers ─────────────────────────────────────────
    _DIGIT_WORDS = {
        "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
        "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    }

    def _decimal_to_spoken(integer_part: str, decimal_part: str) -> str:
        int_word = _int_to_words(int(integer_part)) if 0 < int(integer_part) < 20 else integer_part
        frac_spoken = " ".join(_DIGIT_WORDS.get(d, d) for d in decimal_part)
        return f"{int_word} point {frac_spoken}"

    # Range: "₹1.5 crore to ₹2.5 crore" or "1.5 to 2.5 crore"
    def _decimal_range_amount(m: re.Match) -> str:
        unit_word = "crore" if m.group(5).lower() in ("crore", "crores", "cr") else "lakh"
        return (
            f"{_decimal_to_spoken(m.group(1), m.group(2))} to "
            f"{_decimal_to_spoken(m.group(3), m.group(4))} {unit_word}"
        )
    text = re.sub(
        r'(?:₹\s*)?(\d{1,2})\.(\d{1,2})\s*(?:crores?|cr|lakhs?)?\s+to\s+(?:₹\s*)?(\d{1,2})\.(\d{1,2})\s*(crores?|cr|lakhs?)\b',
        _decimal_range_amount,
        text,
        flags=re.IGNORECASE,
    )

    # Single decimal crore/lakh (with or without ₹ prefix): "₹1.20 crore", "1.5 lakh"
    def _bare_decimal_amount(m: re.Match) -> str:
        unit_word = "crore" if m.group(3).lower() in ("crore", "crores", "cr") else "lakh"
        return _decimal_to_spoken(m.group(1), m.group(2)) + f" {unit_word}"
    text = re.sub(
        r'(?:₹\s*)?(\d{1,2})\.(\d{1,2})\s*(crores?|cr|lakhs?)\b',
        _bare_decimal_amount,
        text,
        flags=re.IGNORECASE,
    )

    # ── 5. Acronyms / abbreviations ──────────────────────────────────────
    # Handle plural forms first (EMIs, ULIPs) before the singular loop.
    _ACRONYM_PLURALS = {
        "EMIs":   "E M I S",
        "ULIPs":  "U L I P S",
        "SIPs":   "S I P S",
    }
    for abbr, spoken in _ACRONYM_PLURALS.items():
        text = re.sub(rf"\b{re.escape(abbr)}\b", spoken, text)

    _ACRONYMS = {
        "LIC":   "L I C",
        "HDFC":  "H D F C",
        "ICICI": "I C I C I",
        "SBI":   "S B I",
        "ULIP":  "U L I P",
        "IRDA":  "I R D A",
        "GST":   "G S T",
        "CI":    "C I",     # Critical Illness abbreviation
        "ADB":   "A D B",
        "ROP":   "R O P",
        "WOP":   "W O P",
        "PPT":   "P P T",
        "UIN":   "U I N",
        "EMI":   "E M I",
    }
    for abbr, spoken in _ACRONYMS.items():
        # Match the abbreviation as a whole word (not inside longer words)
        text = re.sub(rf"\b{re.escape(abbr)}\b", spoken, text)

    # ── 6. Product / brand name fixes ────────────────────────────────────
    # "Click To Protect" avoids the "2" being read as "do" in Hindi TTS context
    text = re.sub(r'Click\s*2\s*Protect', 'Click To Protect', text, flags=re.IGNORECASE)
    text = re.sub(r'COVID-19', 'COVID nineteen', text, flags=re.IGNORECASE)

    # ── 7. Tax section refs ───────────────────────────────────────────────
    text = re.sub(r'\b80C\b', 'eighty C', text)
    text = re.sub(r'\b10\(10D\)\b', 'ten ten D', text)

    # ── 7b. Numeric ranges — must run BEFORE age-hyphen patterns ─────────
    # "10-15 years" → "ten to fifteen years"
    # "10-15 साल" → "ten to fifteen saal" (Devanagari already normalised above)
    def _num_range(m: re.Match) -> str:
        lo, hi = int(m.group(1)), int(m.group(2))
        unit = m.group(3)
        lo_w = _int_to_words(lo) if lo < 100 else str(lo)
        hi_w = _int_to_words(hi) if hi < 100 else str(hi)
        return f"{lo_w} to {hi_w} {unit}"
    text = re.sub(
        r'\b(\d{1,3})-(\d{1,3})\s*(years?|months?|days?|saal|varsh)\b',
        _num_range,
        text,
        flags=re.IGNORECASE,
    )
    # Plain numeric range without unit: "10-15" by itself (e.g. "10-15 का" in Hindi)
    def _bare_num_range(m: re.Match) -> str:
        lo, hi = int(m.group(1)), int(m.group(2))
        lo_w = _int_to_words(lo) if lo < 100 else str(lo)
        hi_w = _int_to_words(hi) if hi < 100 else str(hi)
        return f"{lo_w} to {hi_w}"
    text = re.sub(r'\b(\d{1,3})-(\d{1,3})\b', _bare_num_range, text)

    # ── 8. Age hyphen patterns ────────────────────────────────────────────
    def _age_hyphen(m: re.Match) -> str:
        n = int(m.group(1))
        words = _int_to_words(n) if n < 100 else str(n)
        unit = m.group(2)
        old_suffix = " old" if m.group(3) else ""
        return f"{words} {unit}{old_suffix}"
    text = re.sub(r'\b(\d{1,2})-(year|month|day)(-old)?\b', _age_hyphen, text)

    # Age patterns: "29-year-old" → "twenty nine year old", "35-year" → "thirty five year"
    def _age_hyphen(m: re.Match) -> str:
        n = int(m.group(1))
        words = _int_to_words(n) if n < 100 else str(n)
        unit = m.group(2)
        old_suffix = " old" if m.group(3) else ""
        return f"{words} {unit}{old_suffix}"
    text = re.sub(r'\b(\d{1,2})-(year|month|day)(-old)?\b', _age_hyphen, text)

    # LPA (lakhs per annum): 50 LPA → fifty lakhs per annum
    def _lpa(m: re.Match) -> str:
        n = int(m.group(1))
        words = _int_to_words(n) if n < 100 else str(n)
        return f"{words} lakhs per annum"
    text = re.sub(r'\b(\d{1,3})\s*(?:LPA|lpa)\b', _lpa, text)

    # Rupee amounts: ₹22/day, ₹1 crore, ₹7,901, Rs. 50,000
    # Use a lookahead to ensure we add a space after if needed
    def _rupee_with_space(m: re.Match) -> str:
        spoken = _rupee_amount(m)
        # Add trailing space if original match consumed trailing space
        return spoken + " "
    text = re.sub(
        r'(?:₹|Rs\.?\s*)(\d[\d,]*(?:\.\d+)?)\s*(crore|lakh|lac|thousand|cr|k|l)?\s*(?:/\s*(?:day|month|year|annum|p\.?a\.?))?\s*',
        _rupee_with_space,
        text,
        flags=re.IGNORECASE,
    )
    # Clean up any double spaces introduced
    text = re.sub(r'  +', ' ', text).strip()

    # Percentages: 15% → fifteen percent, 100% → one hundred percent
    def _pct(m: re.Match) -> str:
        n = int(m.group(1))
        if n == 100:
            return "one hundred percent"
        return f"{_int_to_words(n) if n < 100 else n} percent"
    text = re.sub(r'\b(\d{1,3})%', _pct, text)

    # Plain Indian-format large numbers not caught above (e.g. "1,00,000")
    def _plain_num(m: re.Match) -> str:
        n = int(m.group(0).replace(",", ""))
        if n >= 10_000_000:
            return f"{n // 10_000_000} crore"
        elif n >= 100_000:
            return f"{n // 100_000} lakh"
        elif n >= 1000:
            t, r = divmod(n, 1000)
            return f"{t} thousand" + (f" {r}" if r else "")
        return m.group(0)
    text = re.sub(r'\b\d{1,2}(?:,\d{2}){2,}\b', _plain_num, text)

    return text.strip()

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
                pace=1.1,
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
            pace=1.3,
        )
    except TTSError:
        raise
    except Exception as exc:
        raise TTSError(str(exc)) from exc
