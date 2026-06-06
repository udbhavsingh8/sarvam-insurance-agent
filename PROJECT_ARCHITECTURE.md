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

STEP 3: GREET Stage
Agent: "Hi, I'm Arjun from PolicyAI. I've gone through the [plan name] policy document..."
Customer: "Yes, tell me about it" or "I don't know this plan"
Agent acknowledges and bridges to discovery (1 turn only — Python forces advance to DISCOVERY)

STEP 4: DISCOVERY Stage (Python advances when discovery_sufficient() == True or 8 turns)
Agent collects in natural conversation: age → who depends on income → annual income →
outstanding loans → existing life insurance → years of support needed
Max 2 questions per turn. Only missing fields asked.
Income-gated: if income not known, ONLY asks about income until collected.
Rupee guard: any ₹ amount in agent response during DISCOVERY is replaced with a safe redirect.

STEP 5: GAP_CALC Stage (term plans only, auto-advances after 1 turn)
Agent walks through deterministic gap calculation from gap_engine.py:
"Your income of ₹X lakh × Y years = ₹Z crore. Plus loans. Minus existing cover.
Protection gap = ₹A crore."
Numbers come exclusively from gap_engine.py — no LLM computation.

STEP 6: POSITION Stage (auto-advances after 1 turn)
Agent reframes term insurance using car insurance analogy.
If customer already knows term insurance → LLM sets position_skip=true → skips to RECOMMEND.

STEP 7: RECOMMEND Stage (auto-advances after 1 turn)
Agent names Click2Protect Life directly: "I'm recommending Click2Protect Life from HDFC."
3-4 sentences only. No premium amounts unless in CALCULATED NUMBERS block.

STEP 8: VARIANTS Stage (term plans) / EXPLAIN Stage (savings plans)
VARIANTS: Agent recommends one variant (default: Life Option), asks about ADB rider,
CI Rebalance if family history. Assumptive close: "Shall we go with [variant] for [gap amount]?"
ROP mentioned only if customer explicitly asks about getting money back.
EXPLAIN: Agent explains one topic at a time (savings/non-term plans only).

STEP 9: CLOSE Stage
PURCHASE_INTENT → customer agrees → PROCEED → agent delivers:
  "Thank you. I'll have the onboarding link sent to you on SMS and email..."
PURCHASE_INTENT → customer declines → FEEDBACK → agent collects reason → CLOSED
VARIANTS direct close: "Perfect, let's get that set up for you." → PROCEED directly (skips PURCHASE_INTENT)
CLOSED: terminal state; QUESTION_ANSWER interrupts blocked

STEP 10: Evaluation (optional)
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
   ├────────────────┬────────────┼──────────────────┬────────────┐
   ▼                ▼            ▼                  ▼            ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────┐
