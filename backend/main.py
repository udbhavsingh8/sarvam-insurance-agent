"""
main.py — FastAPI backend for the Insurance Sales Voice Agent.

Endpoints
---------
POST /upload            Ingest a PDF (text extraction, no embeddings)
GET  /status/{job_id}   Poll ingestion status
POST /chat              LLM turn (streaming SSE or plain JSON)
POST /transcribe        Audio bytes → transcript + detected language
GET  /speak             Text → streaming WAV audio (character voice)
POST /evaluate          Post-conversation evaluation report
DELETE /session/{id}    End and clean up a session
GET  /health            Liveness probe
"""

import asyncio
import json
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiofiles
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from agent import AgentSession          # noqa: E402
from evaluation import evaluate_session # noqa: E402
from ingestion import ingest            # noqa: E402
from pipeline import run_voice_pipeline # noqa: E402
from rag import DocumentStore           # noqa: E402
from stt import transcribe              # noqa: E402
from tts import SUPPORTED_LANGUAGES, synthesize_stream  # noqa: E402
from characters import CHARACTERS       # noqa: E402

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))

_sessions: dict[str, AgentSession] = {}
_jobs: dict[str, dict] = {}
_session_locks: dict[str, asyncio.Lock] = {}

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    os.makedirs(DATA_DIR, exist_ok=True)
    yield


app = FastAPI(title="Insurance Sales Voice Agent", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class _null_lock:
    """No-op async context manager for sessions that lack an explicit lock."""
    async def __aenter__(self) -> None:
        return None
    async def __aexit__(self, *_: object) -> None:
        return None


def _get_session(session_id: str) -> AgentSession:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return session


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def _run_ingestion(job_id: str, pdf_path: str, character_id: str) -> None:
    loop = asyncio.get_event_loop()
    try:
        page_count, index_name = await loop.run_in_executor(
            None, ingest, pdf_path, DATA_DIR
        )
        store = DocumentStore(DATA_DIR, index_name)
        session_id = str(uuid.uuid4())
        _sessions[session_id] = AgentSession(
            store=store,
            character_id=character_id,
            session_id=session_id,
        )
        _session_locks[session_id] = asyncio.Lock()
        _jobs[job_id] = {
            "status":      "done",
            "session_id":  session_id,
            "index_name":  index_name,
            "chunk_count": page_count,
            "character":   character_id,
        }
    except Exception as exc:
        _jobs[job_id] = {"status": "failed", "error": str(exc)}


@app.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    character: str = Form(default="arjun"),
) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    if character not in CHARACTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown character '{character}'. Choose from: {list(CHARACTERS.keys())}",
        )

    pdf_path = os.path.join(DATA_DIR, file.filename)
    raw = await file.read()
    async with aiofiles.open(pdf_path, "wb") as fh:
        await fh.write(raw)

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "ingesting"}
    asyncio.create_task(_run_ingestion(job_id, pdf_path, character))

    return JSONResponse({"job_id": job_id, "status": "ingesting"})


@app.get("/status/{job_id}")
async def job_status(job_id: str) -> JSONResponse:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JSONResponse(job)


