# Project Handoff Document
# sarvam-insurance-agent — Full Context Transfer
# Date: 2026-06-05 | Last commit: 4b75261

---

## READ THIS FIRST

**Critical facts that override everything else:**

1. **Two data files keep getting reverted by the user's environment** — `data/HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.brief.txt` and `data/HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.meta.json` are regenerated/reverted externally. They currently show `plan_type: "other"`, `company_name: "Not specified"`, and no VARIANTS section — even though we carefully rewrote them in commit 4b75261. The correct versions are in git history. Do NOT assume the files on disk match what was committed. Always check `git diff data/` before starting work.

2. **The stage machine was completely redesigned in the last session.** Old stages (INTRODUCE, PROFILE, NEED_DEVELOPMENT, EXPLAIN, RECOMMENDATION, HANDLE) are replaced. New stages for term plans: GREET → DISCOVERY → GAP_CALC → POSITION → RECOMMEND → VARIANTS → CLOSE. Savings plans: GREET → DISCOVERY → RECOMMEND → EXPLAIN → CLOSE. Old stage names kept as stubs for backward compat only.

3. **The new flow has NOT been end-to-end tested yet.** The redesign was committed and the server was restarted and health-checked, but no full conversation was run through the new flow. The first thing to do in the new session is run a demo and verify all stages fire correctly.

4. **gpt-4o-mini is the LLM** (not sarvam-m, not Claude, not GPT-4o). Switched from sarvam-m in commit 34227ba due to output quality. Model string: `"gpt-4o-mini"`.

5. **No database.** Everything is in-memory. Sessions die on server restart. Intentional for demo/prototype phase.

6. **The HDFC brief needs the VARIANTS section** for the VARIANTS stage to work. The correct brief content is in git at commit 4b75261. If the file has been reverted, restore it before testing.

7. **API keys are in `.env` at project root** — SARVAM_API_KEY and OPENAI_API_KEY. The .env file exists and has real keys. Do not touch them.

8. **Server runs with:** `cd backend && uvicorn main:app --port 8000`. Frontend is served from FastAPI at `/` via StaticFiles mount. Access at `http://localhost:8000`.

9. **The user's mental model is a real-world insurance sales approach:** 70% discovery, 20% positioning, 10% product. The old flow was a scripted stage machine that felt robotic. The new flow is designed to feel like a consultative conversation. The user is passionate about this distinction — do not regress to the old robotic approach.

10. **Three insurance PDFs are pre-ingested:** HDFC Click2Protect Life (term), LIC Jeevan Anand (savings/endowment), Max Life STPP (sparse). Only HDFC and LIC have full chunk/structure files.

---

## 1. Project Overview

**Problem:** Insurance sales in India happen over phone/video calls. Most agents give scripted, product-first pitches that don't address the customer's actual financial situation. Customers tune out.

**Solution:** An AI voice agent named "Arjun" that sells insurance plans from uploaded PDFs using a real-world consultative sales approach — discovery-first, gap-calculation, then product recommendation.

**Business objective:** Demonstrate that an AI agent can conduct a better insurance sales conversation than a typical human agent — more personalised, more honest, more consultative.

**End users:** Insurance advisors using this as a demo/prototype tool. Also useful for direct-to-customer deployment once production-ready.

**Key use cases:**
- Upload any insurance PDF → agent learns the plan
- Customer speaks (voice) or types → agent responds in audio + text
- Agent collects financial profile, computes protection gap, explains variants, closes sale
- Bilingual/Hinglish support (Hindi + English mixed)

---

## 2. Current Project Status

**Phase:** Active development. Core functionality works. New stage machine just redesigned (last commit). Needs end-to-end testing.

