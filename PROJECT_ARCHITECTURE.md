# COMPLETE TECHNICAL ARCHITECTURE AND SYSTEM WALKTHROUGH
**PolicyAI — Insurance Sales Voice Agent**
*Audience: CTO, Architect, Senior Engineer, Technical Reviewer*

---

## 1. System Overview

PolicyAI is a real-time, voice-first AI insurance sales agent. A manager uploads an insurance product PDF; the system ingests it; a customer can then have a personalised sales conversation with the AI agent over voice or text, in any of 10 Indian languages.

The system has two runtime modes:
- **Voice mode**: Customer speaks → Sarvam STT → LLM → Sarvam TTS → audio playback
- **Text mode**: Customer types → LLM → Sarvam TTS → audio playback (or browser TTS fallback)

All sales intelligence is deterministic Python — no financial numbers are LLM-generated.

---

## 2. Business Workflow

```
MANAGER WORKFLOW
─────────────────
1. Manager opens http://localhost:8000
2. Uploads insurance product PDF (e.g., HDFC Click2Protect Life brochure)
3. System ingests PDF → 5 output files (text, metadata, brief, structure, BM25 chunks)
4. Session created → session_id returned to frontend
5. Customer can now start conversation

CUSTOMER WORKFLOW
─────────────────
1. Customer clicks "Start Session"
2. Agent delivers opener (deterministic, no LLM)
3. Customer speaks or types
4. Agent responds with voice + text (via WebSocket streaming pipeline)
5. Conversation progresses through sales stages
6. Agent closes with onboarding handoff or feedback collection
7. Manager can request evaluation report
```

---

## 3. User Journey

```
STEP 1: Upload
Customer opens UI → sees welcome screen → manager has uploaded PDF →
"Start Session" enabled → customer clicks it

STEP 2: Session Start
AgentSession created in memory → /chat called with "__opener__" →
generate_opener() returns deterministic greeting → TTS spoken → chat window opens

STEP 3: INTRODUCE Stage
Agent: "Hi, I'm Arjun from PolicyAI. I've gone through the [plan name] policy document..."
Customer: "Yes, tell me about it" or "I don't know this plan"

STEP 4: PROFILE Stage (Python advances after 2 INTRODUCE turns)
Agent collects in natural conversation: age → smoker status → income → family situation → existing coverage
Max 2 questions per turn. Only missing fields asked.
Python advances to NEED_DEVELOPMENT when is_sufficient() == True.

STEP 5: NEED_DEVELOPMENT Stage
Agent: "If something unexpected happened and you couldn't work for a year, how would your family manage financially?"
Customer articulates vulnerability.
Python advances to EXPLAIN after 2 turns.

STEP 6: EXPLAIN Stage
Agent explains 4 plan topics (chosen by plan_type + customer profile):
  Term plan example: coverage_and_sum_assured → premium_and_daily_cost → death_benefit_and_payout → key_exclusions
Each explanation: connects to customer's risk narrative → plan benefit → calculated numbers → check-in question.
Python advances to RECOMMENDATION when close_readiness ≥ 70 and ≥ 2 EXPLAIN turns.

STEP 7: RECOMMENDATION Stage
Agent: "Given that [specific customer risk], this plan ensures [specific outcome].
For your profile, this works out to [calculated premium]. I genuinely think this plan makes sense for you.
Would you like to take this forward?"
Python advances to CLOSE after 1 turn.

STEP 8: CLOSE Stage
PURCHASE_INTENT → customer says yes → PROCEED → agent delivers handoff message
                → customer says no → FEEDBACK → agent collects decline reason → CLOSED

STEP 9: Evaluation (optional)
Manager clicks "Evaluate Session" → /evaluate called → LLM generates coaching report
```

---

## 4. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          BROWSER                                │
│  frontend/index.html                                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐   │
│  │ File DnD │  │ Mic API  │  │ WebSocket│  │ Audio Player│   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘   │
└───────┼─────────────┼─────────────┼───────────────┼──────────┘
        │ HTTP POST   │ Audio webm  │ WS frames     │ WAV bytes
        ▼             ▼             │               │
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend (main.py)                   │
│                                                                 │
│  POST /upload      POST /transcribe    WS /ws/chat             │
│  GET  /status      GET  /speak         POST /chat              │
│  POST /evaluate    GET  /transcript    DELETE /session          │
│  GET  /health                                                   │
└──┬──────────────┬──────────────┬─────────────────┬─────────────┘
   │              │              │                 │
   ▼              ▼              ▼                 ▼
┌──────┐    ┌──────────┐  ┌──────────────┐  ┌──────────────┐
│ingest│    │  stt.py  │  │  pipeline.py │  │    tts.py    │
│ion.py│    │saaras:v3 │  │  (voice ws)  │  │ bulbul:v3    │
└──┬───┘    └──────────┘  └──────┬───────┘  └──────────────┘
   │                             │
   │                             ▼
   │                    ┌─────────────────────┐
   │                    │   AgentSession       │
   │                    │   (agent.py)         │
   │                    └────────┬────────────┘
   │                             │
   ├────────────────┬────────────┼────────────────┬────────────┐
   ▼                ▼            ▼                 ▼            ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────┐
