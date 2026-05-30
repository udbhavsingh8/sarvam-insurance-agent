# PolicyAI — Full Project Handoff Document

> Generated 2026-05-30. This document is the single source of truth for the next
> Claude Code session. Read it completely before touching any code.

---

## READ THIS FIRST

Critical facts a new Claude session MUST know before proceeding:

1. **Sarvam-only constraint.** Every AI component (STT, TTS, LLM) uses Sarvam AI exclusively.
   Do not suggest or introduce OpenAI, Google, or any other provider.

2. **sarvam-m context window is 7192 tokens.** The system prompt is ~3600 tokens after all
   the char caps. max_tokens is set to 1800. Total must stay under 7192. If you expand prompts,
   recalculate. Budget: system prompt ≤ 3600t + history ≤ 390t + max_tokens 1800t = 5790t.

3. **sarvam-m always emits `<think>...</think>` before its response.** The streaming client
   buffers tokens until `</think>`, then yields content. If the think block consumes all
   max_tokens, `</think>` never appears → empty output → LLMError is raised.

4. **META tag mechanism is the stage machine.** The LLM appends `[META stage=X ...]` to each
   response. `parse_meta_tag()` strips it and `apply_analysis()` updates `SessionMemory`.
   If the LLM doesn't emit the tag (or emits the wrong stage), the stage machine doesn't advance.

5. **No vector database.** RAG is keyword scoring over paragraph chunks from the plain-text
   PDF. This is intentional for simplicity — don't add embeddings unless the user asks.

6. **The ingestion pipeline is synchronous + background.** PDF upload → text extraction →
   metadata extraction (LLM first, keyword fallback) → sales_brief generation → `.txt` +
   `.meta.json` + `.brief.txt` files saved to `data/`. DocumentStore reads these files.

7. **Two existing documents already ingested** in `data/`:
   - `HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure` (HDFC Life Click2Protect Life, term)
   - `max-life-stpp-axis-documents` (Axis Max Life Smart Term Plan Plus, term)

8. **Sales brief is capped at 1800 chars, document context at 800 chars** per call in
   `agent.py:_build_messages()`. If you add new prompts, these caps protect token budget.

9. **TTS normalization is in `tts.py:normalize_for_tts()`** — called in `pipeline.py`
   per sentence before TTS. Do not call TTS with raw LLM text (₹ symbols, hyphens, etc.
   cause garbled audio with bulbul:v3).

10. **Session state is in-process memory.** `_sessions` dict in `main.py`. No database,
    no persistence. Restart = all sessions lost.

11. **The frontend communicates via two paths:**
    - HTTP: `/upload`, `/status`, `/chat`, `/transcribe`, `/speak`, `/evaluate`
    - WebSocket: `/ws/chat` for the voice pipeline (streaming LLM → TTS → audio)

12. **Server start command:**
    ```
    lsof -ti:8000 | xargs kill -9 2>/dev/null; .venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
    ```
    Frontend is at http://localhost:8000 — it's served as StaticFiles from `frontend/`.

---

## 1. Project Overview

**PolicyAI** is an insurance sales voice agent that conducts full insurance sales conversations
in Indian languages. A user uploads an insurance product PDF; the agent reads it, builds a
product profile, and conducts a voice conversation as a named sales advisor (Arjun or Lalita).

**Business objective:** Automate insurance sales calls with a consultative, human-feeling voice
agent that can speak 10 Indian languages, collect customer profile information, explain plan
details, handle objections, and guide customers toward a purchase decision.

**End users:** Insurance companies or aggregators who want to automate outbound or inbound
insurance sales calls via a web interface.

**Key use cases:**
- Sales advisor calls to explain term/health/savings/ULIP plans
- Customer profiling (age, income, dependents, existing coverage)
- Product explanation (coverage, premiums, riders, tax benefits, exclusions)
- Objection handling (price, trust, timing, comparison, family)
- Closing and next-step guidance (quote, application walkthrough)

**Goal:** End-to-end voice conversation from greeting to close, ≤4s first audio latency,
across 10 Indian languages, using only Sarvam AI APIs.

---

## 2. Current Project Status

**Phase:** Production-ready v1. All core features implemented and committed.

### Completed
- Full voice pipeline: STT → LLM → sentence-split → TTS → WebSocket audio
- Sales stage machine: INTRODUCE → PROFILE → PERSONALIZE → EXPLAIN → HANDLE → CLOSE → QUESTION_ANSWER
- Two advisor characters: Arjun (male, energetic) and Lalita (female, empathetic)
- PDF ingestion: text extraction, keyword metadata extraction, LLM-assisted sales brief generation
- RAG: keyword-scored chunk retrieval from plain-text document
- Customer profile collection via META tags (age, gender, marital_status, dependents, smoker, existing_coverage, financial_goal, income_range)
- Lead scoring and buying intent tracking
- TTS pronunciation normalization (₹ amounts, LPA, age hyphens, percentages, plan names)
- Multi-language support: 10 Indian languages via sarvam-m + bulbul:v3
- Language detection with hysteresis (commit at ≥0.85 confidence, 2-consecutive at 0.7–0.84)
- Retry logic with exponential backoff for all Sarvam API calls
- Post-conversation evaluation (sarvam-m at temperature 0.3)
- Structured turn/session metrics logged to `logs/turns.jsonl` and `logs/sessions.jsonl`
- Barge-in: WebSocket disconnect mid-stream is handled gracefully