@app.post("/chat", response_model=None)
async def chat(
    session_id: str = Form(...),
    message: str = Form(...),
    stream: bool = Form(default=False),
    stt_latency_ms: int = Form(default=0),
) -> StreamingResponse | JSONResponse:
    session = _get_session(session_id)
    lock = _session_locks.get(session_id)

    # Special opener token — generate a contextual opening line from the document
    if message.strip() == "__opener__":
        loop = asyncio.get_event_loop()
        opener_text = await loop.run_in_executor(None, session.generate_opener)
        return JSONResponse({"reply": opener_text, "language": session.language, "stage": "CONNECT"})

    if not message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty.")

    if stream:
        async def token_generator() -> AsyncIterator[str]:
            loop = asyncio.get_event_loop()
            queue: asyncio.Queue[str | Exception | None] = asyncio.Queue()
            t_start = time.time()

            def _produce() -> None:
                try:
                    for token in session.chat_stream(message):
                        queue.put_nowait(token)
                    queue.put_nowait(None)
                except Exception as exc:
                    queue.put_nowait(exc)

            ctx = lock if lock else _null_lock()
            async with ctx:
                loop.run_in_executor(None, _produce)

                llm_error = False
                error_detail: str | None = None
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        llm_error = True
                        error_detail = str(item)
                        yield f"data: [ERROR] {item}\n\n"
                        break
                    yield f"data: {item}\n\n"

                llm_ms = int((time.time() - t_start) * 1000)
                session.record_turn(
                    llm_ms=llm_ms,
                    stt_ms=stt_latency_ms,
                    llm_error=llm_error,
                    error_detail=error_detail,
                )
            yield "data: [DONE]\n\n"

        return StreamingResponse(token_generator(), media_type="text/event-stream")

    if lock:
        async with lock:
            loop = asyncio.get_event_loop()
            reply = await loop.run_in_executor(None, session.chat, message)
    else:
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, session.chat, message)

    return JSONResponse({
        "reply": reply,
        "language": session.language,
        "stage": session.memory.stage,
    })


@app.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    session_id: str = Form(default=""),
) -> JSONResponse:
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio file exceeds 10 MB limit.")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, transcribe, audio_bytes)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"STT error: {exc}") from exc

    # Propagate detected language to session if provided
    if session_id and session_id in _sessions:
        _sessions[session_id].update_language(
            result["language_code"], result["language_probability"]
        )

    return JSONResponse(result)


@app.get("/speak")
async def speak(
    text: str,
    session_id: str = "",
    language_code: str = "en-IN",
) -> StreamingResponse:
    if not text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty.")

    # Prefer session's detected language and character voice
    speaker: str | None = None
    if session_id and session_id in _sessions:
        sess = _sessions[session_id]
        language_code = sess.language
        speaker = sess.speaker

    if language_code not in SUPPORTED_LANGUAGES:
        language_code = "en-IN"

    async def audio_generator() -> AsyncIterator[bytes]:
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[bytes | Exception | None] = asyncio.Queue()

        def _produce() -> None:
            try:
                for chunk in synthesize_stream(text, language_code, speaker):
                    queue.put_nowait(chunk)
                queue.put_nowait(None)
            except Exception as exc:
                queue.put_nowait(exc)

        loop.run_in_executor(None, _produce)

        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    return StreamingResponse(audio_generator(), media_type="audio/wav")


@app.post("/evaluate")
async def evaluate(session_id: str = Form(...)) -> JSONResponse:
    session = _get_session(session_id)
    if not session.memory.turn_log:
        return JSONResponse({"evaluation": "No conversation to evaluate yet."})

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            evaluate_session,
            session.memory,
            session.character["name"],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Evaluation error: {exc}") from exc

    session.end_session()
    return JSONResponse(result)


@app.delete("/session/{session_id}")
async def delete_session(session_id: str) -> JSONResponse:
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    session = _sessions.pop(session_id)
    _session_locks.pop(session_id, None)
    session.end_session()
    return JSONResponse({"deleted": session_id})


@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        session_id = data.get("session_id", "")
        message = data.get("message", "").strip()
        stt_latency_ms = int(data.get("stt_latency_ms", 0))

        session = _sessions.get(session_id)
        if not session:
            await websocket.send_text('{"type":"error","message":"Session not found."}')
            return
        if not message:
            await websocket.send_text('{"type":"error","message":"Empty message."}')
            return

        lock = _session_locks.get(session_id)
        ctx = lock if lock else _null_lock()
        async with ctx:
            await run_voice_pipeline(websocket, session, message, stt_latency_ms)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_text(
                json.dumps({"type": "error", "message": str(exc)})
            )
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# Mount frontend LAST so API routes always take priority
_FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