**Completed:**
- Full PDF ingestion pipeline (PDF → text → BM25 chunks → brief → structure)
- WebSocket-based voice conversation loop (STT → LLM → TTS → audio playback)
- Three pre-ingested plans: HDFC Click2Protect, LIC Jeevan Anand, Max Life STPP
- New consultative stage machine: GREET → DISCOVERY → GAP_CALC → POSITION → RECOMMEND → VARIANTS → CLOSE
- Gap calculation engine (deterministic Python, not LLM) — `backend/gap_engine.py`
- TTS normalization: LIC→"L I C", करोड़→"crore", decimal amounts, email addresses
- Profile extractor: Hindi income/policy-term extraction, family-member dependent patterns
- Guardrails: no hallucinated premiums, no application form collection, no cover amounts in DISCOVERY
- Assumptive close (not "do you want to buy?")
- HDFC brief rewritten with accurate VARIANTS section (but gets reverted externally)
- Five forensic docs: PROJECT_FORENSICS_HISTORY.md, PROJECT_ARCHITECTURE.md, PROJECT_DECISIONS_AND_ROADMAP.md, PROJECT_AGENT_TRACEABILITY.md, PROJECT_CODE_INDEX.md

**Partially completed / not tested:**
- New GREET→DISCOVERY→GAP_CALC→POSITION→RECOMMEND→VARIANTS→CLOSE flow — not tested end-to-end
- LIC savings path through new flow (GREET→DISCOVERY→RECOMMEND→EXPLAIN→CLOSE)
- HDFC brief/meta.json keeps getting reverted — correct versions in git
- `years_of_support` field exists in CustomerProfile but no extractor pattern written
- `existing_cover_lakh` field exists but no extractor pattern written
- Rider question logic in VARIANTS implemented in prompts but not tested

**Not started:**
- Customer name extraction and personalisation
- Production deployment
- Persistent sessions / multi-tenancy
- Fine-tuning

**Progress estimate:** ~70% of a production-ready demo.

---

## 3. Architecture Overview

```
Browser (frontend/index.html)
    ↕ WebSocket /ws/{session_id}
    ↕ HTTP (upload, health, evaluate)
FastAPI (backend/main.py :8000)
    ├── AgentSession (backend/agent.py)
    │   ├── SessionMemory (backend/memory.py)
    │   ├── ConversationAnalyzer (backend/conversation_analyzer.py)
    │   ├── ProfileExtractor (backend/profile_extractor.py)
    │   ├── GapEngine (backend/gap_engine.py)  ← NEW
    │   └── LLMClient → OpenAI gpt-4o-mini
    ├── STT (backend/stt.py) → Sarvam saaras:v3
    ├── TTS (backend/tts.py) → Sarvam bulbul:v3
    └── DocumentStore (backend/rag.py / bm25_store.py)
        └── data/ (pre-ingested PDFs as .chunks.json, .brief.txt, .meta.json, .structure.json)
```

**Conversation flow per turn (WebSocket):**
1. Browser sends audio bytes (WebM/WAV) over WebSocket
2. `main.py` receives → calls `stt.transcribe()` → Sarvam saaras:v3 → text
3. `profile_extractor.extract_profile_fields(text)` → updates `CustomerProfile` deterministically
4. `agent._build_messages()` → assembles system prompt with all context blocks
5. `LLMClient.complete()` → OpenAI gpt-4o-mini → raw response with [META ...] tag
6. `conversation_analyzer.parse_meta_tag()` → strips [META] → clean text + TurnAnalysis
7. `conversation_analyzer.apply_analysis()` → updates SessionMemory (stage, interest, objections)
8. `agent._auto_advance_stage()` → Python has final say on stage transitions
9. `tts.normalize_for_tts(text)` → runs before TTS
10. `tts.synthesize_stream()` → Sarvam bulbul:v3 → WAV audio
11. Browser receives audio + text over WebSocket

**Key architectural rationale:**
- **BM25 over vector DB**: Single-document retrieval per session. No embedding cost. No infra.
- **gpt-4o-mini**: 20x cheaper than GPT-4o, better instruction following than sarvam-m
- **Deterministic gap calc**: LLM cannot be trusted with arithmetic. Python computes, LLM reads.
- **Python-gated stages**: LLM signals intent via [META], Python has final say. Prevents stuck/premature stages.
- **In-memory sessions**: No database. Prototype phase. Intentional.

---