### Partially completed
- Behavior testing: one live conversation verified working (server.log shows opener + one user turn),
  but full stage progression (INTRODUCE→PROFILE→PERSONALIZE→EXPLAIN→CLOSE) not yet verified
  in a complete session

### Not started
- Persistent session storage (currently in-process memory only)
- Authentication / API keys for multi-tenant use
- Outbound call integration (currently web UI only)
- Analytics dashboard
- A/B testing between characters
- Fine-tuned intent classifier to replace META tag mechanism

**Progress: ~85%** (core feature-complete, needs behavioral verification and production hardening)

---

## 3. Architecture Overview

```
Browser (frontend/index.html)
    │
    ├─ HTTP POST /upload          → PDF → ingest() → .txt + .meta.json + .brief.txt
    ├─ HTTP GET  /status/{job_id} → poll ingestion completion
    ├─ HTTP POST /chat            → opener generation (__opener__) or JSON turn
    ├─ HTTP POST /transcribe      → audio bytes → saaras:v3 → transcript
    ├─ HTTP GET  /speak           → text → bulbul:v3 → streaming WAV
    └─ WebSocket /ws/chat         → voice pipeline (streaming LLM+TTS)
            │
            ▼
    FastAPI (backend/main.py)
            │
    ┌───────┴────────────────────────────────────────────────┐
    │  AgentSession (agent.py)                                │
    │    ├─ SessionMemory (memory.py)  — stage, profile, intel│
    │    ├─ LLMClient (llm.py)         — sarvam-m            │
    │    ├─ DocumentStore (rag.py)     — keyword RAG          │
    │    └─ character dict (characters.py)                    │
    │                                                         │
    │  run_voice_pipeline (pipeline.py)                       │
    │    ├─ LLM stream → sentence boundary detection          │
    │    ├─ normalize_for_tts() (tts.py)                      │
    │    └─ synthesize_stream() → binary WebSocket frames     │
    │                                                         │
    │  ingest (ingestion.py)                                  │
    │    ├─ pdfplumber text extraction                         │
    │    ├─ LLM metadata extraction (with keyword fallback)   │
    │    └─ sales_brief generation (rule-based template)      │
    └────────────────────────────────────────────────────────┘
            │
    Sarvam AI APIs
        ├─ saaras:v3  — STT (codemix, language auto-detect)
        ├─ sarvam-m   — LLM (7192 token context, emits <think> blocks)
        └─ bulbul:v3  — TTS (10 Indian languages, speaker-consistent)
```

**Architecture rationale:**
- No embeddings/vector DB: keeps ingestion fast (<5s) and removes infra dependency
- In-process session state: simplest possible for single-server deployment
- Sentence-split streaming pipeline: delivers first audio in ~2.5s (T3 target)
- META tag in LLM response: single LLM call per turn carries both response + analytics signals
- Keyword RAG fallback: if no keyword match, returns first 4 chunks (product overview)

---

## 4. Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| Language | Python 3.11+ | Backend |
| Web framework | FastAPI 0.115+ | HTTP + WebSocket API |
| ASGI server | Uvicorn | Production-grade async server |
| PDF parsing | pdfplumber 0.11+ | Text extraction from insurance PDFs |
| STT | Sarvam saaras:v3 | Speech-to-text, 10 Indian languages |
| LLM | Sarvam sarvam-m | Main conversation + analytics LLM |
| TTS | Sarvam bulbul:v3 | Text-to-speech, 22050Hz WAV |
| Sarvam SDK | sarvamai>=0.1.0 | Unified SDK for all Sarvam APIs |
| Frontend | Vanilla HTML/CSS/JS | Single-file UI, no build step |
| File I/O | aiofiles | Async PDF save |
| Env config | python-dotenv | Load .env file |
| HTTP client | httpx | Used transitively |

---

## 5. Repository Structure

