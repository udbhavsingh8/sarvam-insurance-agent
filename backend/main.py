"""
main.py — FastAPI backend for the Insurance Sales Voice Agent.

Endpoints
---------
POST /upload       Ingest a PDF → build FAISS index, returns session_id
POST /chat         LLM + RAG turn (streaming SSE or plain JSON)
POST /transcribe   Audio bytes → transcribed text via saaras:v3
GET  /speak        Text → streaming WAV audio via bulbul:v3
POST /summary      End-of-session structured summary
DELETE /session    Reset / end a session
GET  /health       Liveness probe

Session state is stored in-process (dict keyed by session_id).
For production, replace with Redis or a persistent store.
"""

import asyncio
import io
import os
import sys
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiofiles
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

load_dotenv()

# ── add backend/ to path so relative imports work when run with uvicorn ──
sys.path.insert(0, os.path.dirname(__file__))

from agent import AgentSession          # noqa: E402
from ingestion import ingest            # noqa: E402
from rag import RAGRetriever            # noqa: E402
from stt import transcribe              # noqa: E402
from tts import SUPPORTED_LANGUAGES, synthesize_stream  # noqa: E402

# ------------------------------------------------------------------ #
# Config
# ------------------------------------------------------------------ #

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DATA_DIR = os.path.abspath(DATA_DIR)

# In-process session store  { session_id: AgentSession }
_sessions: dict[str, AgentSession] = {}


# ------------------------------------------------------------------ #
# App
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    os.makedirs(DATA_DIR, exist_ok=True)
    yield


app = FastAPI(
    title="Insurance Sales Voice Agent",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _get_session(session_id: str) -> AgentSession:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return session


# ------------------------------------------------------------------ #
# Endpoints
# ------------------------------------------------------------------ #

@app.get("/health")
async def health() -> JSONResponse:
    """Liveness probe."""
    return JSONResponse({"status": "ok"})


@app.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    mode: str = Form(default="pitch"),
) -> JSONResponse:
    """
    Ingest a PDF and start a new agent session.

    Returns ``session_id`` and ``chunk_count``.
    Mode can be ``"pitch"`` (default) or ``"qa"``.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    if mode not in ("pitch", "qa"):
        raise HTTPException(status_code=400, detail="mode must be 'pitch' or 'qa'.")

    # Save upload to data/
    pdf_path = os.path.join(DATA_DIR, file.filename)
    raw = await file.read()
    async with aiofiles.open(pdf_path, "wb") as fh:
        await fh.write(raw)

    # Ingest (blocking CPU + network work) — run in thread pool
    loop = asyncio.get_event_loop()
    try:
        chunk_count, index_name = await loop.run_in_executor(
            None, ingest, pdf_path, DATA_DIR
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Create session
    retriever = RAGRetriever(DATA_DIR, index_name)
    session_id = str(uuid.uuid4())
    _sessions[session_id] = AgentSession(retriever=retriever, mode=mode)

    return JSONResponse(
        {
            "session_id": session_id,
            "index_name": index_name,
            "chunk_count": chunk_count,
            "mode": mode,
        }
    )


@app.post("/chat", response_model=None)
async def chat(
    session_id: str = Form(...),
    message: str = Form(...),
    stream: bool = Form(default=True),
    open_pitch: bool = Form(default=False),
) -> StreamingResponse | JSONResponse:
    """
    Send a user message and get the agent's reply.

    * ``stream=True``  (default) → SSE stream of text tokens
    * ``stream=False`` → JSON ``{ "reply": "..." }``
    * ``open_pitch=True`` → ignore *message*, let the agent open the pitch
    """
    session = _get_session(session_id)

    if open_pitch:
        # Run blocking LLM call in thread pool
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, session.open_pitch)
        return JSONResponse({"reply": reply})

    if not message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty.")

    if stream:
        async def token_generator() -> AsyncIterator[str]:
            loop = asyncio.get_event_loop()
            queue: asyncio.Queue[str | None] = asyncio.Queue()

            def _produce() -> None:
                try:
                    for token in session.chat_stream(message):
                        queue.put_nowait(token)
                finally:
                    queue.put_nowait(None)  # sentinel

            loop.run_in_executor(None, _produce)

            while True:
                token = await queue.get()
                if token is None:
                    break
                yield f"data: {token}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(token_generator(), media_type="text/event-stream")

    # Non-streaming path
    loop = asyncio.get_event_loop()
    reply = await loop.run_in_executor(None, session.chat, message)
    return JSONResponse({"reply": reply})


@app.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    language_code: str = Form(default="unknown"),
) -> JSONResponse:
    """
    Transcribe uploaded audio with saaras:v3 codemix.

    Accepts WebM / WAV / MP3 from the browser's MediaRecorder.
    Returns ``{ "transcript": "..." }``.
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file.")

    loop = asyncio.get_event_loop()
    try:
        text = await loop.run_in_executor(
            None, transcribe, audio_bytes, language_code
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"STT error: {exc}") from exc

    return JSONResponse({"transcript": text})


@app.get("/speak")
async def speak(
    text: str,
    language_code: str = "en-IN",
) -> StreamingResponse:
    """
    Convert *text* to speech with bulbul:v3 and stream WAV audio.

    Supported language codes: en-IN  hi-IN  ta-IN  te-IN
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty.")

    if language_code not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language '{language_code}'. "
                   f"Choose from: {SUPPORTED_LANGUAGES}",
        )

    async def audio_generator() -> AsyncIterator[bytes]:
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        def _produce() -> None:
            try:
                for chunk in synthesize_stream(text, language_code):
                    queue.put_nowait(chunk)
            finally:
                queue.put_nowait(None)

        loop.run_in_executor(None, _produce)

        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

    return StreamingResponse(audio_generator(), media_type="audio/wav")


@app.post("/summary")
async def summary(session_id: str = Form(...)) -> JSONResponse:
    """
    Generate a structured end-of-session summary.

    Returns ``{ "summary": "..." }``.
    """
    session = _get_session(session_id)
    if not session.history:
        return JSONResponse({"summary": "No conversation to summarize yet."})

    loop = asyncio.get_event_loop()
    try:
        text = await loop.run_in_executor(None, session.summarize)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}") from exc

    return JSONResponse({"summary": text})


@app.post("/mode")
async def set_mode(
    session_id: str = Form(...),
    mode: str = Form(...),
) -> JSONResponse:
    """Switch the agent between ``"pitch"`` and ``"qa"`` modes mid-session."""
    session = _get_session(session_id)
    try:
        session.set_mode(mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"session_id": session_id, "mode": mode})


@app.delete("/session/{session_id}")
async def delete_session(session_id: str) -> JSONResponse:
    """Reset and remove a session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    _sessions.pop(session_id)
    return JSONResponse({"deleted": session_id})


# ------------------------------------------------------------------ #
# Dev entrypoint
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
