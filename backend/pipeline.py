"""
Streaming voice pipeline: LLM tokens → sentence splitter → parallel TTS → single WAV → WebSocket.

Flow per voice turn:
  1. LLM stream runs in a background executor, filling a token queue.
  2. Main async loop reads tokens, detects sentence boundaries, and sends
     text frames immediately so the user sees the response progressively.
  3. Once all LLM text is collected, all sentences are TTS'd in parallel.
  4. The resulting WAV files are merged into one seamless blob and streamed
     to the client as a single continuous audio stream — one audio_end frame.

This eliminates the inter-sentence audio gap (brief silence when each WAV
header loaded separately) that caused perceived mid-sentence breaks.

Latency profile:
  - First text visible:  ~2s  (first LLM sentence)
  - Audio starts:        ~4s  (LLM done + parallel TTS ~1s)
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import wave
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent import AgentSession
    from fastapi import WebSocket

_BOUNDARY = re.compile(r"[.!?।](?:\s|$)|(?<=\w)\n")
_MIN_SENTENCE_CHARS = 4


def _merge_wav(wav_blobs: list[bytes]) -> bytes:
    """
    Merge a list of WAV byte strings into a single WAV file.
    Strips headers from blobs 2+ and re-writes one clean header.
    Uses Python stdlib wave module — no extra dependencies.
    """
    valid = [b for b in wav_blobs if b and len(b) > 44]
    if not valid:
        return b""
    if len(valid) == 1:
        return valid[0]

    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        for i, blob in enumerate(valid):
            try:
                with wave.open(io.BytesIO(blob), "rb") as inp:
                    if i == 0:
                        out.setparams(inp.getparams())
                    out.writeframes(inp.readframes(inp.getnframes()))
            except Exception:
                pass  # skip any malformed blob
    return buf.getvalue()


async def run_voice_pipeline(
    websocket: "WebSocket",
    session: "AgentSession",
    message: str,
    stt_latency_ms: int,
) -> None:
    """
    Drive the full LLM → text-display → parallel-TTS → merged-audio pipeline.

    WebSocket protocol (server → client):
      Text frame  {"type": "sentence", "text": "..."}   — display this sentence
      Binary frames                                       — merged WAV audio (one stream)
      Text frame  {"type": "audio_end"}                  — all audio sent
      Text frame  {"type": "done", "language": "...", "stage": "...", "profile": {...}}
      Text frame  {"type": "error", "message": "..."}   — LLM failure
    """
    from conversation_analyzer import parse_meta_tag
    from tts import normalize_for_tts, synthesize

    loop = asyncio.get_running_loop()
    token_queue: asyncio.Queue[str | Exception | None] = asyncio.Queue()
    t_start = loop.time()

    # ── Phase 1: stream LLM tokens ────────────────────────────────────────
    def _llm_produce() -> None:
        try:
            for token in session.chat_stream(message):
                token_queue.put_nowait(token)
            token_queue.put_nowait(None)
        except Exception as exc:
            token_queue.put_nowait(exc)

    loop.run_in_executor(None, _llm_produce)

    # Collect sentences while sending text frames immediately
    clean_sentences: list[str] = []   # clean text (META stripped) for TTS
    buffer = ""
    short_prefix = ""
    llm_error = False
    error_detail: str | None = None
    interrupted = False

    async def _emit_sentence(raw_sentence: str) -> None:
        """Strip META, send text frame, record sentence for TTS."""
        clean, _ = parse_meta_tag(raw_sentence)
        clean = clean.strip()
        if not clean:
            return
        await websocket.send_text(json.dumps({"type": "sentence", "text": clean}))
        clean_sentences.append(clean)

    try:
        while True:
            item = await token_queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                llm_error = True
                error_detail = str(item)
                break

            buffer += item

            while True:
                m = _BOUNDARY.search(buffer)
                if not m:
                    break
                punct_pos = m.start() + 1
                sentence = buffer[:punct_pos].strip()
                buffer = buffer[punct_pos:].lstrip()
                if len(sentence) < _MIN_SENTENCE_CHARS:
                    short_prefix += sentence + " "
                else:
                    await _emit_sentence((short_prefix + sentence).strip())
                    short_prefix = ""

        remainder = (short_prefix + buffer).strip()
        if remainder and not llm_error:
            await _emit_sentence(remainder)

    except Exception:
        interrupted = True

    finally:
        llm_ms = int((loop.time() - t_start) * 1000)
        session.record_turn(
            llm_ms=llm_ms,
            stt_ms=stt_latency_ms,
            llm_error=llm_error,
            error_detail=error_detail if error_detail else ("interrupted" if interrupted else None),
        )

    if interrupted:
        return

    if llm_error:
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "I'm having a connection issue right now. Could you try again?",
            }))
        except Exception:
            pass
        return

    # ── Phase 2: parallel TTS for all sentences ───────────────────────────
    async def _tts_one(text: str) -> bytes:
        tts_text = normalize_for_tts(text)
        if not tts_text.strip():
            return b""
        try:
            return await loop.run_in_executor(
                None, synthesize, tts_text, session.language, session.speaker
            )
        except Exception:
            return b""

    if clean_sentences:
        wav_blobs = await asyncio.gather(*[_tts_one(s) for s in clean_sentences])
        merged = _merge_wav(list(wav_blobs))

        if merged:
            _CHUNK = 8192
            for i in range(0, len(merged), _CHUNK):
                try:
                    await websocket.send_bytes(merged[i : i + _CHUNK])
                except Exception:
                    break

    try:
        await websocket.send_text(json.dumps({"type": "audio_end"}))
    except Exception:
        pass

    # ── Phase 3: done ─────────────────────────────────────────────────────
    p = session.memory.customer_profile
    try:
        await websocket.send_text(json.dumps({
            "type": "done",
            "language": session.language,
            "stage": session.memory.stage,
            "profile": {
                "fields": p.fields_collected,
                "age": p.age,
                "smoker": p.smoker,
                "income_range": p.income_range,
                "dependents": p.dependents,
                "marital_status": p.marital_status,
                "gender": p.gender,
            },
        }))
    except Exception:
        pass