```
/Users/ud/sarvam-insurance-agent/
├── .env                          # SARVAM_API_KEY=... (not committed)
├── .venv/                        # Python virtual environment
├── requirements.txt              # Python dependencies
├── README.md
├── HANDOFF.md                    # This file
│
├── backend/
│   ├── main.py                   # FastAPI app, all HTTP + WS endpoints
│   ├── agent.py                  # AgentSession — wires LLM, RAG, memory, chars
│   ├── pipeline.py               # Voice streaming pipeline (LLM → sentence → TTS → WS)
│   ├── llm.py                    # LLMClient — sarvam-m, streaming, think-block stripping
│   ├── stt.py                    # transcribe() — saaras:v3 codemix
│   ├── tts.py                    # synthesize/synthesize_stream + normalize_for_tts()
│   ├── memory.py                 # SessionMemory, CustomerProfile, CustomerIntelligence
│   ├── characters.py             # CHARACTERS dict (arjun, lalita) + SUPPORTED_LANGUAGES
│   ├── prompts.py                # All prompt templates: MAIN_SYSTEM_PROMPT, STAGE_INTENTS, etc.
│   ├── ingestion.py              # PDF → text + metadata + sales_brief
│   ├── rag.py                    # DocumentStore — keyword-scored chunk retrieval
│   ├── conversation_analyzer.py  # parse_meta_tag() + apply_analysis() + TurnAnalysis
│   ├── errors.py                 # STTError, LLMError, TTSError, retry_call()
│   ├── metrics.py                # TurnMetrics logging to logs/turns.jsonl
│   └── evaluation.py            # Post-session evaluation via sarvam-m
│
├── frontend/
│   └── index.html                # Complete single-file UI (HTML + CSS + JS)
│
├── data/                         # Ingested documents (created at runtime)
│   ├── *.pdf                     # Uploaded PDFs
│   ├── *.txt                     # Extracted plain text
│   ├── *.meta.json               # {plan_name, company_name, plan_type, one_line_pitch}
│   └── *.brief.txt               # Sales advisor product brief (~1800 chars)
│
└── logs/                         # Created at runtime
    ├── turns.jsonl               # Per-turn metrics
    └── sessions.jsonl            # Per-session summary
```

**Entry point:** `backend/main.py` — run with uvicorn.

**Environment variables required:**
- `SARVAM_API_KEY` — single key for all three Sarvam APIs (STT, LLM, TTS)

---

## 6. Implementation History

### Commit history (oldest → newest)

1. **`e1830c4` Initial scaffold** — basic project structure
2. **`11653a3` fix: truncate turn_log** — first context overflow fix (cap at 20 turns)
3. **`f1956ab` feat: advisor architecture, stage machine** — INTRODUCE/PROFILE/PERSONALIZE/EXPLAIN/CLOSE stages
4. **`479501b` feat: contextual opener** — generate_opener() uses document metadata
5. **`f81c5f7` feat: deep advisor persona redesign** — Arjun/Lalita characters with Indian context
6. **`9894b18` feat: sales-brief architecture** — advisor studies sales_brief before each call
7. **`a4beb01` feat: document-aware opener** — opener uses plan_name, company_name, one_line_pitch
8. **`3b7e393` / `8866772` fix: context overflow** — BRIEF_CHAR_LIMIT=1800, DOC_CONTEXT=800, max_tokens=1800
9. **`ad89da6` fix: stuck INTRODUCE stage** — rewrote INTRODUCE intent with explicit case-by-case transitions
10. **`4f460c3` feat: deep behavioral redesign** — 7-problem fix (consultative advisor, profile-anchored answers, colon fix, TTS normalization)

---

## 7. Design Decisions Log

### Decision: Sarvam-only APIs
**Reasoning:** Project requirement — user explicitly stated "only Sarvam AI".
**Alternatives rejected:** OpenAI GPT-4o, Google STT, ElevenLabs TTS — all rejected by constraint.
**Impact:** All AI code is in 3 files (llm.py, stt.py, tts.py) — easy to swap if constraint changes.

### Decision: META tag for analytics
**Reasoning:** Avoids a second LLM call per turn; sarvam-m produces structured data + response in one call.
**Alternatives considered:** Separate classifier call (parallel), rule-based heuristics.
**Rejected because:** Second call adds ~1.5s latency; heuristics are fragile for multilingual input.
**Risk:** LLM sometimes omits or malforms the tag. Mitigated by graceful handling in `parse_meta_tag()`.
**Designed for replacement:** `conversation_analyzer.py` has a narrow interface. Swap internals without changing callers.

### Decision: No vector embeddings / RAG
**Reasoning:** Speed of ingestion, zero infra dependencies, keyword matching sufficient for structured insurance docs.
**Alternatives rejected:** ChromaDB, FAISS, pgvector — all require setup and add latency.
**When to reconsider:** If documents are very long (>50 pages) or highly unstructured.

### Decision: sarvam-m over sarvam-105b
**Reasoning:** sarvam-105b has a ~17s thinking phase on starter tier → violates T3 (<4s) latency target.
**Alternative:** sarvam-105b with `thinking_budget` control — not yet available on starter tier.
**Implementation note:** `ACTIVE_CONFIG = SARVAM_M` in `llm.py`. One line change to switch.

### Decision: max_tokens=1800 for sarvam-m
**Reasoning:** sarvam-m context = 7192 tokens. System prompt ~3600t + history ~390t = ~3990t used.
Think block needs ~400-800t. Response needs ~300t. Total: ~5090t. 1800 max_tokens gives headroom.
**Risk:** If system prompt grows, this budget shrinks. BRIEF_CHAR_LIMIT and DOC_CONTEXT_CHAR_LIMIT are the guards.

### Decision: Sentence-split streaming pipeline
**Reasoning:** Bulbul:v3 rejects inputs >~500 chars. Splitting on sentence boundaries lets TTS
start while LLM is still generating → T3 latency of ~2.5s.
**Implementation:** `_BOUNDARY` regex in pipeline.py detects `.!?।` followed by whitespace.
Short fragments (<4 chars) are buffered to avoid abbreviation artifacts (e.g. "Mr.").

