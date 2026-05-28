# Insurance Sales Voice Agent · Sarvam AI

A full-stack voice agent that pitches insurance products from uploaded PDFs,
powered entirely by the [Sarvam AI](https://sarvam.ai) platform.

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | `sarvam-m` (128 K context) via Sarvam chat completions |
| STT | `saaras:v3` · codemix mode (Hinglish) |
| TTS | `bulbul:v3` · streaming · en-IN / hi-IN / ta-IN / te-IN |
| Translation | `sarvam-translate:v1` via sarvamai SDK |
| Embeddings | OpenAI `text-embedding-3-small` |
| Vector store | FAISS (IndexFlatIP, cosine similarity) |
| PDF parsing | pdfplumber |
| Backend | FastAPI + uvicorn |
| Frontend | Single-page HTML/CSS/JS (zero build step) |

---

## Folder Structure

```
sarvam-insurance-agent/
├── backend/
│   ├── main.py        # FastAPI app — all API endpoints
│   ├── ingestion.py   # PDF → chunks → embeddings → FAISS
│   ├── rag.py         # FAISS retrieval (top-k cosine search)
│   ├── agent.py       # LLM logic — Pitch/Q&A modes, objections, summary
│   ├── stt.py         # saaras:v3 STT (codemix)
│   └── tts.py         # bulbul:v3 TTS (streaming, 4 languages)
├── frontend/
│   └── index.html     # Complete SPA
├── data/              # gitignored — PDFs + FAISS indexes
├── .env               # your secrets (gitignored)
├── .env.example
└── requirements.txt
```

---

## Quickstart

### 1 · Prerequisites

- Python 3.11+
- A [Sarvam AI API key](https://console.sarvam.ai)
- An [OpenAI API key](https://platform.openai.com) (embeddings only)

### 2 · Install

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3 · Configure

```bash
cp .env.example .env
# Fill in SARVAM_API_KEY and OPENAI_API_KEY in .env
```

### 4 · Run

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Then open **`http://localhost:8000`** … wait, serve the frontend separately or
add a static-files mount. For quick testing, open `frontend/index.html` directly
and set `const API = 'http://localhost:8000'` at the top of the `<script>` block.

Or serve everything from FastAPI (add to `main.py`):

```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="../frontend", html=True), name="static")
```

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `POST` | `/upload` | Ingest PDF → create session |
| `POST` | `/chat` | LLM+RAG turn (SSE stream or JSON) |
| `POST` | `/transcribe` | Audio → text via saaras:v3 |
| `GET` | `/speak` | Text → streaming WAV via bulbul:v3 |
| `POST` | `/summary` | End-of-session structured summary |
| `POST` | `/mode` | Switch pitch ↔ Q&A mid-session |
| `DELETE` | `/session/{id}` | Reset/end session |
| `GET` | `/docs` | Swagger UI |

---

## Core Features

1. **Upload any insurance PDF** — parsed, chunked (~1 000 chars), embedded into FAISS
2. **Pitch Mode** — agent proactively presents key benefits using RAG-retrieved excerpts
3. **Q&A Mode** — strict grounding: answers only from document; explicitly says when it can't
4. **Hinglish STT** — `saaras:v3` codemix handles natural Hindi-English speech
5. **Multilingual TTS** — streaming `bulbul:v3` audio in 4 Indian languages
6. **Objection handling** — LLM addresses concerns using document evidence
7. **Session summary** — structured recap of conversation at session end
8. **Zero-build frontend** — single HTML file, no npm/webpack needed

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `SARVAM_API_KEY` | Sarvam AI platform key (STT, TTS, LLM) |
| `OPENAI_API_KEY` | OpenAI key for `text-embedding-3-small` |
