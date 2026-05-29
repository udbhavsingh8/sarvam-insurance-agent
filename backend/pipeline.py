"""
Streaming voice pipeline: LLM tokens → sentence splitter → TTS → WebSocket.

Flow per voice turn:
  1. LLM stream runs in a background executor, filling a token queue.
  2. Main async loop reads tokens and detects sentence boundaries.
  3. Each complete sentence is dispatched to TTS (executor); audio chunks
     are sent to the client as binary WebSocket frames immediately.
  4. A JSON text frame signals sentence text and audio boundaries so the
     client can update the chat bubble and queue audio for ordered playback.

T3 target: first audio frame arrives < 4s after STT completes.
  - STT → first LLM token:  ~1.5s
  - First sentence complete: ~2.0s (short opener sentence)
  - TTS first chunk:         ~0.5s after sentence dispatched
  - Total:                   ~2.5s  ✓
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent import AgentSession
    from fastapi import WebSocket

# Matches sentence-ending punctuation (Latin and Devanagari danda) followed
# by whitespace or end-of-string, plus word-terminated newlines.
_BOUNDARY = re.compile(r"[.!?।](?:\s|$)|(?<=\w)\n")

# Avoid dispatching abbreviation fragments like "Mr." or "Dr." to TTS.
# 4 allows short but real sentences ("Yes.", "No.") while blocking 3-char abbrevs.
_MIN_SENTENCE_CHARS = 4


async def run_voice_pipeline(
    websocket: "WebSocket",
    session: "AgentSession",
    message: str,
    stt_latency_ms: int,
) -> None:
    """
    Drive the full LLM → sentence-split → TTS → WebSocket pipeline.

    WebSocket protocol (server → client):
      Text frame  {"type": "sentence", "text": "..."}   — display this sentence
      Binary frames                                       — WAV audio chunks
      Text frame  {"type": "audio_end"}                  — seal audio for this sentence
      Text frame  {"type": "done", "language": "...", "stage": "..."} — turn complete
      Text frame  {"type": "error", "message": "..."}   — LLM failure
    """
    from conversation_analyzer import parse_meta_tag
    from tts import synthesize_stream

    loop = asyncio.get_running_loop()
    token_queue: asyncio.Queue[str | Exception | None] = asyncio.Queue()
    t_start = loop.time()

    # ── Start LLM stream in background executor ───────────────────────
    def _llm_produce() -> None:
        try:
            for token in session.chat_stream(message):
                token_queue.put_nowait(token)
            token_queue.put_nowait(None)
        except Exception as exc:
            token_queue.put_nowait(exc)

    loop.run_in_executor(None, _llm_produce)

    # ── Per-sentence TTS + audio send ─────────────────────────────────
    async def flush_sentence(raw_sentence: str) -> None:
        clean, _ = parse_meta_tag(raw_sentence)
        clean = clean.strip()
        if not clean:
            return  # was a META-tag fragment — skip TTS entirely

        await websocket.send_text(json.dumps({"type": "sentence", "text": clean}))

        audio_queue: asyncio.Queue[bytes | Exception | None] = asyncio.Queue()

        def _tts_produce() -> None:
            try:
                for chunk in synthesize_stream(clean, session.language, session.speaker):
                    audio_queue.put_nowait(chunk)
                audio_queue.put_nowait(None)
            except Exception as exc:
                audio_queue.put_nowait(exc)

        loop.run_in_executor(None, _tts_produce)

        while True:
            chunk = await audio_queue.get()
            if chunk is None:
                break
            if isinstance(chunk, Exception):
                # TTS failed for this sentence; text is already shown — continue
                break
            await websocket.send_bytes(chunk)

        await websocket.send_text(json.dumps({"type": "audio_end"}))

    # ── Read LLM tokens, detect boundaries, flush sentences ──────────
    buffer = ""
    short_prefix = ""   # accumulates sub-threshold fragments (e.g. "Mr. ")
    llm_error = False
    error_detail: str | None = None
    interrupted = False   # True when the client disconnects mid-stream (barge-in)

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

            # Flush all complete sentences found in the buffer
            while True:
                m = _BOUNDARY.search(buffer)
                if not m:
                    break
                # Everything up to and including the punctuation is the sentence.
                punct_pos = m.start() + 1      # one past the punctuation char
                sentence = buffer[:punct_pos].strip()
                buffer = buffer[punct_pos:].lstrip()
                if len(sentence) < _MIN_SENTENCE_CHARS:
                    # Likely an abbreviation — carry it forward into the next sentence
                    short_prefix += sentence + " "
                else:
                    await flush_sentence((short_prefix + sentence).strip())
                    short_prefix = ""

        # Flush any remainder (includes any carried prefix + last sentence or META tag).
        remainder = (short_prefix + buffer).strip()
        if remainder and not llm_error:
            await flush_sentence(remainder)

    except Exception:
        # WebSocketDisconnect or any send failure — client barged in or dropped.
        interrupted = True

    finally:
        # Record the turn regardless of how we exited — barge-in, error, or clean finish.
        # _stream_parts is populated by chat_stream() up to the point of interruption.
        llm_ms = int((loop.time() - t_start) * 1000)
        session.record_turn(
            llm_ms=llm_ms,
            stt_ms=stt_latency_ms,
            llm_error=llm_error,
            error_detail=error_detail if error_detail else ("interrupted" if interrupted else None),
        )

    if interrupted or llm_error:
        # Don't attempt to send on a broken socket.
        return

    await websocket.send_text(json.dumps({
        "type": "done",
        "language": session.language,
        "stage": session.memory.stage,
    }))