### Decision: Language hysteresis in SessionMemory.update_language()
**Reasoning:** Single-turn language detection can be noisy (especially code-mix). Two consecutive
detections at ≥0.7 confidence before committing prevents thrashing.
**Single-turn commit threshold:** ≥0.85 (high confidence → commit immediately).

---

## 8. AI / LLM Design Details

### Model: sarvam-m
- **Context window:** 7192 tokens
- **Think blocks:** Always emits `<think>...</think>` before content. Streaming client buffers
  until `</think>` then yields content. `_strip_think()` handles non-streaming.
- **Max tokens:** 1800 (keep system prompt ≤ 3600 chars / ~1565 tokens)
- **Temperature:** 0.7 (conversation), 0.3 (evaluation)
- **API call:** `client.chat.completions(messages=..., model="sarvam-m", ...)`

### Prompt architecture (MAIN_SYSTEM_PROMPT in prompts.py)

```
[Identity: character name + persona]
[Communication style: style_guide]
[Emotional handling: emotional_guide]
[Product knowledge: sales_brief (≤1800 chars)]
[Document reference: RAG context (≤800 chars)]
[Language instruction]
[Customer profile: collected fields so far]
[Memory summary: lead score, objections, positive signals]
[Current stage + EXPLAIN subtopic if applicable]
[Stage intent for current stage]
[VOICE_RULES: 2-3 sentences, no lists, no colons at end]
[ADVISOR_RULES: one question per turn, use profile, watch buying signals]
[DEFLECTION_PLAYBOOK: 4 objection responses]
[META_TAG_INSTRUCTION: exact format + transition table]
```

### Stage machine (via META tag)

```
INTRODUCE  → PROFILE        (customer agrees to overview / asks questions)
PROFILE    → PERSONALIZE    (4+ profile fields collected)
PERSONALIZE → EXPLAIN       (always, one-turn bridge)
EXPLAIN    → CLOSE          (all 8 subtopics done)
any        → QUESTION_ANSWER (customer asks a question)
any        → HANDLE         (objection raised)
HANDLE     → previous stage (after resolution)
QUESTION_ANSWER → return_to_stage (tracked in memory.return_to_stage)
```

EXPLAIN subtopics (in order, tracked by `memory.explain_subtopic_index` 0–7):
coverage, premiums, policy_term, death_benefit, maturity_benefit, riders, tax_benefits, exclusions.

### META tag format
```
[META stage=STAGE interest_delta=N objection=TYPE emotional_state=STATE
 close_readiness_delta=N customer_age=N customer_gender=X
 customer_marital_status=X customer_dependents=N customer_smoker=X
 customer_existing_coverage=X customer_financial_goal=X customer_income_range=X]
```

### Characters

**Arjun** (arjun): male, early 30s, eight years field experience, energetic, consultative,
recognises buying signals. Voice: `rahul` (bulbul:v3 speaker).

**Lalita** (lalita): female, early 40s, twelve years experience, patient, empathetic,
quiet closer — earns sale through trust. Voice: `ritu` (bulbul:v3 speaker).

### Opener generation
Separate LLM call with `OPENER_PROMPT` — produces a 3-4 sentence intro:
1. Introduce self by first name
2. State plan name + company name
3. Adapted one-line pitch
4. Ask if familiar or wants overview

Falls back to template string on LLM failure.

### History management
- `MAX_HISTORY_TURNS = 6` (last 12 messages: 6 user + 6 assistant)
- History from `memory.turn_log`, filtered to role ∈ {user, assistant}
- Current user turn appended as final message

---

## 9. Speech Pipeline Details

### STT: saaras:v3
- **Mode:** `codemix` — handles mixed Hindi-English (Hinglish) and all 10 languages
- **Language code:** Always `unknown` for auto-detection. Passing specific codes returns
  `None` for `language_probability` and causes downstream KeyError.
- **Output:** `{transcript, language_code, language_probability}`
- **Retry:** 3 attempts with 1s/2s/4s exponential backoff

### TTS: bulbul:v3
- **Sample rate:** 22050 Hz
- **Output:** WAV (via `output_audio_codec="wav"`)
- **Input limit:** ~500 chars — enforced by `_truncate_for_tts()` at 400 chars
- **Preprocessing:** `enable_preprocessing=True` (Sarvam-side normalization)
- **Custom normalization:** `normalize_for_tts()` in tts.py runs BEFORE the API call:
  - `₹50 lakh` → `fifty lakh rupees`
  - `₹22/day` → `twenty two rupees per day`
  - `29-year-old` → `twenty nine year old`
  - `50 LPA` → `fifty lakhs per annum`
  - `80C` → `eighty C`
  - `Click2Protect` → `Click 2 Protect`
  - `COVID-19` → `COVID nineteen`
  - `15%` → `fifteen percent`
  - `1,00,000` → `one lakh`