## 4. Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| Language | Python 3.11+ | Backend |
| Web framework | FastAPI 0.136+ | HTTP + WebSocket server |
| ASGI server | uvicorn 0.48+ | Serves FastAPI |
| LLM | OpenAI gpt-4o-mini | Agent responses, stage signaling |
| STT | Sarvam saaras:v3 | Hindi/English/Hinglish speech-to-text |
| TTS | Sarvam bulbul:v3 | Text-to-speech, Indian voices |
| Sarvam SDK | sarvamai | Python wrapper for Sarvam APIs |
| OpenAI SDK | openai | Python wrapper for OpenAI API |
| Retrieval | rank_bm25 (BM25Okapi) | Document chunk retrieval |
| PDF parsing | pdfplumber | Extracts text from PDFs |
| Async I/O | aiofiles | Non-blocking file operations |
| Frontend | Vanilla HTML/CSS/JS | Single file, zero build step |
| Audio | WebAudio API (browser) | Mic capture, WAV playback |

**Arjun's TTS voice:** `arjun` speaker in bulbul:v3.

---

## 5. Repository Structure

```
sarvam-insurance-agent/
├── backend/
│   ├── main.py              FastAPI app — WebSocket /ws, POST /upload, GET /health
│   ├── agent.py             AgentSession — core LLM orchestration, stage machine
│   ├── memory.py            SessionMemory, CustomerProfile, CustomerIntelligence
│   ├── conversation_analyzer.py  [META] tag parsing, apply_analysis, stage transitions
│   ├── prompts.py           All prompts: STAGE_INTENTS, CLOSE_SUBSTAGE_INTENTS,
│   │                        META_TAG_INSTRUCTION, VOICE_RULES, ADVISOR_RULES,
│   │                        DEFLECTION_PLAYBOOK, MAIN_SYSTEM_PROMPT
│   ├── gap_engine.py        NEW — deterministic protection gap calculator
│   ├── profile_extractor.py Regex extraction from user speech (age/income/dependents/etc)
│   ├── characters.py        Arjun persona, style_guide, emotional_guide, speaker name
│   ├── tts.py               TTS + normalize_for_tts() preprocessing
│   ├── stt.py               STT via Sarvam saaras:v3
│   ├── llm.py               LLMClient wrapping OpenAI gpt-4o-mini
│   ├── rag.py               DocumentStore — BM25 retrieval interface
│   ├── bm25_store.py        BM25Okapi indexing, section-aware chunking
│   ├── ingestion.py         PDF → text → brief → chunks → structure pipeline
│   ├── structure_builder.py Extracts plan structure (pricing tables) from document text
│   ├── quote_engine.py      Deterministic premium quote from document structure
│   ├── cover_engine.py      Recommended cover amount from customer profile
│   ├── recommendation.py    Builds CALCULATED NUMBERS block for system prompt
│   ├── pipeline.py          Orchestrates full ingestion pipeline
│   ├── metrics.py           Turn/session logging to logs/turns.jsonl
│   ├── evaluation.py        Post-conversation evaluation prompt
│   ├── table_parser.py      Extracts premium tables from document text
│   ├── ingest_worker.py     ORPHANED — not called from anywhere, ignore
│   └── errors.py            Custom exceptions (TTSError, STTError, LLMError, QuoteError)
├── frontend/
│   └── index.html           Complete SPA — mic, chat, upload, audio playback
├── data/                    Pre-ingested plan files
│   ├── *.brief.txt          Sales briefs (HDFC one keeps getting reverted — see READ THIS FIRST)
│   ├── *.meta.json          plan_name, company_name, plan_type, one_line_pitch
│   ├── *.chunks.json        BM25 indexed text chunks
│   ├── *.structure.json     Parsed premium table structure
│   └── *.txt                Raw extracted text from PDF
├── logs/
│   ├── sessions.jsonl       Session-level metrics
│   └── turns.jsonl          Per-turn log
├── .env                     SARVAM_API_KEY, OPENAI_API_KEY (valid, not in git)
├── requirements.txt         Python dependencies
├── HANDOFF.md               This document
└── PROJECT_*.md             Five forensic documentation files
```

---

## 6. Implementation History (Commit Log)