│DocumentS │ │SessionMe │ │  LLMClient   │ │cover_eng │ │quote_eng │
│tore (rag)│ │mory      │ │ (llm.py)     │ │ine.py    │ │ine.py    │
│BM25Store │ │(memory.py│ │ gpt-4o-mini  │ │          │ │          │
└──────────┘ └──────────┘ └──────────────┘ └──────────┘ └──────────┘

EXTERNAL SERVICES:
  Sarvam AI  →  saaras:v3 (STT), bulbul:v3 (TTS)
  OpenAI     →  gpt-4o-mini (LLM, ingestion, evaluation)
```

---

## 5. Component Architecture

### backend/main.py — FastAPI Application
- Entry point. Defines all HTTP + WebSocket endpoints.
- Manages `_sessions: dict[str, AgentSession]` and `_session_locks: dict[str, asyncio.Lock]`
- Runs ingestion in background executor via `asyncio.create_task(_run_ingestion(...))`
- Mounts `/frontend` as static files LAST (after API routes)
- Session concurrency: per-session `asyncio.Lock` prevents concurrent LLM calls

### backend/agent.py — AgentSession (Core Controller)
- Owns the session lifecycle
- `generate_opener()` — deterministic, no LLM
- `chat(user_text)` — synchronous, returns complete response
- `chat_stream(user_text)` — generator, yields tokens
- `record_turn(...)` — called after streaming to update memory
- `_build_messages(user_text)` — assembles the full LLM message list (system prompt + history + current turn)
- `_auto_advance_stage(memory, plan_type)` — Python-gated stage transitions
- `build_risk_narrative(profile)` — deterministic vulnerability story
- `detect_language_from_text(text)` — Unicode script range detection

### backend/pipeline.py — Streaming Voice Pipeline
- `run_voice_pipeline(websocket, session, message, stt_latency_ms)` — WebSocket handler
- Phase 1: Streams LLM tokens into sentence queue; sends `{type:"sentence"}` frames immediately
- Phase 2: `asyncio.gather()` all sentences for parallel TTS
- Phase 3: `_merge_wav()` combines WAV blobs; sends binary frames + `{type:"audio_end"}`
- Phase 4: Sends `{type:"done", language, stage, profile}`

### backend/memory.py — Session State
- `CustomerProfile` dataclass — 13 fields
- `CustomerIntelligence` dataclass — interest_level, close_readiness, objections, lead_score()
- `SessionMemory` dataclass — all session state
- `choose_explain_topics(plan_type, profile)` — dynamic topic selection

### backend/prompts.py — All Prompt Templates
- `VOICE_RULES`, `ADVISOR_RULES`, `DEFLECTION_PLAYBOOK` — formatting and behaviour constants
- `OPENER_PROMPT` — not used (generate_opener() is now deterministic)
- `STAGE_INTENTS: dict[str, str]` — 8 stage intent guides
- `CLOSE_SUBSTAGE_INTENTS: dict[str, str]` — 5 close substage intents
- `META_TAG_INSTRUCTION` — instructs LLM to emit [META ...] tag
- `MAIN_SYSTEM_PROMPT` — master template (~30 placeholders, assembled every turn)
- `EVALUATION_PROMPT` — post-conversation coaching report

### backend/conversation_analyzer.py — Meta Tag Parser + Analysis
- `parse_meta_tag(text)` → `(clean_text, TurnAnalysis | None)` — strips [META ...] tag, returns analysis
- `apply_analysis(memory, analysis, user_text)` — applies stage transitions, interest/objection updates
- Contains all stage transition gates (I-9, PROFILE→PERSONALIZE gate, NEED_DEV→EXPLAIN blocking)

### backend/profile_extractor.py — Deterministic Profile Extraction
- `extract_profile_fields(text) → dict` — runs before every LLM call
- 10 extractors: age, smoker, income, dependents, marital_status, gender, policy_term, payment_frequency, liabilities_lakh, cover_amount_override_lakh
- All regex-based, no LLM

### backend/recommendation.py — Benchmark Premium Estimates
- `build_recommendation_block(profile, plan_meta, brief_text) → str`
- Industry-standard actuarial constants for term insurance
- Income × multiplier (10/15/20x) for cover
- Premium: ₹8,500/crore base × age factor × smoker factor
- Returns empty string if profile insufficient; suppresses premium if smoker=None

### backend/cover_engine.py — Cover Amount Calculator
- `recommend_cover(profile) → CoverRecommendation | None`
- Income × multiplier + liabilities - existing_coverage
- Multipliers: 20x (dependents + income < 10 LPA), 15x (dependents), 10x (no dependents)
- Consumed by quote_engine.py

### backend/quote_engine.py — Document-Derived Premium Calculator
- `generate_quote(profile, cover_lakh, structure) → Quote`
- Reads premium_tables from structure.json
- `_interpolate()` — exact match → age interpolation → nearest term → single row fallback
- Applies GST 18%, 4 payment frequency breakdowns
- `quote_to_prompt_block(quote, payment_frequency) → str` — formatted for LLM injection

### backend/ingestion.py — PDF Processing Pipeline
- `ingest(pdf_path, index_dir) → (page_count, name)` — main entry point
- Produces 5 output files: .txt, .meta.json, .brief.txt, .structure.json, .chunks.json
- `_extract_metadata()` → GPT-4o-mini extracts plan_name, company_name, plan_type, one_line_pitch
- `_generate_brief_via_llm()` → GPT-4o-mini generates 9-section advisor cheat-sheet
- `_extract_section()` → keyword-based section extraction for brief fallback
- `_profiling_questions_for_type()` → per-plan-type question sequences (reference only)

### backend/rag.py — Document Store + Retrieval
- `DocumentStore(index_dir, name)` — loads text, metadata, brief, BM25 store, structure
- `get_context(query, top_k=3)` → BM25 retrieval or keyword fallback
- Instantiated once per session; holds all document data for the session's lifetime

### backend/bm25_store.py — BM25 Retrieval
- `BM25Store.build(text)` → builds section-aware chunks + BM25Okapi index
- `BM25Store.save(path)` / `BM25Store.load(path)` → JSON serialisation
- `retrieve(query, top_k) → str` → BM25 scores, falls back to first N chunks on zero scores
- Section header detection: 30+ insurance document section keywords

### backend/table_parser.py — Premium Table Extractor
- `parse_tables(pages_data) → list[dict]` — deterministic, no LLM
- Scores each pdfplumber table as premium table (0-1 score, threshold 0.35)
- Format A: age rows × term columns (most common)
- Format B: term rows × age columns
- Detects smoker/non-smoker column splits

### backend/structure_builder.py — Product Structure Builder
- `build_product_structure(text, pages_data, meta, doc_hash) → dict`
- Step 1: table_parser.py (deterministic)
- Step 2: GPT fallback if no tables found
- Step 3: Actuarial validation (range checks, monotonicity)
- Step 4: Eligibility extraction (regex)
- Step 5: Quote capability level (0-3)
- Outputs structure.json

### backend/characters.py — Character Registry
- `CHARACTERS: dict[str, dict]` — arjun and lalita
- Each character: id, name, gender, persona, style_guide, emotional_guide, opener (unused), voice
- `SUPPORTED_LANGUAGES: dict[str, str]` — 10 BCP-47 codes

### backend/tts.py — Text-to-Speech
- `synthesize(text, language_code, speaker) → bytes` — non-streaming, returns full WAV
- `synthesize_stream(text, language_code, speaker) → Iterator[bytes]` — streaming
- `normalize_for_tts(text) → str` — converts ₹ amounts, LPA, percentages, product names, age patterns
- `_truncate_for_tts(text)` — hard cap 400 chars (bulbul:v3 limit)
- `SUPPORTED_LANGUAGES` — 10 language codes

### backend/stt.py — Speech-to-Text
- `transcribe(audio_bytes) → dict` — calls saaras:v3, returns transcript + language_code + language_probability
- Always passes `language_code="unknown"` (specific codes break probability)

### backend/llm.py — LLM Client
- `LLMClient.complete(messages) → str` — blocking, returns full response
- `LLMClient.stream(messages) → Iterator[str]` — streaming tokens
- Both use retry_call() with 3 attempts, exponential backoff

### backend/errors.py — Error Handling
- `SarvamAPIError`, `STTError`, `LLMError`, `TTSError` — typed exceptions
- `retry_call(fn, label, max_attempts=3, base_delay=1.0)` — exponential backoff
- `is_retryable(exc)` — 4xx errors, context overflow, invalid requests → no retry

### backend/metrics.py — JSONL Logging
- `TurnMetrics` dataclass — 13 fields per turn
- `log_turn(metrics)` → appends to `logs/turns.jsonl`
- `log_session(session_id, memory, duration)` → appends to `logs/sessions.jsonl`

### backend/evaluation.py — Post-Conversation Evaluation
- `evaluate_session(memory, character_name) → dict`
- Assembles full transcript, session metrics, objection details
- Calls GPT-4o-mini with EVALUATION_PROMPT
- Returns structured dict with evaluation text + scores

---

## 6. Frontend Architecture

**Technology**: Vanilla HTML/CSS/JavaScript — no framework, no build step.
**File**: `frontend/index.html` (1344 lines, all inline)

### Structure
- Sidebar (left): PolicyAI brand, PDF upload section, advisor character selection, session controls, profile chips, session actions (evaluate, transcript)
- Main area (right): Agent header (avatar, status, mode toggle, language badge), chat window, input area (textarea + mic button + send button)
- Modals: Evaluation modal, Transcript modal

### State
```javascript
sessionId       // current session UUID
selectedChar    // "arjun"
mediaRecorder   // WebRTC recording
isRecording     // recording state
currentWs       // active WebSocket
currentAudioEl  // active Audio element
activeAudioQueue // queued WAV blobs for sequential playback
```

### Audio Pipeline (Frontend)
```
mic button pressed
→ getUserMedia({audio: true}) + MediaRecorder
→ audioChunks[] accumulated
→ mic button pressed again → mediaRecorder.stop()
→ handleAudioBlob(blob)
→ POST /transcribe → transcript
→ appendUserBubble(transcript)
→ voicePipeline(transcript, sttLatencyMs)
  → WebSocket /ws/chat
  → onmessage: type="sentence" → appendAgentBubbleStreaming, update text
  → onmessage: binary → accumulate audioBlobs[]
  → onmessage: type="audio_end" → merge audioBlobs → queueAudio(blob)
  → queueAudio → playNextAudio → Audio.play()
  → onmessage: type="done" → updateStageBadge, updateLangBadge, updateProfileChips
```

### Fallback TTS
```javascript
function browserSpeak(text)  // Web Speech API fallback when Sarvam TTS unavailable
// Fires when: audio blob too small (<100 bytes), TTS API error
```

### Key Functions
- `voicePipeline(message, sttLatencyMs)` — main WebSocket pipeline handler
- `interruptAgent()` — closes WebSocket, stops audio, cancels browser TTS
- `handleAudioBlob(blob)` — transcribes audio, then calls voicePipeline
- `playTTS(text)` — used only for opener (GET /speak endpoint)
- `updateProfileChips(profile)` — shows collected profile fields as chips
- `renderTranscript(turns)` — formats conversation history in modal
- `runEvaluation()` — calls /evaluate, shows modal

---

## 7. Backend Architecture

### Framework
- **FastAPI** 0.115+: async HTTP + WebSocket
- **uvicorn**: ASGI server with standard extras (WebSocket support)
- **python-multipart**: form data (file uploads)
- **aiofiles**: async file I/O for PDF save

### Concurrency Model
- FastAPI runs on asyncio event loop
- All blocking operations (LLM, STT, TTS, file I/O) run in thread pool executor via `loop.run_in_executor(None, ...)`
- Per-session asyncio.Lock prevents concurrent LLM calls for the same session
- Background tasks: `asyncio.create_task(_run_ingestion(...))` for async PDF processing

### Session Management
```python
_sessions: dict[str, AgentSession]     # session_id → AgentSession
_jobs: dict[str, dict]                 # job_id → {status, session_id, ...}
_session_locks: dict[str, asyncio.Lock] # session_id → Lock
```
- No database. All state in-process memory. Lost on server restart.

### Error Handling
- All external API calls wrapped in `retry_call()` (3 attempts, exponential backoff)
- Non-retryable errors (4xx, context overflow) raised immediately
- Agent fallback: `_FALLBACK = "I'm having a connection issue right now..."` for LLM errors
- Frontend retry: error bubble with "Retry" button calls `retryLast()`

---

## 8. Database Architecture

**No database.** All session state is in-process Python dicts.

**Persistence layer**: JSONL files in `logs/`
- `logs/turns.jsonl` — one line per conversation turn (TurnMetrics)
- `logs/sessions.jsonl` — one line per session end (session summary)

**Document artifacts** (file-based, persistent):
- `data/{name}.txt` — full extracted PDF text
- `data/{name}.meta.json` — plan metadata
- `data/{name}.brief.txt` — advisor cheat-sheet
- `data/{name}.structure.json` — premium tables, eligibility, quote capability
- `data/{name}.chunks.json` — BM25 index chunks

Pre-ingested documents (committed in repo):
- HDFC Click2Protect Life
- Axis Max Life STPP
- LIC Jeevan Anand

---

## 9. AI Architecture

| Component | Provider | Model | Purpose |
|---|---|---|---|
| LLM (conversation) | OpenAI | gpt-4o-mini | Sales conversation, stage control, persona |
| LLM (ingestion) | OpenAI | gpt-4o-mini | Metadata extraction, brief generation, premium table extraction fallback |
| LLM (evaluation) | OpenAI | gpt-4o-mini | Post-conversation coaching report |
| STT | Sarvam AI | saaras:v3 | Customer voice → text, language detection |
| TTS | Sarvam AI | bulbul:v3 | Agent text → voice |
| Embeddings | None | N/A | Not used |
| Reranker | None | N/A | Not used |
| OCR | None | N/A | pdfplumber used instead |
| Vision | None | N/A | Not used |

---

## 10. Voice Pipeline

```
USER SPEAKS
     │
     ▼  (browser MediaRecorder)
WebM audio blob (browser)
     │
     ▼  POST /transcribe
Sarvam saaras:v3 STT
  mode="codemix"
  language_code="unknown"
     │
     ▼  → {transcript, language_code, language_probability}
Language detection:
  confidence ≥ 0.70 → commit detected language to session
     │
     ▼  WebSocket /ws/chat
AgentSession.chat_stream(transcript)
  ├── detect_language_from_text() (typed path, N/A for voice)
  ├── extract_profile_fields() → CustomerProfile.apply_updates()
  ├── _build_messages() → [system_prompt, ...history, user_turn]
  └── LLMClient.stream() → OpenAI gpt-4o-mini streaming
     │
     ▼  LLM tokens stream
Sentence splitter (regex on [.!?।])
  → Each complete sentence → {type:"sentence"} → browser (text display)
  → clean_sentences[] accumulated
     │
     ▼  After all LLM tokens received
parse_meta_tag() → (clean_response, TurnAnalysis)
apply_analysis() → update stage, interest, close_readiness, objections
_auto_advance_stage() → Python-gated transitions
     │
     ▼  Parallel TTS
asyncio.gather(*[synthesize(sentence, language, speaker) for sentence in clean_sentences])
  → Each sentence: normalize_for_tts() → Sarvam bulbul:v3 → WAV bytes
     │
     ▼  WAV merge
_merge_wav(wav_blobs) → single continuous WAV file
  (Python stdlib wave module — no dependencies)
     │
     ▼  Binary WebSocket frames (8192-byte chunks)
Browser assembles ArrayBuffer[] → Blob → URL → Audio.play()
     │
     ▼  {type:"done", language, stage, profile} frame
Browser updates UI (stage badge, language badge, profile chips)
```

**Latency profile (documented)**:
- First text visible: ~2s (first LLM sentence arrives)
- Audio starts: ~4s (LLM finishes + parallel TTS ~1s)

---

## 11. Agent Architecture

The agent is `AgentSession` — a single Python object per conversation session.

### How the Agent Knows What to Do (each turn)
```
1. WHAT STAGE AM I IN?
   → memory.stage (INTRODUCE|PROFILE|NEED_DEVELOPMENT|EXPLAIN|RECOMMENDATION|HANDLE|CLOSE|QUESTION_ANSWER)
   → STAGE_INTENTS[stage] injected as "YOUR GOAL THIS TURN"

2. WHAT DO I KNOW ABOUT THE PRODUCT?
   → store.sales_brief (LLM-generated cheat-sheet from ingestion)
   → store.get_context(user_text, top_k=3) (BM25 top-3 relevant chunks)
   → Both injected into system prompt

3. WHAT DO I KNOW ABOUT THE CUSTOMER?
   → memory.customer_profile.summary() (collected fields)
   → missing_fields_line (at PROFILE stage: what's still needed)
   → build_risk_narrative(profile) (at sales-active stages: vulnerability story)
   → build_recommendation_block(profile, meta, brief) (EXPLAIN+: cover estimate)
   → quote_to_prompt_block(quote) (RECOMMENDATION/CLOSE: document-derived quote)

4. HOW SHOULD I COMMUNICATE?
   → character.persona + character.style_guide + character.emotional_guide
   → VOICE_RULES, ADVISOR_RULES, DEFLECTION_PLAYBOOK

5. WHAT LANGUAGE?
   → language_display_name(memory.detected_language) injected as mandatory language rule

6. HOW DO I SIGNAL TRANSITIONS?
   → META_TAG_INSTRUCTION injected; LLM appends [META stage=... ...] to every response
   → conversation_analyzer.py parses and validates; agent.py gates transitions
```

---

## 12. Tool Architecture

No explicit tool-calling framework (no LangChain, no function_calling API). All "tools" are Python functions called deterministically:

| "Tool" | Implementation | When Called |
|---|---|---|
| Profile extraction | profile_extractor.extract_profile_fields() | Every turn, before LLM |
| Language detection | agent.detect_language_from_text() | Every turn (typed text) |
| Risk narrative | agent.build_risk_narrative() | NEED_DEV/EXPLAIN/REC/CLOSE/HANDLE |
| Cover recommendation | recommendation.build_recommendation_block() | EXPLAIN/RECOMMENDATION/CLOSE |
| Premium quote | cover_engine.recommend_cover() + quote_engine.generate_quote() | RECOMMENDATION/CLOSE |
| Document retrieval | store.get_context() via BM25Store.retrieve() | Every turn |
| Stage advancement | agent._auto_advance_stage() | Every turn, after LLM response |
| Meta tag parsing | conversation_analyzer.parse_meta_tag() | Every turn, after LLM response |

---

## 13. Memory Architecture

### Per-Turn (in-context memory)
The system prompt assembled by `_build_messages()` includes:
- Last 6 turns of conversation history (`MAX_HISTORY_TURNS = 6`)
- Current customer profile summary
- Missing fields (at PROFILE stage)
- Risk narrative (sales-active stages)
- Recommendation block + quote (EXPLAIN/RECOMMENDATION/CLOSE)
- Memory summary (interest level, lead score, open objections, positive signals)

### Session Memory (Python object, in-process)
`SessionMemory` dataclass contains:
```python
stage: str                          # current conversation stage
previous_stage: str                 # for HANDLE/QA return
return_to_stage: str                # set when entering QUESTION_ANSWER
turn_in_stage: int                  # turns spent in current stage
close_substage: str                 # PURCHASE_INTENT/PROCEED/FEEDBACK/CLOSED
detected_language: str              # BCP-47 code
emotional_state: str                # curious/engaged/hesitant/resistant/anxious/satisfied
customer_profile: CustomerProfile   # 13 fields
explain_subtopic_index: int         # current EXPLAIN topic
explain_topics: list[str]           # dynamic topic list (set at EXPLAIN entry)
intelligence: CustomerIntelligence  # interest, close_readiness, objections, lead_score
turn_log: list[dict]                # full conversation history
```

### Persistent Storage
- No database. JSONL files only (`logs/turns.jsonl`, `logs/sessions.jsonl`)
- Document artifacts on disk (`data/*.txt`, `data/*.json`)
- Sessions lost on server restart

---

## 14. Workflow Architecture (Stage Machine)

### Stage Transition Rules
```
INTRODUCE (start)
├── LLM signals PROFILE → allowed (with Python validation)
└── turn_in_stage >= 2 → Python forces to PROFILE

PROFILE
├── LLM signals PERSONALIZE → allowed ONLY IF age + (smoker or income) known
├── LLM signals EXPLAIN/CLOSE/RECOMMENDATION → BLOCKED (Python gate I-9)
└── is_sufficient(plan_type) == True → Python forces to NEED_DEVELOPMENT

PERSONALIZE
└── Python forces to NEED_DEVELOPMENT after 1 turn (vestigial stage)

NEED_DEVELOPMENT
├── LLM signals EXPLAIN → allowed
├── LLM signals QUESTION_ANSWER/HANDLE → allowed
├── LLM signals anything else → BLOCKED
└── turn_in_stage >= 2 → Python forces to EXPLAIN

EXPLAIN
├── LLM signals RECOMMENDATION → allowed
├── LLM signals CLOSE → intercepted, redirected to RECOMMENDATION
├── LLM signals QUESTION_ANSWER/HANDLE → allowed
└── (on_last_topic AND turn_in_stage >= 1) OR (close_readiness >= 50 AND turn_in_stage >= 2) OR (turn_in_stage >= 6) → Python forces to RECOMMENDATION

RECOMMENDATION
└── turn_in_stage >= 1 → Python forces to CLOSE (substage=PURCHASE_INTENT)

HANDLE / QUESTION_ANSWER
└── turn_in_stage >= 1 → Python returns to previous stage (or return_to_stage)

CLOSE (substage machine)
├── PURCHASE_INTENT: LLM signals PROCEED → if customer yes
│                   LLM signals FEEDBACK → if customer no
├── PROCEED: Python forces to CLOSED after 1 turn
├── FEEDBACK: LLM signals CLOSED; Python forces after 3 turns
└── CLOSED: terminal
```

### Dual Control (LLM + Python)
- LLM signals desired transition via `[META stage=X]` tag
- Python validates and may block, override, or redirect
- Python also fires escape hatches when LLM gets stuck

---

## 15. API Inventory

| Endpoint | Method | Purpose | Auth | Notes |
|---|---|---|---|---|
| /upload | POST | Ingest PDF | None | multipart/form-data, starts background task |
| /status/{job_id} | GET | Poll ingestion status | None | Returns {status, session_id, chunk_count} when done |
| /chat | POST | Text conversation turn | None | Optional streaming=True for SSE |
| /transcribe | POST | Audio → transcript | None | POST audio/webm, optional session_id |
| /speak | GET | Text → WAV audio | None | Query params: text, session_id, language_code |
| /evaluate | POST | Generate evaluation | None | Ends session; one-time call |
| /transcript/{id} | GET | Get conversation history | None | Returns all turns with stages |
| /session/{id} | DELETE | Clean up session | None | Calls end_session() |
| /ws/chat | WebSocket | Full voice pipeline | None | JSON + binary frames |
| /health | GET | Liveness probe | None | Returns {status:"ok"} |
| / | GET | Serve frontend | None | StaticFiles mount |

---

## 16. Authentication Architecture

**None implemented.** Acceptable for demo.

**What's needed for production**:
- JWT or session tokens
- API key per manager (for PDF upload)
- Rate limiting
- Session isolation (one manager can't access another's sessions)

---

## 17. Security Architecture

### Current Protections
- API keys in `.env`, not hardcoded, `.gitignore`d
- Audio file size limit: 10MB
- PDF extension validation on upload
- Character ID validation (must be in CHARACTERS registry)
- Retry backoff on API failures

### Known Gaps
- No authentication
- CORS `allow_origins=["*"]` — wide open
- No input sanitisation for prompt injection via user messages
- No rate limiting
- `[META stage=CLOSE]` injection in user message could manipulate stage

---

## 18. Deployment Architecture

**Current**: Local development only. Single process, single instance.

```bash
# Start server
.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**Environment variables** (`.env`):
```
SARVAM_API_KEY=...
OPENAI_API_KEY=...
AUTO_APPROVE_DOCUMENTS=true
```

**No Docker, no CI/CD, no cloud deployment.**

---

## 19. Infrastructure Architecture

- **Compute**: Single Python process on developer machine
- **Storage**: Local filesystem (`data/` for documents, `logs/` for JSONL)
- **APIs**: Sarvam AI (cloud, pay-per-use), OpenAI (cloud, pay-per-use)
- **Scalability**: Zero. Single process, in-memory state, no horizontal scaling.

---

## 20. Monitoring Architecture

**Current logging**:
- `logs/turns.jsonl` — per-turn: latencies (STT, LLM, TTS), character counts, detected language, stage, error flags
- `logs/sessions.jsonl` — per-session: duration, turn count, final stage/language, lead score, interest, intent, objection counts

**No dashboards, no alerting, no distributed tracing.**

---

## 21. Data Flow Architecture

```
PDF Upload → ingestion.py
│
├── pdfplumber text extraction → {name}.txt
├── GPT-4o-mini metadata → {name}.meta.json
├── GPT-4o-mini brief → {name}.brief.txt
├── table_parser → structure_builder → {name}.structure.json
└── BM25Store.build → {name}.chunks.json
         │
         ▼ On session start
DocumentStore.load()
├── .txt → self.text
├── .meta.json → self.metadata
├── .brief.txt → self.sales_brief
├── .chunks.json → BM25Store → self._bm25
└── .structure.json → self.structure

Per turn (in AgentSession._build_messages):
profile_extractor(user_text) → CustomerProfile update
language_detector(user_text) → language update
store.get_context(user_text) → top-3 BM25 chunks
build_risk_narrative(profile) → vulnerability story
build_recommendation_block(profile, meta, brief) → cover estimate
generate_quote(profile, cover_lakh, structure) → premium quote
MAIN_SYSTEM_PROMPT.format(...all above...) → system message
→ LLMClient → OpenAI gpt-4o-mini → raw response
parse_meta_tag(raw) → clean text + TurnAnalysis
apply_analysis(memory, analysis) → stage/intelligence update
_auto_advance_stage(memory) → stage gate enforcement
→ Response returned to client
```

---

## 22. Complete Folder Structure Analysis

```
sarvam-insurance-agent/
├── .claude/
│   └── launch.json               # Claude Code launch config
├── .env                          # API keys (gitignored)
├── .env.example                  # Template for .env
├── .gitignore                    # Standard Python + .env
├── HANDOFF.md                    # Previous handoff doc (superseded)
├── README.md                     # Project README
├── requirements.txt              # Python dependencies
├── regen_briefs.py               # Utility: regenerate briefs for existing PDFs
├── run_tests.py                  # Legacy test script
├── direct_test.py                # Legacy direct API test
│
├── backend/
│   ├── __init__.py               # Empty
│   ├── main.py                   # FastAPI app, all endpoints
│   ├── agent.py                  # AgentSession, stage machine, risk narrative
│   ├── pipeline.py               # WebSocket streaming pipeline, WAV merge
│   ├── memory.py                 # SessionMemory, CustomerProfile, CustomerIntelligence
│   ├── prompts.py                # All prompt templates and constants
│   ├── conversation_analyzer.py  # META tag parser, stage transition gates
│   ├── profile_extractor.py      # Deterministic profile extraction (10 fields, regex)
│   ├── recommendation.py         # Benchmark premium estimates
│   ├── cover_engine.py           # Cover amount calculator
│   ├── quote_engine.py           # Document-derived premium quotes
│   ├── characters.py             # Character registry (Arjun, Lalita)
│   ├── ingestion.py              # PDF processing pipeline (5 output files)
│   ├── rag.py                    # DocumentStore, BM25 + keyword retrieval
│   ├── bm25_store.py             # BM25Okapi index, section-aware chunking
│   ├── table_parser.py           # Deterministic premium table extraction
│   ├── structure_builder.py      # Product structure JSON builder
│   ├── tts.py                    # Sarvam bulbul:v3 TTS, normalize_for_tts
│   ├── stt.py                    # Sarvam saaras:v3 STT
│   ├── llm.py                    # OpenAI gpt-4o-mini LLM client
│   ├── errors.py                 # Typed exceptions, retry_call
│   ├── metrics.py                # JSONL logging
│   ├── evaluation.py             # Post-conversation evaluation
│   └── ingest_worker.py          # Thin CLI wrapper around ingestion.py
│
├── frontend/
│   └── index.html                # Single-file SPA (1344 lines, CSS+HTML+JS)
│
├── data/                         # Document artifacts (pre-ingested)
│   ├── HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.pdf
│   ├── HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.txt
│   ├── HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.meta.json
│   ├── HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.brief.txt
│   ├── HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.structure.json
│   ├── HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.chunks.json
│   ├── max-life-stpp-axis-documents.pdf
│   ├── max-life-stpp-axis-documents.txt
│   ├── max-life-stpp-axis-documents.meta.json
│   ├── max-life-stpp-axis-documents.brief.txt
│   │   (no .chunks.json or .structure.json — incomplete ingestion)
│   ├── Lic-leaflet-jeevan-Anand*.pdf
│   ├── Lic-leaflet-jeevan-Anand*.txt
│   ├── Lic-leaflet-jeevan-Anand*.meta.json
│   ├── Lic-leaflet-jeevan-Anand*.brief.txt
│   ├── Lic-leaflet-jeevan-Anand*.structure.json
│   └── Lic-leaflet-jeevan-Anand*.chunks.json
│
└── logs/
    ├── turns.jsonl               # Per-turn metrics (JSONL)
    └── sessions.jsonl            # Per-session summaries (JSONL)
```

---

## 23. Technology Inventory

| Technology | Purpose | Why Used |
|---|---|---|
| Python 3.14 | Backend language | Ecosystem, AI library support |
| FastAPI 0.115+ | Web framework | Async, WebSocket native, fast |
| uvicorn | ASGI server | uvicorn[standard] includes WebSocket support |
| OpenAI SDK (openai>=1.0) | LLM + ingestion calls | gpt-4o-mini is reliable, cheap, 128k context |
| Sarvam AI SDK (sarvamai>=0.1) | STT + TTS | Required by project brief (demo for Sarvam AI) |
| pdfplumber | PDF text + table extraction | Python-native, good table extraction, no Java/Poppler required |
| rank-bm25 | BM25Okapi retrieval | Pure Python, no external service, works offline |
| python-dotenv | API key management | Standard env var loading |
| aiofiles | Async file I/O | Non-blocking PDF write during upload |
| websockets | WebSocket support | Required by uvicorn[standard] |
| python-multipart | Form data parsing | Required for file uploads in FastAPI |
| httpx | HTTP client | Indirect dependency |
| HTML/CSS/JS (vanilla) | Frontend | No build step, no framework, minimal dependencies |

---

## 24. End-to-End Execution Walkthrough

**Scenario**: Customer, 32 years old, non-smoker, married, 2 kids, 15 LPA income, no existing coverage. HDFC Click2Protect Life already uploaded.

### Turn 0: Session Start
```
Client → POST /chat {session_id=..., message="__opener__"}
Server → AgentSession.generate_opener()
  → plan_name = "Click 2 Protect Life" (from meta.json, cleaned)
  → return "Hi, I'm Arjun from PolicyAI. I've gone through the Click 2 Protect Life policy document..."
Client → playTTS(opener_text) → GET /speak?text=...
Server → normalize_for_tts("Click 2 Protect Life") → no change
  → synthesize_stream("Click 2 Protect Life...", "en-IN", "dev") → Sarvam bulbul:v3 → WAV stream
Client plays audio
```

### Turn 1: Customer speaks "Yes, I'd like to know more" (Stage: INTRODUCE)
```
Client → POST /transcribe {audio=webm_blob}
Sarvam saaras:v3 → {transcript:"Yes, I'd like to know more", language_code:"en-IN", language_probability:0.95}
Session.update_language("en-IN", 0.95) → language committed (≥0.70)

Client → WebSocket /ws/chat {session_id, message:"Yes, I'd like to know more", stt_latency_ms:340}

AgentSession.chat_stream("Yes, I'd like to know more")
  extract_profile_fields → {} (no profile fields in text)
  _build_messages():
    stage = INTRODUCE, turn_in_stage = 0
    brief = sales_brief (with PREMIUMS section stripped)
    doc_context = BM25 top-3 chunks for "Yes I'd like to know more" → general overview chunks
    risk_narrative = "" (not at sales-active stage)
    recommendation_block = "" (not at EXPLAIN+)
    stage_intent = STAGE_INTENTS["INTRODUCE"]
    system_prompt assembled (~300 lines)
    history = [] (first user turn)
  
  LLMClient.stream(messages) → OpenAI gpt-4o-mini
  → tokens stream: "Click 2 Protect Life is a pure term insurance plan...Can I ask you a couple of quick questions to make this more relevant for you?[META stage=PROFILE interest_delta=+5 objection=none emotional_state=curious close_readiness_delta=0]"

pipeline.py sentence splitter:
  sentence 1: "Click 2 Protect Life is a pure term insurance plan that pays your nominee a lump sum if something were to happen to you during the policy term."
  → {type:"sentence", text:"..."} → client
  sentence 2: "Can I ask you a couple of quick questions to make this more relevant for you?"
  → {type:"sentence", text:"..."} → client

record_turn():
  parse_meta_tag() → clean: (sentences above), analysis: {stage:PROFILE, interest_delta:5, ...}
  apply_analysis(): stage INTRODUCE → PROFILE allowed → memory.stage = "PROFILE", turn_in_stage = 0
  _auto_advance_stage(): stage=PROFILE, is_sufficient()==False → no auto-advance

Parallel TTS:
  asyncio.gather(synthesize(sentence1), synthesize(sentence2))
  → both WAV blobs
_merge_wav([wav1, wav2]) → single WAV
→ binary frames to client
→ {type:"audio_end"} → client assembles, plays
→ {type:"done", language:"en-IN", stage:"PROFILE", profile:{fields:[]}} → client updates badges
```

### Turn 2: Customer "I'm 32, married with 2 kids" (Stage: PROFILE)
```
extract_profile_fields("I'm 32, married with 2 kids")
  → {age:32, marital_status:"married", dependents:2}
  CustomerProfile.apply_updates() → age=32, marital_status="married", dependents=2, fields_collected=["age","marital_status","dependents"]

_build_messages():
  stage = PROFILE, is_sufficient(plan_type="other") → False (no smoker, no income)
  missing_fields_line = "STILL NEEDED FROM CUSTOMER: smoker status (yes/no), annual income.\nAsk ONLY about these fields..."
  stage_intent = STAGE_INTENTS["PROFILE"] (ask max 2 missing fields, natural order)

LLM → "Do you smoke or use tobacco? And roughly what's your annual income?"
[META stage=PROFILE interest_delta=+3 objection=none emotional_state=curious close_readiness_delta=0]

_auto_advance_stage(): is_sufficient() still False → no advance
```

### Turn 3: Customer "I don't smoke, and I earn about 15 LPA" (Stage: PROFILE)
```
extract_profile_fields() → {smoker:False, income_range:"15 LPA"}
CustomerProfile.apply_updates() → smoker=False, income_range="15 LPA"
fields_collected = ["age","marital_status","dependents","smoker","income_range"]

is_sufficient("other") → age(32)✓ + income_range("15 LPA")✓ → True

_auto_advance_stage() → stage="NEED_DEVELOPMENT", turn_in_stage=0

LLM → "No existing cover at 32 — that's quite common. Quick question: if something unexpected happened and you couldn't work for a year, how would your wife and kids manage financially?"
```

### Turn 5: (after NEED_DEVELOPMENT) Stage: EXPLAIN
```
build_risk_narrative(profile):
  "At 32, this is still a strong window to secure adequate cover. A spouse and 2 dependents rely on this income entirely..."

build_recommendation_block(profile, meta, brief):
  income_lpa = 15; has_dependents = True; multiplier = 15
  cover_lakh = round(15 * 15 / 25) * 25 = 225 lakh = ₹2.25 crore
  age_factor = 1.035^7 = 1.272; smoker_factor = 1.0
  annual_premium = 8500 * 1.272 * (225/100) = ₹24,341
  → "Suggested cover: ₹2.25 crore (15 LPA × 15x + dependents)\nPremium estimate: approx. ₹24,341/year"

explain_topics = ["coverage_and_sum_assured", "premium_and_daily_cost", "death_benefit_and_payout", "key_exclusions"]
explain_subtopic_line = "EXPLAIN TOPIC NOW: Coverage And Sum Assured (topic 1 of 4 | Next: premium and daily cost, death benefit and payout, key exclusions)"

LLM → "Since you have no coverage right now and your family depends entirely on your income, having a ₹2.25 crore cover is the difference between your family staying secure or facing a financial crisis. Click 2 Protect Life lets you choose this coverage amount. Does that scale of protection make sense for your situation?"
```

### Turn N: CLOSE/PURCHASE_INTENT
```
Agent: "Would you like to proceed with purchasing this policy?"
Customer: "Yes"
→ META: close_substage=PROCEED
→ _apply_close_substage: PURCHASE_INTENT → PROCEED (valid next state)

Agent: "Thank you for choosing this plan. I will share the payment and onboarding link with you on your registered email and SMS..."
→ META: close_substage=CLOSED
→ Python auto-advances to CLOSED after 1 PROCEED turn
```