### Voice pipeline (pipeline.py: run_voice_pipeline)
1. LLM stream starts in background executor → fills `token_queue`
2. Main async loop reads tokens, accumulates in `buffer`
3. `_BOUNDARY` regex detects sentence end (`[.!?।]` + whitespace or `\n`)
4. Short fragments (<4 chars) buffered to next sentence (avoids "Mr." artifacts)
5. For each complete sentence: send `{"type":"sentence","text":"..."}` text frame
6. `normalize_for_tts(clean)` → TTS stream in background executor → `audio_queue`
7. Send binary WAV chunks as WebSocket binary frames
8. Send `{"type":"audio_end"}` text frame
9. After all sentences: send `{"type":"done","language":"...","stage":"..."}`
10. On LLM error: send `{"type":"error","message":"..."}` (never silent failure)
11. On WebSocket disconnect: `interrupted=True`, skip done frame, still call `record_turn()`

### Latency target (T3 < 4s)
- STT → first LLM token: ~1.5s
- First sentence complete: ~2.0s (short opener sentence)
- TTS first chunk: ~0.5s after sentence dispatched
- **Total: ~2.5s** ✓

---

## 10. APIs and Integrations

### POST /upload
- Accepts: multipart form — `file` (PDF), `character` (arjun|lalita)
- Creates background task via `asyncio.create_task(_run_ingestion(...))`
- Returns: `{job_id, status: "ingesting"}`
- PDF saved to `data/{filename}.pdf` before background task starts

### GET /status/{job_id}
- Returns: `{status: ingesting|done|failed, session_id?, index_name?, chunk_count?, character?}`
- Frontend polls this until `status == "done"` then stores `session_id`

### POST /chat
- Form fields: `session_id`, `message`, `stream` (bool), `stt_latency_ms`
- Special message `__opener__` → calls `session.generate_opener()`, returns JSON
- Normal turn: calls `session.chat()` (blocking) or `session.chat_stream()` (SSE)
- SSE format: `data: {token}\n\n` ... `data: [DONE]\n\n` (or `data: [ERROR] ...\n\n`)
- Returns: `{reply, language, stage}`

### POST /transcribe
- Accepts: multipart form — `audio` (webm), `session_id` (optional)
- Max audio: 10 MB
- Returns: `{transcript, language_code, language_probability}`
- If session_id provided: calls `session.update_language(...)` to propagate detection

### GET /speak
- Query params: `text`, `session_id` (optional), `language_code` (fallback)
- If session_id provided: uses session's detected language and character voice
- Returns: streaming WAV (`audio/wav`)

### WebSocket /ws/chat
- Client sends JSON: `{session_id, message, stt_latency_ms}`
- Server sends (in order):
  - `{"type":"sentence","text":"..."}` — display text
  - binary frames — WAV audio chunks
  - `{"type":"audio_end"}` — audio for this sentence complete
  - (repeat for each sentence)
  - `{"type":"done","language":"...","stage":"..."}` — turn complete
  - `{"type":"error","message":"..."}` — on LLM/WS failure

### POST /evaluate
- Form: `session_id`
- Runs `evaluate_session(memory, character_name)` via sarvam-m (temperature 0.3)
- Returns full evaluation text + numeric metrics
- Calls `session.end_session()` which logs session summary to `logs/sessions.jsonl`

### DELETE /session/{session_id}
- Removes session from `_sessions`, calls `end_session()`

---

## 11. Database & Data Model

**No database.** All state is in-process Python dicts.

### Session state (`_sessions: dict[str, AgentSession]`)
Each `AgentSession` contains:
- `SessionMemory` — full conversation state (see below)
- `LLMClient` — reused across turns
- `DocumentStore` — loaded once at session creation
- `character` dict — immutable character definition

### SessionMemory fields (memory.py)
```python
stage: str                    # Current stage (INTRODUCE|PROFILE|...)
previous_stage: str           # Last stage (for HANDLE return)
return_to_stage: str          # For QUESTION_ANSWER return
turn_in_stage: int
turn_count: int
detected_language: str        # BCP-47 (e.g. "hi-IN")
language_confidence: float
emotional_state: str          # curious|engaged|hesitant|resistant|anxious|satisfied
customer_profile: CustomerProfile
intelligence: CustomerIntelligence
explain_subtopic_index: int   # 0–7 (which EXPLAIN topic we're on)
questions_asked: list[str]    # User questions (last 3 shown in memory_summary)
features_explained: list[str]
turn_log: list[dict]          # {role, text, stage, turn} — full history
```

### CustomerProfile fields
age, gender, marital_status, dependents, smoker, existing_coverage, financial_goal, income_range.
All optional. `is_sufficient()` returns True when ≥4 of {age, gender, dependents, existing_coverage, financial_goal} are set.

### CustomerIntelligence fields
interest_level (0–100), buying_intent (cold|warm|hot), engagement_score (0–100),
close_readiness (0–100), objections (list of {text, category, turn, resolved}),
positive_signals (list[str]), hesitation_count, deflection_count.

`lead_score()` = 40% interest + 30% close_readiness + 15% objection resolution ratio + 15% positive signals.

### Document files (data/)
- `{name}.txt` — full extracted text (pdfplumber)
- `{name}.meta.json` — `{plan_name, company_name, plan_type, one_line_pitch}`
- `{name}.brief.txt` — sales advisor product brief (≤1800 chars, rule-based template)