| Commit | Description |
|---|---|
| 4b75261 | **Complete stage redesign** — GREET→DISCOVERY→GAP_CALC→POSITION→RECOMMEND→VARIANTS→CLOSE; gap_engine.py created |
| 355d277 | **Major fixes** — Hindi income extraction, TTS normalization (LIC/HDFC/करोड़), guardrails, HDFC brief rewrite |
| d954091 | **Major overhaul** — sales pipeline, language switching, hallucination fixes |
| 34227ba | **LLM switch** — sarvam-m → OpenAI gpt-4o-mini |
| 5c05c08 | Fix max_tokens crash, slim-prompt retry |
| 1d5c599 | Parallel TTS + WAV merge (eliminate audio breaks) |
| 84ffcee | Deterministic opener, Arjun voice |

---

## 7. Design Decisions Log

**D1: BM25 over vector DB**
Single-document retrieval per session. No semantic similarity needed. Zero embedding cost. PERMANENT — do not change.

**D2: gpt-4o-mini over sarvam-m**
sarvam-m failed to follow complex multi-instruction prompts. gpt-4o-mini 20x cheaper than GPT-4o, sufficient quality.

**D3: Deterministic gap calculation (never LLM)**
LLM hallucinated cover amounts even with explicit prohibition. Python computes gap, LLM reads it out. `gap_engine.py` is the source of truth.

**D4: Python-gated stage transitions**
LLM signals intent via [META] tag. Python has final authority in `_auto_advance_stage()`. Prevents both stuck stages and premature advances.

**D5: No database / in-memory sessions**
Prototype phase. Intentional. Eliminates infra complexity.

**D6: Consultative sales model (new flow)**
Old PROFILE→NEED_DEVELOPMENT→EXPLAIN flow felt robotic and scripted. Real insurance sales = 70% discovery, 20% positioning, 10% product. New design: DISCOVERY → GAP_CALC → POSITION → RECOMMEND → VARIANTS → CLOSE.

**D7: Assumptive close**
"Would ₹5 crore or ₹3 crore feel more appropriate?" not "Do you want to buy?" User (real insurance professional) explicitly identified permission close as bad technique.

**D8: Manual HDFC brief with VARIANTS section**
Re-ingesting the PDF with a new prompt would not produce structured variant information. Manual rewrite in commit 4b75261. Problem: the file keeps getting reverted externally.

**D9: SUMMARY substage removed from CLOSE**
Old flow: CLOSE had SUMMARY → PURCHASE_INTENT → PROCEED/FEEDBACK. New flow: CLOSE starts directly at PURCHASE_INTENT (the assumptive close). The RECOMMEND + VARIANTS stages serve as the summary.

---

## 8. AI / LLM Design Details

**Model:** `gpt-4o-mini` via OpenAI API. Temperature 0.7. Max tokens 600.