│DocumentS │ │SessionMe │ │  LLMClient   │ │gap_engin │ │cover/    │
│tore (rag)│ │mory      │ │ (llm.py)     │ │e.py      │ │quote_eng │
│BM25Store │ │(memory.py│ │ gpt-4o-mini  │ │          │ │ines.py   │
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
- `_guard_discovery_numbers(text, profile)` — hard safety net: replaces any ₹ amount in DISCOVERY response
- `build_risk_narrative(profile)` — deterministic vulnerability story
- `detect_language_from_text(text)` — Unicode script range detection

### backend/pipeline.py — Streaming Voice Pipeline
- `run_voice_pipeline(websocket, session, message, stt_latency_ms)` — WebSocket handler
- Phase 1: Streams LLM tokens into sentence queue; sends `{type:"sentence"}` frames immediately
- Phase 2: `asyncio.gather()` all sentences for parallel TTS
- Phase 3: `_merge_wav()` combines WAV blobs; sends binary frames + `{type:"audio_end"}`
- Phase 4: Sends `{type:"done", language, stage, profile}`

### backend/memory.py — Session State
- `CustomerProfile` dataclass — 15 fields (including new `existing_cover_lakh`, `years_of_support`, `chosen_variant`)
- `CustomerIntelligence` dataclass — interest_level, close_readiness, gap_lakh, objections, lead_score()
- `SessionMemory` dataclass — all session state; initial `stage="GREET"`, initial `close_substage="PURCHASE_INTENT"`
- `choose_explain_topics(plan_type, profile)` — dynamic topic selection
- `discovery_sufficient(plan_type)` — gates: age + income_range + existing_cover_lakh + years_of_support

### backend/gap_engine.py — Deterministic Gap Calculator (NEW)
- `build_gap_calculation(profile)` → dict with gap_lakh, spoken_walkthrough, assumptions_made
- `gap_to_prompt_block(gap)` → injects pre-formatted walkthrough into system prompt at GAP_CALC
- `_parse_income_lpa(income_range)` — parses "25 LPA", "₹2,00,000/month", etc.
- `_fmt_lakh(lakh)` → "₹X crore" or "₹X lakh"
- Formula: gap_lakh = (income_lpa × years_of_support) + liabilities_lakh − existing_cover_lakh
- Defaults: 20 years, 0 existing cover, 0 liabilities if not stated
- Called at GAP_CALC stage in `_build_messages()`; result stored in `memory.intelligence.gap_lakh`

### backend/prompts.py — All Prompt Templates
- `VOICE_RULES`, `ADVISOR_RULES`, `DEFLECTION_PLAYBOOK` — formatting and behaviour constants
- `OPENER_PROMPT` — not used (generate_opener() is now deterministic)
- `STAGE_INTENTS: dict[str, str]` — intents for new consultative stages (GREET, DISCOVERY, GAP_CALC, POSITION, RECOMMEND, VARIANTS, EXPLAIN, OBJECTIONS, QUESTION_ANSWER) plus legacy stubs
- `CLOSE_SUBSTAGE_INTENTS: dict[str, str]` — PURCHASE_INTENT, PROCEED, FEEDBACK, CLOSED (SUMMARY removed from active flow)
- `META_TAG_INSTRUCTION` — instructs LLM to emit [META ...] tag with `position_skip` field added
- `MAIN_SYSTEM_PROMPT` — master template (~30 placeholders, assembled every turn)
- `EVALUATION_PROMPT` — post-conversation coaching report

### backend/conversation_analyzer.py — Meta Tag Parser + Analysis
- `parse_meta_tag(text)` → `(clean_text, TurnAnalysis | None)` — strips [META ...] tag, returns analysis
- `apply_analysis(memory, analysis, user_text)` — applies stage transitions, interest/objection updates
- `TurnAnalysis` dataclass includes new `position_skip: bool` field
- `_LLM_ALLOWED_TRANSITIONS` enforces which stages the LLM may request transitions to
- DISCOVERY → next: Python-only gate; LLM cannot advance out of DISCOVERY
- VARIANTS → CLOSE: Python sets `close_substage="PROCEED"` directly (skips PURCHASE_INTENT)
- CLOSED: blocks QUESTION_ANSWER interrupts

### backend/profile_extractor.py — Deterministic Profile Extraction
- `extract_profile_fields(text) → dict` — runs before every LLM call
- 12 extractors: age, smoker, income, dependents, marital_status, gender, policy_term, payment_frequency, liabilities_lakh, cover_amount_override_lakh, **years_of_support**, **existing_cover_lakh**
- `existing_cover_lakh = 0.0` when customer says "no insurance" (gates discovery_sufficient)
- "Maybe close to 20 years" → `years_of_support = 20`

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
- Skips brief/meta regeneration if files already exist (prevents revert-on-upload bug)
- `_extract_metadata()` → GPT-4o-mini extracts plan_name, company_name, plan_type, one_line_pitch
- `_generate_brief_via_llm()` → GPT-4o-mini generates 9-section advisor cheat-sheet

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
- Arjun: persona updated to "twenty years of field experience" (was "eight years")
- Each character: id, name, gender, persona, style_guide, emotional_guide, opener (unused), voice
- `SUPPORTED_LANGUAGES: dict[str, str]` — 10 BCP-47 codes

### backend/tts.py — Text-to-Speech
- `synthesize(text, language_code, speaker) → bytes` — non-streaming, returns full WAV
- `synthesize_stream(text, language_code, speaker) → Iterator[bytes]` — streaming
- `normalize_for_tts(text) → str` — converts ₹ amounts, LPA, percentages, product names, age patterns
  - "EMI" → "E M I S" (all caps, spaced) for plural; "100%" → "one hundred percent"
- `_truncate_for_tts(text)` — hard cap 400 chars (bulbul:v3 limit)
- `SUPPORTED_LANGUAGES` — 10 language codes

### backend/stt.py — Speech-to-Text
- `transcribe(audio_bytes) → dict` — calls saaras:v3, returns transcript + language_code + language_probability
- Always passes `language_code="unknown"` (specific codes break probability)

### backend/llm.py — LLM Client
- `LLMClient.complete(messages, stage=None) → str` — blocking, returns full response
- `LLMClient.stream(messages, stage=None) → Iterator[str]` — streaming tokens
- Stage-scoped temperature: lower temperature at GREET/DISCOVERY, higher at VARIANTS/OBJECTIONS
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
  │   ├── (DISCOVERY) missing_fields_line injected (income-gated priority)
  │   ├── (GAP_CALC) build_gap_calculation() → gap_to_prompt_block() injected
  │   ├── (RECOMMEND/VARIANTS/CLOSE) build_risk_narrative() injected
  │   └── (VARIANTS/CLOSE/EXPLAIN) build_recommendation_block() injected
  └── LLMClient.stream(stage=...) → OpenAI gpt-4o-mini streaming
     │
     ▼  LLM tokens stream
Sentence splitter (regex on [.!?।])
  → Each complete sentence → {type:"sentence"} → browser (text display)
  → (DISCOVERY) _guard_discovery_numbers() applied to each sentence
  → clean_sentences[] accumulated
     │
     ▼  After all LLM tokens received
parse_meta_tag() → (clean_response, TurnAnalysis)
apply_analysis() → update stage, interest, close_readiness, objections, position_skip
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
   → memory.stage (GREET|DISCOVERY|GAP_CALC|POSITION|RECOMMEND|VARIANTS|EXPLAIN|OBJECTIONS|CLOSE|QUESTION_ANSWER)
   → STAGE_INTENTS[stage] injected as "YOUR GOAL THIS TURN"
   → At CLOSE: CLOSE_SUBSTAGE_INTENTS[close_substage] used instead

2. WHAT DO I KNOW ABOUT THE PRODUCT?
   → store.sales_brief (LLM-generated cheat-sheet from ingestion)
   → store.get_context(user_text, top_k=3) (BM25 top-3 relevant chunks)
   → Both injected into system prompt
   → PREMIUMS section stripped from brief at GREET/DISCOVERY stages

3. WHAT DO I KNOW ABOUT THE CUSTOMER?
   → memory.customer_profile.summary() (collected fields)
   → missing_fields_line (at DISCOVERY stage: income-gated priority; what's still needed)
   → build_risk_narrative(profile) (at RECOMMEND/VARIANTS/EXPLAIN/CLOSE/OBJECTIONS)
   → build_gap_calculation(profile) → gap_to_prompt_block() (at GAP_CALC)
   → build_recommendation_block(profile, meta, brief) (RECOMMEND/VARIANTS/EXPLAIN/CLOSE)
   → quote_to_prompt_block(quote) (CLOSE: document-derived quote)

4. HOW SHOULD I COMMUNICATE?
   → character.persona + character.style_guide + character.emotional_guide
   → VOICE_RULES, ADVISOR_RULES, DEFLECTION_PLAYBOOK

5. WHAT LANGUAGE?
   → language_display_name(memory.detected_language) injected as mandatory language rule
   → Per-turn ⚠️ LANGUAGE THIS TURN reminder appended at end of system prompt

6. HOW DO I SIGNAL TRANSITIONS?
   → META_TAG_INSTRUCTION injected; LLM appends [META stage=... position_skip=... ...] to every response
   → conversation_analyzer.py parses and validates; agent.py gates transitions
```

---

## 12. Tool Architecture

No explicit tool-calling framework (no LangChain, no function_calling API). All "tools" are Python functions called deterministically:

| "Tool" | Implementation | When Called |
|---|---|---|
| Profile extraction | profile_extractor.extract_profile_fields() | Every turn, before LLM |
| Language detection | agent.detect_language_from_text() | Every turn (typed text) |
| Gap calculation | gap_engine.build_gap_calculation() | GAP_CALC stage, before LLM |
| Risk narrative | agent.build_risk_narrative() | RECOMMEND/VARIANTS/EXPLAIN/CLOSE/OBJECTIONS |
| Cover recommendation | recommendation.build_recommendation_block() | RECOMMEND/VARIANTS/EXPLAIN/CLOSE |
| Premium quote | cover_engine.recommend_cover() + quote_engine.generate_quote() | CLOSE |
| Document retrieval | store.get_context() via BM25Store.retrieve() | Every turn |
| Stage advancement | agent._auto_advance_stage() | Every turn, after LLM response |
| Meta tag parsing | conversation_analyzer.parse_meta_tag() | Every turn, after LLM response |
| Discovery number guard | agent._guard_discovery_numbers() | DISCOVERY stage, after LLM response |

---

## 13. Memory Architecture

### Per-Turn (in-context memory)
The system prompt assembled by `_build_messages()` includes:
- Last 6 turns of conversation history (`MAX_HISTORY_TURNS = 6`)
- Current customer profile summary
- Missing fields (at DISCOVERY stage, income-gated)
- Gap calculation block (at GAP_CALC stage)
- Risk narrative (sales-active stages)
- Recommendation block + quote (RECOMMEND/VARIANTS/EXPLAIN/CLOSE)
- Memory summary (interest level, lead score, open objections, positive signals, computed gap)

### Session Memory (Python object, in-process)
`SessionMemory` dataclass contains:
```python
stage: str                          # current conversation stage (initial: "GREET")
previous_stage: str                 # for QA/OBJECTIONS return
return_to_stage: str                # set when entering QUESTION_ANSWER / OBJECTIONS
turn_in_stage: int                  # turns spent in current stage
close_substage: str                 # PURCHASE_INTENT/PROCEED/FEEDBACK/CLOSED (initial: "PURCHASE_INTENT")
position_skipped: bool              # True if POSITION stage was bypassed
detected_language: str              # BCP-47 code
emotional_state: str                # curious/engaged/hesitant/resistant/anxious/satisfied
customer_profile: CustomerProfile   # 15 fields (includes years_of_support, existing_cover_lakh, chosen_variant)
explain_subtopic_index: int         # current EXPLAIN topic
explain_topics: list[str]           # dynamic topic list (set at EXPLAIN entry)
intelligence: CustomerIntelligence  # interest, close_readiness, gap_lakh, objections, lead_score
turn_log: list[dict]                # full conversation history
```

### CustomerProfile Key Fields (new vs old design)
```python
existing_cover_lakh: Optional[float]  # numeric existing life cover
    # 0.0 = "no insurance" explicitly answered (gates discovery_sufficient)
    # None = not asked yet (blocks discovery_sufficient)
years_of_support: Optional[int]       # years of income replacement needed (gates discovery_sufficient)
chosen_variant: Optional[str]         # plan variant selected at VARIANTS stage
liabilities_lakh: Optional[float]     # outstanding loans in lakh (input to gap_engine)
```

### Persistent Storage
- No database. JSONL files only (`logs/turns.jsonl`, `logs/sessions.jsonl`)
- Document artifacts on disk (`data/*.txt`, `data/*.json`)
- Sessions lost on server restart

---

## 14. Workflow Architecture (Stage Machine)

### Stage Flows
```
Term plans:    GREET → DISCOVERY → GAP_CALC → POSITION → RECOMMEND → VARIANTS → CLOSE
Savings plans: GREET → DISCOVERY → RECOMMEND → EXPLAIN → CLOSE
Any stage:     → QUESTION_ANSWER (interrupt, returns to previous stage after 1 turn)
               → OBJECTIONS     (interrupt, returns to previous stage after 1 turn)
               → NOT from CLOSE/CLOSED (QUESTION_ANSWER blocked from CLOSED substage)
```

### Stage Transition Rules
```
GREET (start)
└── turn_in_stage >= 1 → Python forces to DISCOVERY (single-turn bridge only)

DISCOVERY
├── discovery_sufficient(plan_type) == True → Python advances to GAP_CALC (term) or RECOMMEND (savings)
├── turn_in_stage >= 8 → Python forces advance regardless (8-turn fallback escape)
└── LLM CANNOT signal out of DISCOVERY — Python-only gate

GAP_CALC
└── turn_in_stage >= 1 → Python forces to POSITION (after 1 turn walkthrough)

POSITION
├── LLM signals position_skip=true + stage=RECOMMEND → Python allows (sets position_skipped=True)
└── turn_in_stage >= 1 → Python forces to RECOMMEND

RECOMMEND
└── turn_in_stage >= 1 → Python forces to VARIANTS (term) or EXPLAIN (savings)

VARIANTS
├── LLM signals stage=CLOSE → Python allows; sets close_substage=PROCEED (skips PURCHASE_INTENT)
├── LLM signals QUESTION_ANSWER/OBJECTIONS → allowed (return after 1 turn)
└── turn_in_stage >= 6 → Python forces to CLOSE (PURCHASE_INTENT) — hard escape

EXPLAIN (savings plans)
├── LLM signals stage=CLOSE → allowed (after final topic)
└── (on_last_topic AND turn_in_stage >= 1) OR (turn_in_stage >= 6) → Python forces to CLOSE

QUESTION_ANSWER / OBJECTIONS
└── turn_in_stage >= 1 → Python returns to return_to_stage or previous_stage

CLOSE (substage machine)
├── PURCHASE_INTENT: LLM signals PROCEED (customer yes) or FEEDBACK (customer no)
│                   Python forces to PROCEED after 2 turns
├── PROCEED: Python forces to CLOSED after 2 turns (threshold >= 2 prevents same-turn skip)
├── FEEDBACK: LLM signals CLOSED; Python forces after 2 turns
└── CLOSED: terminal; QUESTION_ANSWER interrupts BLOCKED from here
```

### Dual Control (LLM + Python)
- LLM signals desired transition via `[META stage=X]` tag
- Python validates and may block, override, or redirect
- Python also fires escape hatches when LLM gets stuck (8-turn DISCOVERY fallback, 6-turn VARIANTS escape, etc.)

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
(GAP_CALC) build_gap_calculation(profile) → gap_to_prompt_block() → gap block
build_recommendation_block(profile, meta, brief) → cover estimate
generate_quote(profile, cover_lakh, structure) → premium quote
_guard_discovery_numbers(clean, profile) → safety filter at DISCOVERY
MAIN_SYSTEM_PROMPT.format(...all above...) → system message
→ LLMClient(stage=...) → OpenAI gpt-4o-mini → raw response
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
│   ├── agent.py                  # AgentSession, stage machine, risk narrative, rupee guard
│   ├── pipeline.py               # WebSocket streaming pipeline, WAV merge
│   ├── memory.py                 # SessionMemory, CustomerProfile (15 fields), CustomerIntelligence
│   ├── prompts.py                # All prompt templates and constants (new consultative stages)
│   ├── conversation_analyzer.py  # META tag parser, stage transition gates (new stage set)
│   ├── profile_extractor.py      # Deterministic profile extraction (12 fields, regex)
│   ├── gap_engine.py             # NEW: deterministic gap calculation engine
│   ├── recommendation.py         # Benchmark premium estimates
│   ├── cover_engine.py           # Cover amount calculator
│   ├── quote_engine.py           # Document-derived premium quotes
│   ├── characters.py             # Character registry (Arjun, Lalita)
│   ├── ingestion.py              # PDF processing pipeline (5 output files, skip-if-exists)
│   ├── rag.py                    # DocumentStore, BM25 + keyword retrieval
│   ├── bm25_store.py             # BM25Okapi index, section-aware chunking
│   ├── table_parser.py           # Deterministic premium table extraction
│   ├── structure_builder.py      # Product structure JSON builder
│   ├── tts.py                    # Sarvam bulbul:v3 TTS, normalize_for_tts
│   ├── stt.py                    # Sarvam saaras:v3 STT
│   ├── llm.py                    # OpenAI gpt-4o-mini LLM client (stage-scoped temperature)
│   ├── errors.py                 # Typed exceptions, retry_call
│   ├── metrics.py                # JSONL logging
│   ├── evaluation.py             # Post-conversation evaluation
│   └── ingest_worker.py          # Thin CLI wrapper around ingestion.py (orphaned)
│
├── frontend/
│   └── index.html                # Single-file SPA (CSS+HTML+JS)
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

**Scenario**: Customer, 32 years old, non-smoker, married with father dependent, 15 LPA income, home loan of 30 lakh, no existing insurance, wants 20 years of support. HDFC Click2Protect Life already uploaded.

### Turn 0: Session Start
```
Client → POST /chat {session_id=..., message="__opener__"}
Server → AgentSession.generate_opener()
  → plan_name = "Click 2 Protect Life" (from meta.json, cleaned)
  → return "Hi, I'm Arjun from PolicyAI. I've gone through the Click 2 Protect Life policy document..."
Client → playTTS(opener_text) → GET /speak?text=...
Server → normalize_for_tts("Click 2 Protect Life...") → no change
  → synthesize_stream(...) → Sarvam bulbul:v3 → WAV stream
Client plays audio
```

### Turn 1: Customer speaks "Yes, I'd like to know more" (Stage: GREET)
```
Client → POST /transcribe {audio=webm_blob}
Sarvam saaras:v3 → {transcript:"Yes, I'd like to know more", language_code:"en-IN", language_probability:0.95}
Session.update_language("en-IN", 0.95) → language committed (≥0.70)

AgentSession.chat_stream("Yes, I'd like to know more")
  extract_profile_fields → {} (no profile fields in text)
  _build_messages():
    stage = GREET, turn_in_stage = 0
    brief = sales_brief (with PREMIUMS section stripped)
    stage_intent = STAGE_INTENTS["GREET"]

  LLM → "Before I walk you through the plan, let me ask you a few quick questions..."
  [META stage=DISCOVERY interest_delta=+5 objection=none emotional_state=curious close_readiness_delta=0]

record_turn():
  parse_meta_tag() → stage=DISCOVERY
  apply_analysis(): GREET → DISCOVERY allowed → memory.stage = "DISCOVERY", turn_in_stage = 0
  _auto_advance_stage(): stage=GREET, turn_in_stage=1 → Python forces to DISCOVERY
  (Python and LLM agree — DISCOVERY)
```

### Turn 2: Customer "I'm 32, father is dependent on me" (Stage: DISCOVERY)
```
extract_profile_fields("I'm 32, father is dependent on me")
  → {age:32, dependents:1}
  CustomerProfile.apply_updates() → age=32, dependents=1

_build_messages():
  stage = DISCOVERY
  missing_fields_line = "⚠ CRITICAL: Annual income is NOT yet known. ASK FOR INCOME NOW..."
  (age is known; income is the next gating field → agent only asks about income)

LLM → "With your father depending on you, that's real responsibility. And what's your annual income roughly?"
[META stage=DISCOVERY interest_delta=+3 ...]

_guard_discovery_numbers() → no ₹ in text, passes through
_auto_advance_stage(): discovery_sufficient() = False (no income_range) → no advance
```

### Turn 3: Customer "I earn about 15 LPA, and I have a home loan of 30 lakh" (Stage: DISCOVERY)
```
extract_profile_fields() → {income_range:"15 LPA", liabilities_lakh:30.0}
CustomerProfile.apply_updates()

_build_messages():
  missing_fields_line = "STILL TO COLLECT IN DISCOVERY: existing life insurance (if any), how many years the family would need support."

LLM → "Home loan adds to your exposure. Do you already have any life insurance — personal or through your employer?"
_auto_advance_stage(): discovery_sufficient() = False (no existing_cover_lakh, years_of_support) → no advance
```

### Turn 4-5: Customer provides remaining fields → discovery_sufficient() fires
```
Customer: "No insurance at all. And maybe around 20 years support needed."
extract_profile_fields() → {existing_cover_lakh:0.0, years_of_support:20}

_auto_advance_stage(): discovery_sufficient() = True
  plan_type = "term" → memory.stage = "GAP_CALC", turn_in_stage = 0
```

### Turn 6: GAP_CALC Stage
```
_build_messages():
  stage = GAP_CALC
  gap = build_gap_calculation(profile)
    income_lpa = 15, years = 20, liabilities = 30, existing = 0
    income_protection_lakh = 15 × 20 = 300 lakh (₹3 crore)
    gap_lakh = 300 + 30 - 0 = 330 lakh (₹3.3 crore)
  memory.intelligence.gap_lakh = 330
  gap_block = gap_to_prompt_block(gap) → injected into prompt

LLM → "So your income of ₹15 lakh a year, over 20 years, gives us ₹3 crore just to replace your income.
Plus your home loan of ₹30 lakh — the protection your family actually needs is around ₹3.3 crore.
Does that number surprise you?"
[META stage=POSITION ...]

_auto_advance_stage(): GAP_CALC, turn_in_stage=1 → Python forces to POSITION
```

### Turn 7: POSITION Stage
```
LLM delivers car insurance reframe. Customer agrees term = pure protection.
_auto_advance_stage(): POSITION, turn_in_stage=1 → Python forces to RECOMMEND
```

### Turn 8: RECOMMEND Stage
```
LLM → "Based on what you've told me — at 32 with your father dependent and a ₹3.3 crore gap —
I'm recommending Click2Protect Life from HDFC Life. It's a pure term plan, no investment mix,
and the most efficient way to close that gap at the lowest possible cost."
[META stage=VARIANTS ...]
_auto_advance_stage(): RECOMMEND, turn_in_stage=1 → Python forces to VARIANTS
```

### Turn N: VARIANTS → CLOSE
```
LLM recommends Life Option variant, asks about ADB rider.
Customer agrees: "Yes, let's go with that."
LLM → "Perfect, let's get that set up for you."
[META stage=CLOSE close_substage=PROCEED ...]

apply_analysis(): VARIANTS → CLOSE allowed → close_substage set to PROCEED directly
```

### Turn N+1: PROCEED → CLOSED
```
LLM → "Thank you. I'll have the onboarding link sent to you on SMS and email.
The rest of the process is handled online — it takes just a few minutes.
Our support team is available if you need any help along the way."
[META close_substage=CLOSED ...]

_auto_advance_close_substage(): PROCEED, turn_in_stage=2 → Python forces to CLOSED
```