### Logs (logs/)
- `turns.jsonl` — one record per LLM turn (session_id, turn_id, latencies, errors, stage)
- `sessions.jsonl` — one record per ended session (lead_score, intent, stages_visited, etc.)

---

## 12. Configuration & Environment Setup

### Required environment variables
```
SARVAM_API_KEY=<your key>
```

### Local setup
```bash
# 1. Navigate to project
cd /Users/ud/sarvam-insurance-agent

# 2. Install dependencies (if .venv doesn't exist)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Create .env file
echo "SARVAM_API_KEY=your_key_here" > .env

# 4. Start server
.venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# 5. Open browser
open http://localhost:8000
```

### Kill and restart server
```bash
lsof -ti:8000 | xargs kill -9 2>/dev/null; sleep 1
.venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
```

### Test TTS normalization
```bash
cd /Users/ud/sarvam-insurance-agent/backend
../.venv/bin/python3 -c "
from tts import normalize_for_tts
print(normalize_for_tts('₹50 lakh sum assured for 29-year-old non-smoker at 50 LPA'))
# Expected: 'fifty lakh rupees sum assured for twenty nine year old non-smoker at fifty lakhs per annum'
"
```

---

## 13. Bugs Encountered & Resolutions

### Bug 1: Context overflow (422 error from sarvam-m)
**Root cause:** System prompt was 6300+ tokens. With max_tokens=1024, total exceeded 7192.
**Symptom:** Agent stops responding after user message. Pipeline gets LLMError, no error frame sent.
**Fix:**
- Cap `sales_brief` at 1800 chars, `document_context` at 800 chars in `agent.py:_build_messages()`
- Set `max_tokens=1800`
- Send `{"type":"error"}` WebSocket frame on LLM failure (pipeline.py)
- Add non-retryable pattern "422" to `errors.py:_NON_RETRYABLE_PATTERNS`

### Bug 2: Think block truncation → empty responses
**Root cause:** sarvam-m think block consumed all max_tokens → `</think>` never appears.
**Symptoms:** Empty string after `_strip_think()`, or stream yields no content.
**Fix (three layers):**
- `_strip_think()`: raises `LLMError` if `<think>` without `</think>`
- `complete()`: raises `LLMError` if result is empty after stripping
- `stream()`: tracks `yielded_any` flag; raises `LLMError` if stream ends with no yielded content
- `agent.chat()`: if `clean.strip()` is empty and no LLMError, sets fallback + marks error

### Bug 3: INTRODUCE stage not advancing to PROFILE
**Root cause:** Stage intent said "End EVERY response in this stage with: 'Can I ask you a couple of quick questions?'" — model copied this into PROFILE responses, stayed stuck.
**Fix:** Rewrote INTRODUCE intent with two explicit cases:
- IF customer asked for overview: give 2-sentence overview, end with permission question, set stage=PROFILE
- IF customer said yes/sure: skip overview, ask first profiling question directly, set stage=PROFILE
- Never repeat the permission question.

### Bug 4: "This plan from the insurer" opener
**Root cause:** LLM metadata extraction failed (no API key in shell), fell through to default values.
**Fix:** Added `_extract_metadata_from_text()` — keyword-based extractor detecting 17 Indian insurers,
plan names from "Introducing X" pattern, plan type from keywords. Used as fallback when LLM fails.
HDFC Life `.meta.json` now has `{"plan_name": "Click2Protect Life", "company_name": "HDFC Life", ...}`.

### Bug 5: "Based on your profile, here's how it works:" then nothing
**Root cause:** Model generates preamble ending with colon, think block exhausts tokens before completing explanation.
**Fix:** Added colon prohibition:
- `VOICE_RULES`: "Never end a sentence with a colon (:) — always complete the thought"
- Character style guides: "Never start a sentence that ends with a colon — complete your thought"
- `PERSONALIZE` intent: "CRITICAL: Do NOT end any sentence with a colon"

### Bug 6: PERSONALIZE producing only META tag (0 chars response)
**Root cause:** Model only output `[META ...]` with no spoken text. `parse_meta_tag()` returned empty string.
**Fix:** In `agent.chat()`: `if not clean.strip() and not llm_error: clean = _FALLBACK; llm_error = True`

### Bug 7: TTS mispronouncing "29-year-old", "₹22/day", "50 LPA"
**Root cause:** bulbul:v3 receives raw LLM text with special characters and Indian number notation.
**Fix:** Added `normalize_for_tts()` in `tts.py`, called in `pipeline.py:flush_sentence()` before TTS.

### Bug 8: Opener returning `stage: "CONNECT"` instead of `stage: "INTRODUCE"`
**Root cause:** Old code used "CONNECT" as initial stage name, main.py still returned it.
**Fix:** `main.py` opener handler returns `stage: "INTRODUCE"` (current stage name).

---

## 14. Known Issues & Technical Debt