**System prompt assembly** (`agent._build_messages()`):
Blocks assembled per turn in this order:
1. Persona (Arjun character from `characters.py`)
2. Product knowledge (brief — PREMIUMS section stripped at GREET/DISCOVERY)
3. Document reference (BM25 top-3 chunks for user's last utterance)
4. Language instruction
5. Customer profile (CUSTOMER PROFILE COLLECTED SO FAR)
6. DISCOVERY missing-fields line (only at DISCOVERY stage)
7. GAP_CALC block (only at GAP_CALC stage — Python-computed numbers)
8. Risk narrative (deterministic, at RECOMMEND/VARIANTS/CLOSE)
9. Calculated numbers (cover rec + gap reminder at VARIANTS/CLOSE)
10. Deterministic quote (at CLOSE if document structure available)
11. Current stage + stage intent from STAGE_INTENTS
12. VOICE_RULES, ADVISOR_RULES, DEFLECTION_PLAYBOOK
13. META_TAG_INSTRUCTION

**[META] tag format:**
```
[META stage=DISCOVERY interest_delta=+5 objection=none emotional_state=curious close_readiness_delta=0 close_substage= position_skip=false]
```

**New stage machine (VALID_STAGES):**
```python
{"GREET", "DISCOVERY", "GAP_CALC", "POSITION", "RECOMMEND",
 "VARIANTS", "EXPLAIN", "OBJECTIONS", "CLOSE", "QUESTION_ANSWER"}
```

**LLM_ALLOWED_TRANSITIONS whitelist** (Python enforces, LLM can only signal these):
```
GREET       → DISCOVERY, QUESTION_ANSWER
DISCOVERY   → QUESTION_ANSWER, OBJECTIONS  (Python-only gate out)
GAP_CALC    → POSITION, QUESTION_ANSWER, OBJECTIONS
POSITION    → RECOMMEND, QUESTION_ANSWER, OBJECTIONS
RECOMMEND   → VARIANTS (term), EXPLAIN (savings), QUESTION_ANSWER, OBJECTIONS
VARIANTS    → CLOSE, QUESTION_ANSWER, OBJECTIONS
CLOSE       → CLOSE (substage changes)
```

**Python-only gates (LLM cannot signal these):**
- GREET→DISCOVERY: auto after 2 turns
- DISCOVERY→GAP_CALC (term) or RECOMMEND (savings): when `discovery_sufficient()` is True
- GAP_CALC→POSITION: auto after 1 turn
- POSITION→RECOMMEND: auto after 1 turn
- RECOMMEND→VARIANTS/EXPLAIN: auto after 1 turn
- VARIANTS→CLOSE: hard escape after 6 turns
- QUESTION_ANSWER/OBJECTIONS→return: after 1 turn

**Key guardrails in prompts:**
- NEVER compute rupee amounts in GREET or DISCOVERY
- NEVER mention application forms, identity proof, KYC
- NEVER hallucinate premiums not in document
- DIRECT RECOMMENDATION RULE: when customer says "you tell me", give direct recommendation immediately
- No filler openers
- No echoing back what customer said

---

## 9. Speech Pipeline Details

**STT:** Sarvam saaras:v3 (`backend/stt.py`)
- Mode: `codemix` (Hindi-English mixing)
- Language commit threshold: confidence ≥ 0.70

**TTS:** Sarvam bulbul:v3 (`backend/tts.py`)
- Speaker: `arjun`
- MAX_TTS_CHARS: 400
- Pace: 1.3 (streaming), 1.1 (non-streaming)

**TTS normalization** (`normalize_for_tts()`) — run order:
1. Email: `rahul@gmail.com` → `rahul at gmail dot com`
2. Devanagari units: `करोड़`→`crore`, `लाख`→`lakh`, `सालाना`→`per year`, `प्रति माह`→`per month`
3. Decimal space fix: `1. 5` → `1.5`
4. Decimal range: `1.2 to 1.8 crore` → `one point two to one point eight crore`
5. Single decimal: `₹1.5 crore` → `one point five crore`
6. Acronyms: `LIC`→`L I C`, `HDFC`→`H D F C`, `ULIP`→`U L I P`, `ICICI`→`I C I C I`, `SBI`→`S B I`, `GST`→`G S T`, `EMI`→`E M I`, `ADB`→`A D B`, `ROP`→`R O P`
7. Product names: `Click2Protect` → `Click 2 Protect`
8. Age hyphen: `29-year-old` → `twenty nine year old`
9. LPA: `25 LPA` → `twenty five lakhs per annum`
10. ₹ amounts (integer): full rupee word expansion
11. Percentages, large Indian-format numbers

---

## 10. APIs and Integrations

| API | Purpose | Status | Notes |
|---|---|---|---|
| OpenAI gpt-4o-mini | LLM responses | Working | temp=0.7, max_tokens=600 |
| Sarvam saaras:v3 | STT (Hinglish) | Working | mode=codemix |
| Sarvam bulbul:v3 | TTS | Working | speaker=arjun, MAX_CHARS=400 |

**FastAPI endpoints:**
- `POST /upload` — ingest PDF
- `GET /status/{job_id}` — poll ingestion
- `WebSocket /ws/{session_id}` — main conversation
- `GET /health` — liveness probe
- `POST /evaluate` — post-conversation evaluation
- `DELETE /session/{id}` — end session

---

## 11. Database & Data Model

**No database.** All state in-memory. Sessions die on restart.

**CustomerProfile fields** (backend/memory.py):
```python
age: Optional[int]
gender: Optional[str]              # male | female | other
marital_status: Optional[str]      # single | married | divorced | widowed
dependents: Optional[int]
smoker: Optional[bool]
income_range: Optional[str]        # "25 LPA", "₹2,00,000/month"
liabilities_lakh: Optional[float]  # outstanding loans
existing_coverage: Optional[str]   # categorical: none | some | adequate
existing_cover_lakh: Optional[float]  # NEW: numeric existing cover
years_of_support: Optional[int]    # NEW: years family needs income
chosen_variant: Optional[str]      # NEW: variant chosen at VARIANTS stage
policy_term: Optional[int]
payment_frequency: Optional[str]
cover_amount_override_lakh: Optional[float]
```

**CustomerIntelligence fields:**
```python
interest_level: int = 50
close_readiness: int = 0
gap_lakh: Optional[float]  # NEW: computed at GAP_CALC, used at VARIANTS/CLOSE
```

**SessionMemory key fields:**
```python
stage: str = "GREET"               # NEW default
close_substage: str = "PURCHASE_INTENT"  # NEW default (SUMMARY removed)
position_skipped: bool = False     # NEW
```

---

## 12. Configuration & Environment Setup

```bash
# Clone and setup
cd /Users/ud/sarvam-insurance-agent
source .venv/bin/activate  # venv already exists

# CRITICAL: Restore HDFC data files if reverted
git diff data/HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.brief.txt
git diff data/HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.meta.json
# If different from commit 4b75261:
git checkout 4b75261 -- data/HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.brief.txt
git checkout 4b75261 -- data/HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.meta.json

# Run
cd backend
uvicorn main:app --port 8000

# Access
open http://localhost:8000
```

**Environment variables (.env):**
```
SARVAM_API_KEY=sk_fitv4trq_...
OPENAI_API_KEY=sk-proj-...
```

---

## 13. Bugs Encountered & Resolutions

**BUG-01: Hindi "12 लाख सालाना" not parsed as income**
- Root cause: `_extract_income()` only matched English "lakh"
- Fix: Added Devanagari normalisation before regex in `_extract_income()`

**BUG-02: "nobody is dependent on me" → dependents=None**
- Fix: Added zero-dependent phrase list in `_extract_dependents()`

**BUG-03: "my father dependent on me" → dependents=None**
- Fix: Added family-member + dependency-marker pattern → dependents=1

**BUG-04: "15 साल" not extracted as policy_term**
- Fix: Added Hindi patterns to `_extract_policy_term()`

**BUG-05: Conversation stuck in PROFILE — never advances**
- Root cause: Income not parsed (BUG-01) → `is_sufficient()` always False
- Fix: Income parser fix; smoker guard for non-term plans

**BUG-06: LLM hallucinating premium figures (₹15,000-20,000 for LIC)**
- Root cause: LIC has no premium tables; LLM invented figures anyway
- Fix: When recommendation block says "cannot be estimated", inject ⚠ PREMIUM FIGURES UNAVAILABLE warning

**BUG-07: LLM asking for application forms, identity proof**
- Fix: Explicit ban in VOICE_RULES including "application process" as forbidden phrase

**BUG-08: "LIC" pronounced "licks" by TTS**
- Fix: Acronym expansion table in `normalize_for_tts()`: LIC→"L I C"

**BUG-09: "₹1.5 करोड़" not handled by TTS**
- Fix: Devanagari normalisation pass (करोड़→crore) before amount regexes

**BUG-10: "1. 2 to 1. 8 Crores" read with pauses**
- Fix: `re.sub(r'(\d+)\.\s+(\d+)', r'\1.\2', text)` early pass

**BUG-11: HDFC brief/meta.json keeps getting reverted externally**
- Workaround: Keep correct versions in git, restore with `git checkout 4b75261 -- data/...`

**BUG-12: New STAGE_INTENTS entries ended up outside the dict**
- Root cause: Edit operation created a second CLOSE_SUBSTAGE_INTENTS dict and new entries went into it
- Fix: Reorganized prompts.py; all new intents now properly inside STAGE_INTENTS

---

## 14. Known Issues & Technical Debt

| Issue | Severity | Status |
|---|---|---|
| HDFC brief/meta.json revert | Critical | Workaround: restore from git |
| New flow not end-to-end tested | Critical | Must test immediately |
| `years_of_support` not extracted | High | Field exists, no pattern |
| `existing_cover_lakh` not extracted | High | Field exists, no pattern |
| `ingest_worker.py` orphaned | Low | Dead code, ignore |
| Max Life STPP partially ingested | Low | No chunks, poor retrieval |
| gpt-4o-mini ignores some instructions under load | Medium | Known limitation |
| PERSONALIZE/SUMMARY stage stubs in old code | Low | Dead code, backward compat |

---

## 15. Performance Analysis

**Estimated end-to-end latency per turn:**
- STT: 800ms–1.5s
- LLM: 600ms–1.5s
- TTS: 500ms–1s
- Total: ~2–4 seconds

**Bottleneck:** STT for short utterances; LLM for complex prompts.

**Optimisations done:**
- Parallel TTS + WAV merge
- MAX_HISTORY_TURNS=6
- PREMIUMS section stripped at GREET/DISCOVERY
- BM25 top-3 chunks, DOC_CONTEXT_CHAR_LIMIT=1500

---

## 16. Security Considerations

**Current (demo):** No auth, no rate limiting, CORS `*`, keys in .env.

**Production needs:** Auth, key vault, rate limiting, restricted CORS, session expiry, PII handling.

---

## 17. Testing Status

**Tested:** PDF ingestion, WebSocket flow, STT, TTS, profile extraction (English + Hindi), gap calculation, stage machine routing (unit tested), TTS normalization.

**NOT tested:** Full conversation through new flow, LIC savings path, OBJECTIONS interrupt, QUESTION_ANSWER interrupt, assumptive close, `years_of_support` extraction, `existing_cover_lakh` extraction, position skip signal.

---

## 18. Current Working State

**Works today:**
- `curl localhost:8000/health` → `{"status":"ok"}`
- Frontend at http://localhost:8000
- PDF upload and ingestion
- Voice + text conversation
- TTS normalization (LIC/HDFC/करोड़/email)
- Profile extraction (Hindi + English)
- Gap calculation (gap_engine.py)
- Stage machine routing

**Not verified / may be broken:**
- HDFC brief likely reverted — check and restore
- New conversation flow not tested end-to-end
- `years_of_support`/`existing_cover_lakh` default to 0/20yr in gap calc

---

## 19. Phase-wise Roadmap

| Phase | Status | Description |
|---|---|---|
| 1 — Foundation | ✅ Done | PDF ingestion, WebSocket, basic conversation |
| 2 — Pipeline | ✅ Done | Stage machine (old), BM25, parallel TTS |
| 3 — Quality | ✅ Done | Language switching, guardrails, TTS fixes, Hindi extraction |
| 4 — Redesign | ✅ Done | New consultative flow, gap engine, assumptive close |
| 5 — Testing | 🔄 Current | End-to-end test, extractor additions, polish |
| 6 — Production | ⏳ Future | Auth, persistent sessions, multi-tenancy |
| 7 — Scale | ⏳ Future | Fine-tuning, CRM integration, goal engine |

---

## 20. Immediate Next Steps

1. **Restore HDFC data files from git** (command in section 12)
2. **Run full HDFC conversation** — verify GREET→DISCOVERY→GAP_CALC→POSITION→RECOMMEND→VARIANTS→CLOSE fires in order
3. **Add `years_of_support` extractor** in `profile_extractor.py`:
   - Pattern: "support for 20 years", "20 साल तक", "till my son is 25" (compute years from child's age)
4. **Add `existing_cover_lakh` extractor** in `profile_extractor.py`:
   - Pattern: "₹50 lakh employer cover", "company gives 3x salary", "I have a 1 crore policy"
5. **Test OBJECTIONS interrupt** — say "too expensive" during VARIANTS
6. **Test LIC savings path** — GREET→DISCOVERY→RECOMMEND→EXPLAIN→CLOSE
7. **Verify position skip** — say "I know what term insurance is" at POSITION stage

---

## 21. Critical Context That Must Not Be Lost

1. **HDFC brief file on disk is wrong.** Restore from git at 4b75261 before any testing.

2. **The user is a real insurance professional** who practices real insurance sales. They will notice immediately if the agent feels scripted, robotic, or uses permission-close instead of assumptive-close.

3. **The gap calculation is the centerpiece** of the new flow. Customers don't understand abstract numbers. Showing income × years + loans = gap creates the "aha moment" that makes the sale.

4. **gpt-4o-mini ignores some instructions under heavy prompt load.** Most likely to fail: no-numbers-in-DISCOVERY, no-application-forms, reflective listening. Watch for these in testing.

5. **plan_type in meta.json determines routing.** If `plan_type: "other"`, agent routes to savings path (RECOMMEND→EXPLAIN) instead of term path (RECOMMEND→VARIANTS). HDFC meta.json MUST have `plan_type: "term"`.

6. **discovery_sufficient() for term plans requires family context** (dependents OR marital_status). If customer says "I'm single, no dependents", marital_status extractor must fire. Test this edge case.

7. **CLOSE substage starts at PURCHASE_INTENT.** SUMMARY substage is gone. Do not add it back. The RECOMMEND+VARIANTS stages serve as the summary.

8. **`normalize_for_tts()` must run before bulbul.** It's called inside `synthesize()` and `synthesize_stream()`. Never bypass it.

9. **The `ingest_worker.py` is orphaned.** Ignore it. Don't try to integrate it.

10. **The 5 PROJECT_*.md forensic files** contain deep architectural documentation. Reference them if you need to understand any specific component before making changes.

---

## START HERE IN NEW SESSION

```
Project: /Users/ud/sarvam-insurance-agent

This is an AI voice sales agent for insurance named "Arjun". It sells insurance plans from uploaded PDFs using a consultative sales approach. Stack: FastAPI + OpenAI gpt-4o-mini + Sarvam saaras:v3 (STT) + Sarvam bulbul:v3 (TTS) + BM25 retrieval + single-page HTML frontend.

CURRENT STATE (as of last commit 4b75261):
The stage machine was completely redesigned. New flow for term plans:
  GREET → DISCOVERY → GAP_CALC → POSITION → RECOMMEND → VARIANTS → CLOSE
Savings plans: GREET → DISCOVERY → RECOMMEND → EXPLAIN → CLOSE
The redesign is committed. The server starts and is healthy. The new flow has NOT been end-to-end tested.

CRITICAL — DO THIS FIRST:
The HDFC brief and meta.json files on disk have been reverted externally to incorrect versions.
Restore the correct versions before doing anything:

  cd /Users/ud/sarvam-insurance-agent
  git checkout 4b75261 -- data/HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.brief.txt
  git checkout 4b75261 -- data/HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.meta.json

Then restart the server:
  cd backend && uvicorn main:app --port 8000

Then open http://localhost:8000 and run a full demo with the HDFC Click2Protect plan.

KEY ARCHITECTURE:
- agent.py: AgentSession — assembles system prompt, calls LLM, applies stage transitions
- memory.py: SessionMemory + CustomerProfile (new fields: years_of_support, existing_cover_lakh, chosen_variant) + CustomerIntelligence (new: gap_lakh)
- conversation_analyzer.py: parses [META] tags, enforces LLM_ALLOWED_TRANSITIONS whitelist
- prompts.py: STAGE_INTENTS (new: GREET, DISCOVERY, GAP_CALC, POSITION, RECOMMEND, VARIANTS, OBJECTIONS)
- gap_engine.py: NEW — deterministic gap = income × years + loans − existing cover
- profile_extractor.py: regex extraction of age/income/dependents/etc from speech
- tts.py: normalize_for_tts() — LIC→"L I C", करोड़→crore, decimal crore, emails
- data/*.brief.txt: plan briefs (HDFC one keeps getting reverted)
- data/*.meta.json: plan_type drives term vs savings routing (MUST be "term" for HDFC)

WHAT THE USER WANTS:
Real-world consultative insurance sales. 70% discovery, 20% positioning, 10% product.
The gap calculation (income × years + loans − existing) shown out loud to the customer is the core insight.
Close is assumptive: "₹5 crore or ₹3 crore?" — NOT "do you want to buy?"
The user is a real insurance professional and will notice immediately if the agent feels robotic.

IMMEDIATE PRIORITIES:
1. Restore HDFC data files (command above)
2. Run full HDFC conversation through new flow — verify each stage
3. Add years_of_support extractor in profile_extractor.py ("support for 20 years", "20 साल तक")
4. Add existing_cover_lakh extractor ("₹50 lakh employer cover")
5. Test LIC savings path
6. Test OBJECTIONS interrupt

API keys are in .env at project root — valid, do not change.
Full context in HANDOFF.md at project root.
```