### Open issues
1. **EXPLAIN subtopic index advance logic is approximate.** `apply_analysis()` advances
   `explain_subtopic_index` whenever `analysis.stage == "EXPLAIN"` and `memory.stage == "EXPLAIN"`.
   This means each turn in EXPLAIN advances the subtopic, not each explicit LLM topic change.

2. **No rate limiting.** Multiple concurrent users can exhaust Sarvam API rate limits.

3. **Session cleanup.** Sessions are never cleaned up unless `DELETE /session/{id}` is called
   or `/evaluate` is called. Long-running server will accumulate sessions in memory.

4. **Audio format assumption.** `POST /transcribe` hardcodes `audio/webm` MIME type.
   Safari sends `audio/mp4` — may fail on iOS/macOS Safari.

5. **META tag sometimes malformed.** sarvam-m occasionally emits `customer_age=empty`
   instead of omitting the field. Currently handled by `_opt_int/str/bool()` returning None.

6. **Lead score doesn't auto-trigger CLOSE.** Lead score ≥70 shows hint in memory_summary
   but LLM must choose to transition. EXPLAIN can continue past optimal close moment.

### Technical debt
- META tag mechanism is designed for replacement (see `conversation_analyzer.py` comments)
- No unit tests for `normalize_for_tts()`, `parse_meta_tag()`, or `apply_analysis()`
- `direct_test.py` and `run_tests.py` in root are uncommitted test scripts

---

## 15. Performance Analysis

### Latency targets (T3 = time to first audio after user speaks)
- **Target:** < 4 seconds
- **Measured (typical):** ~2.5–3.0s
  - STT (saaras:v3): ~0.8–1.5s
  - First LLM token: ~0.3–0.5s
  - First sentence complete: ~1.5–2.0s total
  - TTS first chunk: ~0.4–0.6s after sentence dispatched

### Optimizations implemented
- Sentence-split streaming: TTS starts while LLM still generating (saves ~1s)
- History capped at 6 turns: reduces prompt token count
- Brief + context caps: prevent token budget overruns that cause retries

---

## 16. Security Considerations

### Implemented
- `MAX_AUDIO_BYTES = 10MB` limit on STT upload
- PDF-only validation for /upload endpoint
- Character ID validation

### Not implemented (production concerns)
- API key authentication (any client can call all endpoints)
- Rate limiting
- Input sanitization (user text goes directly to LLM — prompt injection possible)
- HTTPS
- Session expiry

---

## 17. Testing Status

### Tested (manually)
- Opener generation with HDFC Life PDF ✓
- TTS normalization (all 9 patterns) ✓
- One voice session: opener → INTRODUCE → one user response ✓
- LLM error fallback (sends error frame) ✓
- Think-block truncation handling ✓

### Not yet tested
- Full INTRODUCE → PROFILE → PERSONALIZE → EXPLAIN → CLOSE progression
- Hindi/Tamil/other language detection and conversation
- Objection handling (HANDLE stage)
- QUESTION_ANSWER stage using collected profile
- CLOSE stage producing next-step suggestions
- Post-session evaluation endpoint
- Lalita character
- Multi-user concurrent sessions
- Barge-in mid-sentence
- Axis Max Life document

---

## 18. Current Working State

### What works
- Server starts, serves frontend at http://localhost:8000
- PDF upload and ingestion (HDFC Life, Axis Max Life verified)
- Opener generation: "Hi, I'm Arjun. I'm here to talk to you about Click2Protect Life from HDFC Life..."
- WebSocket voice pipeline: LLM stream → sentence split → TTS → binary audio frames
- Stage machine mechanics (META tag parsing, apply_analysis, memory updates)
- TTS normalization (verified via unit test)
- LLM error fallback (sends error frame to client)
- Language detection with hysteresis
- Session metrics logging

### What needs verification
- Whether the 7-problem behavioral redesign (commit 4f460c3) produces correct conversation flow
  end-to-end. The last server log shows the opener and one user turn worked but the session
  ended before we could see PROFILE/PERSONALIZE/EXPLAIN/CLOSE.

---

## 19. Phase-wise Roadmap

### Phase 1 — Core voice pipeline ✅
STT + LLM + TTS + WebSocket pipeline, single character, English only

### Phase 2 — Reliability ✅
Retry logic, error handling, context overflow fix, empty response fallback

### Phase 3 — Language ✅
10-language support, language detection with hysteresis

### Phase 4 — Streaming + barge-in ✅
Sentence-split streaming, T3 < 4s, barge-in via WebSocket disconnect

### Phase 5 — Sales stage machine ✅
INTRODUCE→PROFILE→PERSONALIZE→EXPLAIN→HANDLE→CLOSE→QUESTION_ANSWER, META tag mechanism

### Phase 6 — Behavioral quality ✅
Deep behavioral redesign: consultative persona, profile-anchored answers, colon fix, TTS normalization

### Phase 7 — Verification (CURRENT)
End-to-end conversation testing across all stages

### Phase 8 — Production hardening
Auth, rate limiting, session expiry, HTTPS, multi-tenant support

### Phase 9 — Analytics
Real-time dashboard, A/B testing, conversion funnel tracking

### Phase 10 — Outbound call integration
Phone/SIP integration, scheduled call campaigns

---

## 20. Immediate Next Steps

### Priority 1: End-to-end conversation verification
Run a complete test session with the HDFC Life document. Verify each stage transition:

1. **Opener:** "Hi, I'm Arjun from HDFC Life. I'm here to talk about Click2Protect Life..."
2. **User:** "Tell me more" → **INTRODUCE** gives 2-sentence overview, asks permission, sets META stage=PROFILE
3. **User:** "Sure" → **PROFILE** asks age+smoker first (not random)
4. **User:** "I'm 29, non-smoker" → **PROFILE** briefly acknowledges, asks about family
5. (Continue through 4+ profile fields)
6. **PERSONALIZE** says "You are 29, non-smoker, married with [X]..." — uses actual age/profile
7. **EXPLAIN** starts with coverage topic anchored to customer profile
8. **QUESTION_ANSWER** (if user asks a question): answers using "at 29, non-smoker..."
9. **CLOSE:** "Based on what you've shared — 29, non-smoker, married — this plan gives your family ₹X crore. Would you like a personalised quote?"

If any stage misbehaves, check `prompts.py:STAGE_INTENTS` for that stage and adjust.

### Priority 2: Fix any issues found
Common failure modes:
- Stage not advancing: check META tag in raw LLM output (add debug print in pipeline.py temporarily)
- Generic answers: check `customer_profile.summary()` is populated and appears in system prompt
- Colon-ending sentences: check VOICE_RULES and character style_guide in characters.py

### Priority 3: Test Hindi
Say "mujhe Hindi mein batao" → verify language switches and response is in Hindi.

---

## START HERE IN NEW SESSION

```
You are continuing development of PolicyAI — an Insurance Sales Voice Agent.
Project root: /Users/ud/sarvam-insurance-agent

## What this project does

A voice agent that conducts insurance sales conversations in 10 Indian languages.
Users upload an insurance PDF → the agent reads it and conducts a voice call as a named
sales advisor (Arjun or Lalita). The agent collects customer profile, explains the plan,
handles objections, and guides toward purchase.

CRITICAL CONSTRAINT: All AI uses ONLY Sarvam AI APIs:
- STT: saaras:v3 (codemix, language_code="unknown" always)
- LLM: sarvam-m (7192 token context, always emits <think>...</think> before content)
- TTS: bulbul:v3 (22050Hz WAV, 10 Indian languages)

## Architecture (10-second version)

FastAPI backend (backend/main.py):
- POST /upload → ingest PDF → creates AgentSession with DocumentStore
- WebSocket /ws/chat → run_voice_pipeline() → LLM stream → sentence split → TTS → binary audio
- POST /chat → JSON turns (non-voice)
- GET /speak → text → bulbul:v3 → streaming WAV
- StaticFiles → frontend/index.html

Key modules:
- agent.py: AgentSession.chat_stream() + record_turn()
- pipeline.py: run_voice_pipeline() → sentence boundary → normalize_for_tts() → synthesize_stream()
- llm.py: LLMClient.stream() buffers until </think> then yields content
- memory.py: SessionMemory with stage machine, CustomerProfile, CustomerIntelligence
- prompts.py: MAIN_SYSTEM_PROMPT, STAGE_INTENTS (INTRODUCE/PROFILE/PERSONALIZE/EXPLAIN/HANDLE/CLOSE/QA)
- conversation_analyzer.py: parse_meta_tag() strips [META...] tag from LLM output, apply_analysis() updates memory
- tts.py: normalize_for_tts() converts ₹/LPA/hyphens/% to spoken form BEFORE bulbul:v3

## Token budget (DO NOT EXCEED)
sarvam-m context = 7192 tokens. Current budget:
- System prompt: ~3600 tokens (controlled by BRIEF_CHAR_LIMIT=1800 + DOC_CONTEXT=800 in agent.py)
- History: ~390 tokens (MAX_HISTORY_TURNS=6 in agent.py)
- max_tokens: 1800 (in llm.py)
- Total: ~5790 tokens (headroom: ~1400 for think block)

## Current state

All code committed. Last commit: 4f460c3 "feat: deep behavioral redesign"
Server runs on port 8000. Start with:
  lsof -ti:8000 | xargs kill -9 2>/dev/null; .venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &

Two documents pre-ingested in data/:
- HDFC Life Click2Protect Life (term plan)
- Axis Max Life Smart Term Plan Plus (term plan)

## What needs to happen now

Run a complete conversation to verify the behavioral redesign works:
INTRODUCE → PROFILE → PERSONALIZE → EXPLAIN → (optionally HANDLE) → CLOSE

Watch for:
1. Opener says "Click2Protect Life" and "HDFC Life" (not generic)
2. PROFILE asks age+smoker first, then family, then existing coverage
3. PERSONALIZE uses actual collected profile ("You are 29, non-smoker...")
4. EXPLAIN is anchored to customer profile (not generic "for a 25-year-old")
5. CLOSE suggests "Would you like a personalised quote?" or similar next step

Fix anything broken by adjusting backend/prompts.py STAGE_INTENTS for that stage.
Read HANDOFF.md for full technical context before making any changes.
```
