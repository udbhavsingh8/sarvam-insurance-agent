# COMPLETE PROJECT DEVELOPMENT HISTORY AND KNOWLEDGE TRANSFER
**PolicyAI — Insurance Sales Voice Agent**
*Forensic reconstruction from git history, source code, and commit messages.*
*Audience: engineers, architects, new AI models, technical due diligence reviewers.*

---

## A. PROJECT ORIGIN

### Original Objective
Build a voice-first AI insurance sales agent as a demo for Sarvam AI — showcasing their STT (`saaras:v3`) and TTS (`bulbul:v3`) speech APIs combined with an LLM in a real-world enterprise application.

### Problem Statement
Insurance sales in India has two structural failures:
1. **Customer side**: Advisors read from brochures generically. Customers receive no personalisation, no risk development, no real recommendation. Most calls end without a sale.
2. **Manager side**: When a new product is launched, advisors need days of training. There is a cold-start problem.

### Business Goal
Demonstrate to Sarvam AI that their speech APIs (STT + TTS) can power a deployable, production-grade enterprise application — specifically an AI insurance sales advisor that:
- Accepts any Indian insurance PDF upload
- Ingests and extracts pricing, coverage, eligibility, sales positioning
- Conducts personalised voice or text sales conversations in 10 Indian languages
- Develops customer need, recommends cover, generates real quotes, closes sales

### User Goals
- **Manager**: Upload a product PDF and have an AI agent ready to sell it in under 2 minutes
- **Customer**: Receive a natural, personalised voice conversation about an insurance product
- **Sarvam AI**: Use this demo as a showcase for prospective enterprise clients

### Constraints
- **Hard**: Must use Sarvam `saaras:v3` for STT, `bulbul:v3` for TTS — this is the demo's purpose
- **Hard**: No vector databases (ChromaDB, FAISS) — explicitly excluded after evaluation
- **Hard**: All premium numbers must be deterministic Python — LLM hallucination is prohibited
- **Soft**: Demo quality (no auth, no persistent DB required for initial version)
- **Timeline**: Built over approximately one week (2026-05-28 to 2026-06-05)

### Success Criteria (from HANDOFF.md)
1. Upload HDFC Click2Protect Life PDF → agent introduces itself correctly
2. Agent collects customer profile naturally (age, smoker, income, family)
3. Agent develops need (makes customer feel financial vulnerability)
4. Agent explains plan tied to customer's specific situation
5. Agent makes a direct personal recommendation
6. Agent generates a real quote with calculated premium
7. Agent closes naturally and hands off
8. Agent speaks clearly in English, Hindi, or Hinglish depending on the customer

---

## B. INITIAL DESIGN THINKING

### Initial Architecture (commit: `e1830c4` — Initial commit: project scaffold)
The baseline had:
- FastAPI backend
- Keyword bag-of-words RAG (no BM25, no vector DB)
- Sarvam-m as the LLM (which was replaced immediately)
- 4-stage machine: GREETING → DISCOVERY → PITCH → CLOSE
- No deterministic profile extraction
- No quote engine
- No structured product JSON
- Text-only interface

### Initial Assumptions and Why They Were Wrong

| Assumption | Reality | Impact |
|---|---|---|
| Sarvam-m LLM would work | Returns API errors constantly | Required full LLM replacement |
| Simple keyword RAG sufficient | Insufficient for complex queries | BM25 with section-aware chunking added |
| 4-stage machine covers arc | Too coarse, no personalisation, agent felt like FAQ bot | Expanded to 8+ stages |
| LLM would personalise if given profile data | LLM acknowledges profile once, then continues generically | Explicit risk narrative mechanism required |
| Sales brief is a safe knowledge base | Marketing figures in brief hallucinated as customer-specific premiums | Hard architectural change required |
| is_sufficient() requiring gender/financial_goal | Customers almost never volunteer these | Gate was permanently stuck, stage never advanced |

### Alternatives Considered

**Vector Search vs BM25**
- ChromaDB/FAISS considered and explicitly rejected
- Reason: No external service, no cost, works offline, insurance vocabulary is keyword-rich
- Decision is permanent for this project

**Goal Engine vs Stage Machine**
- Goal engine (dynamically determine what conversation needs each turn) considered
- Rejected for demo due to complexity and time
- Identified as the correct long-term architecture in HANDOFF.md
- Stage machine chosen: faster to build, more predictable for demo

**Sarvam-m vs OpenAI for LLM**
- Sarvam-m attempted — failed with 402/API errors immediately
- OpenAI gpt-4o-mini selected: low cost, low latency, 128k context, reliable
- gpt-4o-mini kept for all LLM calls: conversation, extraction, brief generation, evaluation

---

## C. CHRONOLOGICAL DEVELOPMENT TIMELINE

### Commit 1: `e1830c4` — 2026-05-28 — Initial commit: project scaffold
- **What**: Basic project structure. FastAPI, Sarvam SDK, PDF text extraction.
- **Files**: Backend scaffold, basic frontend, initial requirements.txt
- **State**: Proof of concept, not functional end-to-end

### Commit 2: `2ae25f6` — 2026-05-28 — feat: complete Insurance Sales Voice Agent (Phases 1-7)
- **What**: First complete implementation. Phases 1-7 in one large commit.
- **Components introduced**: Full AgentSession, session memory, STT, TTS, basic ingestion, 4-stage machine, frontend UI
- **State**: End-to-end functional but generic, no personalisation

### Commit 3: `bca6cf1` — 2026-05-29 — feat: complete voice agent — Phases 2-5 (reliability, language, streaming, barge-in)
- **What**: Reliability and voice quality improvements
- **Added**: Parallel TTS with WAV merging (pipeline.py redesign), language detection, streaming, barge-in (interrupt current audio on new user input)
- **Key change**: `_merge_wav()` function — merges per-sentence WAV files into one continuous audio blob, eliminates inter-sentence audio gaps

### Commit 4: `ea4cac7` — 2026-05-30 — feat: premium SaaS UI redesign (PolicyAI brand, sidebar layout, state animations)
- **What**: Complete UI overhaul
- **Added**: PolicyAI brand, sidebar with document upload + character selection, speaking ring animation, thinking dots, listening overlay, EQ bars, mode toggle (voice/text)
- **Files**: frontend/index.html rebuilt from scratch

### Commit 5: `466b550` — 2026-05-30 — chore: remove unused openai, faiss-cpu, numpy from requirements.txt
- **What**: Cleanup. openai was being removed at this point (before being re-added for LLM)
- **State**: Confirmed: no vector DB dependency

### Commit 6: `11653a3` — 2026-05-30 — fix: truncate turn_log to last 20 turns in _build_messages to prevent context overflow
- **Problem**: Long conversations exceeded context window
- **Fix**: `turn_log[-(20 * 2):]` in _build_messages

### Commit 7: `f81c5f7` — 2026-05-30 — feat: deep advisor persona redesign
- **What**: Arjun and Lalita character definitions with full style_guide, emotional_guide, objection handling
- **Files**: characters.py introduced
- **Key insight**: Character communication style separated from product knowledge

### Commit 8: `479501b` — 2026-05-30 — feat: contextual document-aware opener
- **What**: Agent now introduces the specific plan by name from document metadata
- **Files**: ingestion.py enhanced with metadata extraction; agent.py generate_opener()
- **Change**: Opener uses plan_name from meta.json, not a generic greeting

### Commit 9: `a4beb01` — 2026-05-30 — feat: sales-brief architecture
- **What**: LLM-generated advisor brief. Agent "studies" the product before every conversation.
- **Added**: `_generate_brief_via_llm()` in ingestion.py, brief.txt output file
- **Sections**: COVERAGE, PREMIUMS, ELIGIBILITY, DEATH BENEFIT, MATURITY BENEFIT, RIDERS, TAX BENEFITS, EXCLUSIONS, PITCH

### Commit 10: `9894b18` — 2026-05-30 — feat: advisor architecture — sales brief, customer profiling, stage machine
- **What**: Major architecture expansion
- **Added**: Explicit stage machine, customer profile collection, sales brief injection into prompts
- **Files**: memory.py CustomerProfile, profile_extractor.py initial version, stage intents in prompts.py

### Commit 11: `f1956ab` — 2026-05-30 — fix: enforce stage transitions in prompts
- **Problem**: INTRODUCE stage getting stuck
- **Fix**: META tag instruction added. LLM now signals stage transitions explicitly.

### Commit 12: `3b7e393` and `8866772` — 2026-05-30 — fix: context overflow and blank responses
- **Problem**: Long PDFs caused context overflow → blank LLM responses
- **Fix**: BRIEF_CHAR_LIMIT = 3500, DOC_CONTEXT_CHAR_LIMIT = 1500. Truncation with notice.

### Commit 13: `ad89da6` — 2026-05-30 — fix: resolve stuck INTRODUCE stage and permission question repeating
- **Problem**: LLM kept repeating "shall I ask you some questions?" without advancing
- **Fix**: Python escape from INTRODUCE after 2 turns (turn_in_stage >= 2 → force PROFILE)

### Commit 14: `4f460c3` — 2026-05-30 — feat: deep behavioral redesign — consultative sales advisor
- **What**: Major redesign of all stage intents to consultative rather than scripted
- **Added**: ADVISOR_RULES, VOICE_RULES, DEFLECTION_PLAYBOOK (separate constants)
- **Changed**: All STAGE_INTENTS rewritten to guide intent, not script words

### Commit 15: `597985a` — 2026-05-30 — docs: comprehensive project handoff document
- **What**: HANDOFF.md written (now superseded by these files)

### Commit 16: `6e98fa6` — 2026-05-30 — chore: add ingest_worker and legacy test scripts
- **What**: ingest_worker.py (thin CLI wrapper around ingestion.py), run_tests.py, direct_test.py

### Commit 17: `00e50bf` — 2026-05-30 — feat: Phase A — reliable profile extraction, stage gating, leaner META tag
- **What**: profile_extractor.py expanded to 10 fields. Deterministic regex replaces LLM for profile fields.
- **META tag**: Simplified — stage, interest_delta, close_readiness_delta, objection, emotional_state, close_substage

### Commit 18: `95c4ce1` — 2026-05-30 — feat: Phase B — LLM brief, dynamic topics, merged PERSONALIZE
- **What**: Dynamic explain topics (choose_explain_topics based on plan_type + profile). PERSONALIZE merged into NEED_DEVELOPMENT flow.
- **Added**: memory.py choose_explain_topics(), explain_subtopic_index tracking

### Commit 19: `c6a18c8` — 2026-05-30 — feat: Phase C+D — recommendation engine, inline QA/HANDLE return
- **What**: recommendation.py and cover_engine.py introduced. QUESTION_ANSWER and HANDLE stages.
- **Added**: CustomerIntelligence (interest_level, close_readiness, objections, lead_score), HANDLE substage, QA return_to_stage

### Commit 20: `445de16` — 2026-05-30 — feat: Phase E — chat mode toggle, profile progress, session transcript
- **What**: Voice/Text mode toggle, profile chip display in sidebar, /transcript endpoint
- **Frontend**: Profile chips, transcript modal, mode-toggle UI

### Commit 21: `1d9c840` — 2026-05-30 — fix: crash prevention, robotic language, voice energy
- **Problem**: Null reference crashes, robotic responses, voice too flat
- **Fix**: Null checks, pace adjustment, character style_guide improvements

### Commit 22: `84ffcee` — 2026-05-30 — fix: remove opener LLM call, fix voice to aditya, pace to 1.3
- **Problem**: Opener LLM call was hallucinating (introducing as "from HDFC Life")
- **Fix**: generate_opener() made deterministic — builds opener from character name + plan_name only. No LLM call.
- **Voice**: Changed to `aditya` speaker (later reverted to `dev`)
- **Pace**: Set to 1.3

### Commit 23: `1d5c599` — 2026-05-30 — fix: eliminate audio breaks — parallel TTS + single merged WAV
- **Problem**: Per-sentence TTS caused brief silences between sentences (WAV header reload)
- **Fix**: All sentences TTS'd in parallel with asyncio.gather(); WAV files merged via `_merge_wav()` into single audio blob

### Commit 24: `a4140f3` — 2026-05-30 — fix: opener placeholders, preparing audio indicator, restart with --reload
- **Problem**: Placeholders like "[Plan Name]" appearing in opener
- **Fix**: `_clean()` function strips bracket-contained strings from plan_name before use

### Commit 25: `5c05c08` — 2026-05-30 — fix: max_tokens 2400→1800 (starter tier cap), add slim-prompt retry
- **Problem**: Sarvam-m max_tokens exceeded tier cap (this commit references Sarvam-m but was applied to the LLM config generally)
- **Fix**: Reduced max_tokens. Slim-prompt retry path if primary fails.

### Commit 26: `34227ba` — 2026-05-30 — feat: switch LLM sarvam-m → OpenAI GPT-4o-mini
- **What**: Formal migration commit. sarvam-m removed. OpenAI SDK added. llm.py rewritten.
- **Note**: Some LLM calls to OpenAI were already present earlier (for ingestion). This commit standardises all conversation calls.

### Commit 27: `d954091` — 2026-06-05 — Major overhaul: sales pipeline, UI polish, hallucination fixes, language switching
- **What**: Largest single commit. Multiple root-cause fixes (Iterations 10-11 in HANDOFF.md terminology).
- **Critical fixes**:
  1. ingestion.py: PREMIUMS brief prompt rewritten — excludes all rupee amounts
  2. agent.py: Runtime strips PREMIUMS section at INTRODUCE/PROFILE/NEED_DEVELOPMENT
  3. agent.py: missing_fields_line injected at PROFILE stage (tells LLM exactly what's still needed)
  4. memory.py: is_sufficient() simplified — removed gender/financial_goal requirement
  5. conversation_analyzer.py: PROFILE→PERSONALIZE gated on minimum fields (age + smoker or income)
  6. New stages: NEED_DEVELOPMENT, RECOMMENDATION added with full intents
  7. build_risk_narrative() — deterministic profile→vulnerability story generator
  8. quote_engine.py introduced
  9. table_parser.py, structure_builder.py introduced
  10. bm25_store.py introduced (BM25 retrieval replaces keyword bag-of-words)
  11. evaluation.py introduced
  12. characters.py: Lalita removed, only Arjun remains
  13. detect_language_from_text() — Unicode script detection for typed input
  14. normalize_for_tts() called in /speak endpoint (fixes opener TTS)
  15. Frontend cleanup: lang-badge-sidebar null reference removed
  16. CLOSE substage redesign: turn_in_stage=0 reset prevents same-turn auto-advance

---

## D. ITERATION HISTORY

### Iteration 1: Sarvam-m LLM Failure
**Problem**: `sarvam-m` API returned errors on every call.
**Root cause**: API instability / account tier issues. Possibly quota exhaustion.
**Fix**: Replaced entirely with OpenAI `gpt-4o-mini`. llm.py completely rewritten.
**Files**: `backend/llm.py`
**Lesson**: Never build on an unproven API. Have a fallback LLM ready from day 1.

### Iteration 2: Context Overflow → Blank Responses
**Problem**: Long PDFs caused system prompt to exceed token limits → LLM returned empty string.
**Root cause**: Unlimited brief and document context injected; no truncation.
**Fix**: BRIEF_CHAR_LIMIT = 3500, DOC_CONTEXT_CHAR_LIMIT = 1500, both hard-truncated.
**Files**: `backend/agent.py:_build_messages()`

### Iteration 3: INTRODUCE Stage Stuck
**Problem**: Agent kept repeating "Shall I ask you some questions?" indefinitely.
**Root cause**: LLM had no instruction to advance stage; stage was only LLM-controlled.
**Fix**: Python escape — if `turn_in_stage >= 2` and still INTRODUCE → force to PROFILE.
**Files**: `backend/agent.py:_auto_advance_stage()`

### Iteration 4: Premium Hallucination at PROFILE Stage (Critical)
**Problem**: Agent presented "₹22/day" as the customer's specific premium during profile collection.
**Root cause**: HDFC brief contained "₹22/day for 25-year non-smoker" in PREMIUMS section. Injected into system prompt at every stage including PROFILE. At PROFILE, no calculated numbers block exists. LLM presented brief figure as customer-specific fact.
**Fix**:
1. Ingestion prompt rewritten: PREMIUMS section now describes payment structure ONLY, no rupee amounts
2. Runtime: PREMIUMS section stripped from brief at INTRODUCE/PROFILE/NEED_DEVELOPMENT stages in `_build_messages()`
3. HDFC PDF re-ingested with new prompt
**Files**: `backend/ingestion.py:_generate_brief_via_llm()`, `backend/agent.py:_build_messages()`
**Lesson**: Any rupee figure in the brief at early stages will be hallucinated as customer-specific. This is architectural, not prompt-fixable.

### Iteration 5: Profile Gate Never Firing
**Problem**: `is_sufficient()` required `gender` and `financial_goal` among 4 required fields. Customers almost never volunteer these. Gate never fired. Stage machine stuck at PROFILE indefinitely.
**Root cause**: Requirements designed from ideal customer, not real customer utterances.
**Fix**: Simplified to `age + smoker + income_range + (dependents or marital_status)` for term plans.
**Files**: `backend/memory.py:CustomerProfile.is_sufficient()`

### Iteration 6: Ungated PROFILE→PERSONALIZE Exit
**Problem**: I-9 fix had blocked PROFILE→EXPLAIN and PROFILE→CLOSE, but not PROFILE→PERSONALIZE. LLM could exit PROFILE early without all fields collected.
**Root cause**: Not all possible transitions from PROFILE were gated.
**Fix**: Gate added in `apply_analysis()`: PROFILE→PERSONALIZE requires `age != None and (smoker != None or income_range != None)`.
**Files**: `backend/conversation_analyzer.py:apply_analysis()`

### Iteration 7: Opener Hallucination (Wrong Brand)
**Problem**: Agent said "I'm Arjun from HDFC Life" — presenting as being employed by the insurer.
**Root cause**: Opener LLM call used one_line_pitch from meta.json which referenced the insurer's brand.
**Fix**: generate_opener() made fully deterministic. Uses character name + plan_name only. No LLM call. Fixed text: "Hi, I'm {name} from PolicyAI. I've gone through the {plan_name} policy document..."
**Files**: `backend/agent.py:generate_opener()`

### Iteration 8: Opener TTS Spelling Out "Click2Protect"
**Problem**: TTS spelled out "Click2Protect" as individual letters.
**Root cause**: GET /speak endpoint called `synthesize_stream()` directly, bypassing `normalize_for_tts()`. pipeline.py called it correctly; /speak did not.
**Fix**: `normalize_for_tts()` called before `synthesize_stream()` in /speak endpoint.
**Files**: `backend/main.py:/speak endpoint`, `backend/tts.py:normalize_for_tts()`

### Iteration 9: Language Switch Not Working for Typed Text
**Problem**: Language detection only worked for voice input (STT-detected language). Typed Hindi/Tamil got no language switch.
**Root cause**: Language update path was STT-only. No text-based language detection.
**Fix**: `detect_language_from_text()` method in AgentSession — scans Unicode code point ranges (Devanagari → hi-IN, Tamil → ta-IN, etc.). Commits at confidence=1.0 for typed non-Latin scripts.
**Files**: `backend/agent.py:detect_language_from_text()`

### Iteration 10: Inter-Sentence Audio Gaps
**Problem**: Brief silence between each sentence in the agent's response.
**Root cause**: TTS produced separate WAV files per sentence. Each WAV has a header. Audio element reloaded header before each sentence → perceptible gap.
**Fix**: All sentences TTS'd in parallel via `asyncio.gather()`. WAV blobs merged via `_merge_wav()` using Python stdlib `wave` module. Single continuous audio blob sent to client.
**Files**: `backend/pipeline.py:_merge_wav()`, `backend/pipeline.py:run_voice_pipeline()`

### Iteration 11: CLOSE Stage Application Data Collection
**Problem**: Agent invented an application collection workflow at CLOSE/PROCEED — asking for name, address, health history, nominee details.
**Root cause**: LLM's strong prior about "insurance application" overrode PROCEED substage prompt.
**Fix**: PROCEED substage prompt rewritten with explicit forbidden list (6 prohibited behaviors).
**Files**: `backend/prompts.py:CLOSE_SUBSTAGE_INTENTS["PROCEED"]`

### Iteration 12: Null Reference in Frontend on Session Start
**Problem**: On session start, opener TTS sometimes didn't fire. Fallback "Hello! I'm ready" appeared instead.
**Root cause**: `updateLangBadge()` called `document.getElementById("lang-badge-sidebar")` which was removed when Live Intelligence sidebar was removed. Threw null reference → caught by try/catch → catch block showed fallback bubble before playTTS() was called.
**Fix**: Dead reference removed.
**Files**: `frontend/index.html:updateLangBadge()`

---

## E. FEATURE DEVELOPMENT HISTORY

### Feature: PDF Ingestion Pipeline
**Why introduced**: Need to support any insurance PDF without hardcoding product knowledge.
**Evolution**:
- v1: Basic `pdfplumber` text extraction only
- v2: LLM metadata extraction (plan_name, company_name, plan_type, one_line_pitch) via GPT-4o-mini
- v3: LLM brief generation (advisor cheat-sheet, 9 sections)
- v4: Deterministic premium table extraction via table_parser.py
- v5: structure_builder.py — builds structure.json with quote capability level
- v6: BM25 indexing via bm25_store.py — section-aware chunks
**Current**: 5 output files per PDF. Full pipeline 10-15 seconds for typical brochure.

### Feature: Stage Machine
**Why introduced**: Need structured sales conversation flow, not free-form chat.
**Evolution**:
- v1: 4 stages — GREETING, DISCOVERY, PITCH, CLOSE
- v2: META tag instruction added — LLM signals transitions
- v3: Python escape after 2 INTRODUCE turns
- v4: I-9 gates — block PROFILE→EXPLAIN/CLOSE
- v5: NEED_DEVELOPMENT stage added (develop customer's sense of risk before pitching)
- v6: RECOMMENDATION stage added (direct personal recommendation before CLOSE)
- v7: HANDLE and QUESTION_ANSWER stages (objection and Q&A handling)
- v8: CLOSE substage machine — PURCHASE_INTENT→PROCEED/FEEDBACK→CLOSED
- v9: PROFILE→PERSONALIZE gate; missing_fields_line injection

### Feature: Customer Profiling
**Why introduced**: Personalisation requires knowing the customer.
**Evolution**:
- v1: LLM-extracted only (implicit in conversation history)
- v2: CustomerProfile dataclass with 5 fields
- v3: profile_extractor.py — deterministic regex extraction before every LLM call
- v4: 10 profile fields (added policy_term, payment_frequency, liabilities_lakh, cover_amount_override_lakh)

### Feature: Risk Narrative
**Why introduced**: LLM personalises generically. Need to force specific vulnerability framing.
**How**: `build_risk_narrative()` — pure deterministic Python, converts profile fields into a 5-6 sentence financial vulnerability story. Injected into system prompt at NEED_DEVELOPMENT, EXPLAIN, RECOMMENDATION, CLOSE, HANDLE.
**Why deterministic**: LLM-generated narratives varied and sometimes inaccurate. Deterministic = auditable, consistent.

### Feature: Quote Engine
**Why introduced**: LLM hallucinated premiums. Insurance customers trust numbers or don't buy.
**Two-tier design**:
1. `recommendation.py` — industry benchmark estimates (income × multiplier, actuarial constants). Injected at EXPLAIN/RECOMMENDATION/CLOSE.
2. `quote_engine.py` — document-derived from structure.json. Interpolates premium tables, applies GST 18%, all 4 frequency breakdowns. Injected at RECOMMENDATION/CLOSE only.
**Critical**: If smoker=None, premium estimate is suppressed entirely. Never assumes non-smoker.

### Feature: BM25 Retrieval
**Why introduced**: Keyword bag-of-words scored poorly on multi-word insurance queries.
**Implementation**: `bm25_store.py` — section-aware chunking (detects insurance document headers), BM25Okapi scoring, fallback to first N chunks if no matches.
**Why not vector search**: No external service, no cost, works offline, insurance vocabulary is keyword-rich.

### Feature: Character Registry
**Why introduced**: Sales persona must be consistent — not just prompt text but emotional handling.
**Characters**:
- `arjun` — high-performing male advisor, 30s, energetic and consultative, `dev` voice
- `lalita` — patient female advisor, 40s, empathetic and trust-building, `ritu` voice (removed from UI in latest iteration, only Arjun shown)
**Each character has**: identity, persona, style_guide, emotional_guide, voice

---

## F. MODEL EVOLUTION HISTORY

### Sarvam-m (LLM — Attempted, Immediately Abandoned)
- **Provider**: Sarvam AI
- **Purpose**: Conversation LLM
- **Selected**: Per project brief requirements (Sarvam AI demo)
- **Problem**: API errors on every call (likely 402 / quota / API instability)
- **When replaced**: Day 1 effectively (commit `34227ba` is the formal removal)
- **Replacement**: OpenAI gpt-4o-mini

### OpenAI gpt-4o-mini (LLM — Current)
- **Provider**: OpenAI
- **Purpose**: All LLM work — conversation, metadata extraction, brief generation, post-conversation evaluation
- **Model ID**: `gpt-4o-mini`
- **Configuration**:
  - Conversation: temperature=0.7, max_tokens=600
  - Metadata extraction: temperature=0.1, max_tokens=200
  - Brief generation: temperature=0.3, max_tokens=900
  - Premium table extraction: temperature=0.0, max_tokens=400
  - Evaluation: no explicit config (uses complete())
- **Why selected**: Low cost ($0.00015/1k input, $0.00060/1k output), 128k context window, fast, reliable
- **Known limitations**: Strong trained priors about insurance/sales override stage instructions in long prompts. Structural data removal (PREMIUMS stripping) more effective than prohibitive instructions.
- **Retry policy**: 3 attempts, exponential backoff (1s, 2s, 4s), non-retryable on 4xx

### Sarvam saaras:v3 (STT — Current)
- **Provider**: Sarvam AI
- **Purpose**: Customer voice → text transcription
- **Mode**: `codemix` — handles Hindi-English code-mixing
- **Language**: Always `language_code="unknown"` — specific codes cause `language_probability=None`
- **Output**: `{transcript, language_code, language_probability}`
- **Language commit threshold**: ≥0.70 confidence → immediate commit to new language
- **Constraint**: Required (Sarvam AI demo requirement)

### Sarvam bulbul:v3 (TTS — Current)
- **Provider**: Sarvam AI
- **Purpose**: Agent text → voice audio
- **Voice**: `dev` (male, for Arjun), `ritu` (female, for Lalita — currently unused)
- **Pace**: 1.1 (non-streaming synthesize), 1.3 (streaming synthesize_stream)
- **Sample rate**: 22050 Hz
- **Output codec**: WAV
- **Hard character limit**: 400 chars per call (bulbul:v3 rejects longer inputs)
- **Pre-processing**: `enable_preprocessing=True` — normalises text for speech
- **Text normalisation**: `normalize_for_tts()` called before every TTS call — converts ₹ amounts, LPA, percentages, age patterns, product names
- **Constraint**: Required (Sarvam AI demo requirement)
- **Note from earlier memory**: Speaker names `ritu`, `priya`, `kavitha`, `gokul` (others → BadRequestError) — current code uses `dev` and `anushka` as defaults, suggesting this was updated

---

## G. API EVOLUTION HISTORY

### Sarvam AI SDK
- **Purpose**: STT + TTS
- **Init**: `SarvamAI(api_subscription_key=key)` — NOT `api_key=`
- **STT call**: `client.speech_to_text.transcribe(file=(...), model="saaras:v3", mode="codemix", language_code="unknown")`
- **TTS call**: `client.text_to_speech.convert(text=..., target_language_code=..., speaker=..., model="bulbul:v3", output_audio_codec="wav", speech_sample_rate=22050, enable_preprocessing=True, pace=1.1)`
- **Issues**: `api_key=` parameter raises TypeError; `language_code` other than `"unknown"` causes `language_probability=None`; speaker names strictly validated

### OpenAI SDK
- **Purpose**: All LLM calls
- **Init**: `OpenAI(api_key=key)`
- **Call**: `client.chat.completions.create(model="gpt-4o-mini", messages=[...], max_tokens=N, temperature=T, stream=True/False)`
- **Used in**: llm.py (conversation), ingestion.py (metadata + brief + table extraction), evaluation.py (evaluation), structure_builder.py (GPT fallback)

---

## H. BUG HISTORY

### BUG-01: Sarvam-m blank responses
- **Symptom**: Every LLM response was empty string or error
- **Root cause**: sarvam-m API instability / quota
- **Fix**: Full LLM replacement with OpenAI gpt-4o-mini

### BUG-02: Context overflow → blank responses
- **Symptom**: Agent went silent after a few turns with long PDFs
- **Root cause**: System prompt exceeded token limits
- **Fix**: BRIEF_CHAR_LIMIT=3500, DOC_CONTEXT_CHAR_LIMIT=1500

### BUG-03: INTRODUCE stage infinite loop
- **Symptom**: Agent kept asking "Shall I ask some questions?" indefinitely
- **Root cause**: No Python escape from INTRODUCE; LLM had no mechanism to advance
- **Fix**: turn_in_stage >= 2 → force to PROFILE

### BUG-04: Premium hallucination at PROFILE stage (Critical)
- **Symptom**: Agent said "₹22/day" to customer during profile collection
- **Root cause**: HDFC brief contained example premium; injected at all stages
- **Fix**: Brief PREMIUMS section → payment structure only; runtime strip at early stages

### BUG-05: Profile gate never firing
- **Symptom**: Conversation stuck at PROFILE forever
- **Root cause**: is_sufficient() required gender + financial_goal which were never stated
- **Fix**: Simplified sufficiency requirements

### BUG-06: Opener introduced agent as "from HDFC Life"
- **Symptom**: Agent presented itself as employed by the insurer
- **Root cause**: Opener LLM call used one_line_pitch which referenced insurer brand
- **Fix**: Deterministic opener using only character name + plan_name

### BUG-07: Audio gaps between sentences
- **Symptom**: 100-200ms silence between each sentence in response
- **Root cause**: Separate WAV per sentence, WAV header reload
- **Fix**: Parallel TTS + WAV merge → single audio blob

### BUG-08: Session start — no TTS, fallback bubble
- **Symptom**: On session start, agent showed fallback text "Hello! I'm ready"
- **Root cause**: JavaScript null reference on `lang-badge-sidebar` (removed element)
- **Fix**: Removed dead DOM reference

### BUG-09: "Click2Protect" spelled out in opener
- **Symptom**: TTS pronounces product name letter-by-letter
- **Root cause**: /speak endpoint bypassed normalize_for_tts()
- **Fix**: normalize_for_tts() added to /speak endpoint

### BUG-10: PROFILE→PERSONALIZE ungated
- **Symptom**: LLM exiting PROFILE before collecting all required fields
- **Root cause**: I-9 fix blocked only PROFILE→EXPLAIN and PROFILE→CLOSE, not PROFILE→PERSONALIZE
- **Fix**: Gate added in apply_analysis()

### BUG-11: CLOSE/PROCEED collecting application data
- **Symptom**: Agent asking for name, address, health, nominee at PROCEED substage
- **Root cause**: LLM's strong insurance-application prior overrode prompt
- **Fix**: Explicit forbidden list in PROCEED substage prompt

---

## I. FAILED EXPERIMENTS

### Failed: Sarvam-m as conversation LLM
- **Attempted**: Use sarvam-m (Sarvam's own LLM) for conversation
- **Why tried**: Project brief required it; Sarvam demo
- **Why failed**: 402/API errors on every call; API not stable enough for demo
- **Learned**: Always have a fallback LLM ready; API reliability must be verified before committing to any provider

### Failed: LLM-based opener
- **Attempted**: LLM generates context-aware opener from document metadata
- **Why tried**: More natural, varied openers
- **Why failed**: Hallucinated brand ("from HDFC Life"), used placeholder text ("[Plan Name]"), inconsistent
- **Learned**: For structured one-time outputs (opener), deterministic template + data injection is more reliable than LLM generation

### Failed: Prohibitive instructions for premium hallucination
- **Attempted**: Add "do not quote premiums at PROFILE stage" to system prompt
- **Why tried**: Quickest fix
- **Why failed**: LLM ignores late-arriving prohibitions when strong trained prior exists. Information appearing earlier in prompt dominates.
- **Learned**: If you need the LLM to not use information, remove it from the prompt. Instructions prohibiting data that the LLM can see are unreliable.

### Failed: gender + financial_goal in is_sufficient()
- **Attempted**: Require gender and financial_goal as profile sufficiency gates
- **Why tried**: Seemed like useful personalisation fields
- **Why failed**: Customers almost never volunteer gender or financial goal in natural conversation. Gate permanently stuck.
- **Learned**: Profile requirements must be validated against realistic customer utterances, not ideal ones.

### Failed: Specific language_code in STT call
- **Attempted**: Pass `language_code="hi-IN"` to saaras:v3 for Hindi detection
- **Why tried**: Seemed like logical hint for the STT model
- **Why failed**: Causes `language_probability=None` → downstream language detection breaks
- **Learned**: Always pass `language_code="unknown"` to saaras:v3

### Failed: 4-stage conversation machine (GREETING/DISCOVERY/PITCH/CLOSE)
- **Attempted**: Simple 4-stage arc
- **Why tried**: Minimal viable structure
- **Why failed**: Too coarse. No need development. No personalisation hooks. Agent felt like FAQ bot.
- **Learned**: Insurance sales requires at minimum: intro, profiling, need development, explanation, recommendation, close. Collapsing these loses the consultative quality.

---

## J. PIVOTS

### Pivot 1: Sarvam-m → OpenAI gpt-4o-mini (LLM)
- **Trigger**: Immediate API failure
- **Impact**: All LLM calls now go to OpenAI. Sarvam APIs remain for STT/TTS only.

### Pivot 2: Generic stages → Consultative sales stages
- **Trigger**: Agent felt robotic and scripted in early testing
- **From**: GREETING → DISCOVERY → PITCH → CLOSE
- **To**: INTRODUCE → PROFILE → NEED_DEVELOPMENT → EXPLAIN → RECOMMENDATION → CLOSE
- **Why**: Need development (making customer feel financial vulnerability) is the core of insurance sales. It was absent in the original design.

### Pivot 3: LLM-generated opener → deterministic template opener
- **Trigger**: Opener hallucination bug
- **Impact**: generate_opener() becomes a Python string template using document metadata. Zero LLM calls at session start.

### Pivot 4: Instruction-based hallucination prevention → structural data removal
- **Trigger**: Premium hallucination bug; prompt-based prohibition failed
- **From**: "Do not quote premiums at PROFILE stage" instruction
- **To**: Runtime strip of PREMIUMS section from brief at INTRODUCE/PROFILE/NEED_DEVELOPMENT
- **Impact**: Permanently architectural. No rupee amounts possible at early stages.

### Pivot 5: LLM-only profile extraction → deterministic regex + LLM
- **Trigger**: LLM sometimes missed explicit profile statements; profile gate never fired
- **From**: LLM-implicit profile understanding
- **To**: profile_extractor.py runs deterministic regex on every user message BEFORE LLM call
- **Impact**: Profile fields collected reliably. is_sufficient() can now fire correctly.

### Pivot 6: Free-form LLM stage control → Python-gated stage machine
- **Trigger**: LLM stuck in stages, skipping stages, not advancing
- **From**: Stage transitions entirely LLM-controlled via META tags
- **To**: LLM signals transitions; Python enforces via _auto_advance_stage() + conversation_analyzer.py gates
- **Impact**: Predictable stage progression. Python escape hatches prevent permanent stucks.

---

## K. PERFORMANCE IMPROVEMENT HISTORY

### Audio Latency Optimisation
- **Original**: Sequential TTS per sentence (~1s per sentence × N sentences gap)
- **Optimisation**: Parallel `asyncio.gather()` for all sentences. All N sentences TTS'd simultaneously.
- **Result**: Total audio latency ≈ max(individual sentence TTS time) instead of sum
- **Documented latency profile**: First text visible ~2s (first LLM sentence); audio starts ~4s (LLM done + parallel TTS ~1s)

### Context Efficiency
- **Problem**: Full conversation history caused context growth and overflow
- **Fix**: `MAX_HISTORY_TURNS = 6` — only last 6 turns sent to LLM
- **System prompt efficiency**: PREMIUMS section stripped at early stages (saves ~300-500 chars per turn)
- **Brief truncation**: 3500 char limit with notification
- **Document context**: 1500 char limit, BM25 top-3 only

### Ingestion Efficiency
- **All 5 output files generated once** at upload time, not per conversation turn
- **Brief generation**: One LLM call at ingestion. All subsequent turns use pre-generated brief.
- **BM25 index**: Built once, saved to JSON, loaded on session start. No per-query reindexing.

---

## L. SECURITY HISTORY

### Authentication
- **Current**: None. No auth, no session isolation beyond in-memory dict.
- **Risk**: Any client with the server URL can create sessions and query any session by ID.
- **Mitigation (none yet)**: Acceptable for demo; required before production.

### Prompt Injection Protection
- **Input validation**: `message.strip()` checked; empty messages rejected (400)
- **Audio size limit**: MAX_AUDIO_BYTES = 10MB (rejects DoS via large audio)
- **No explicit prompt injection detection**: User text is included verbatim in LLM messages. No sanitisation for META tag injection or system prompt escape attempts.
- **Risk**: A user could potentially inject `[META stage=CLOSE]` in their message to manipulate stage. Currently not defended.

### LLM Guardrails
- **Hallucination prevention (structural)**:
  - Brief PREMIUMS section never contains rupee amounts
  - PREMIUMS stripped from brief at early stages
  - Calculated numbers block is the only source of financial figures
- **Hallucination prevention (prompt)**:
  - VOICE_RULES: "HALLUCINATION IS FORBIDDEN" with exact fallback phrase
  - ADVISOR_RULES: "Numbers must come from document or CALCULATED NUMBERS block only"
- **CLOSE/PROCEED forbidden list**: Prevents agent from collecting personal data or inventing application steps
- **Objection playbook**: Prevents agent from citing competitors not in document

### Content Restrictions
- Word "death" banned in all responses — "if something were to happen" required
- No urgency-manufacturing, no guilt-tripping, no pressure
- Claims handling: agent can only cite document facts about claim settlement

### API Security
- API keys loaded from `.env` via `python-dotenv` — not hardcoded
- `.env` in `.gitignore`
- CORS: `allow_origins=["*"]` — wide open (demo only)

---

## M. CURRENT STATE (as of 2026-06-05, commit `d954091`)

### What Exists and Works
- PDF upload → full ingestion pipeline (5 output files in ~10-15s)
- Session creation and in-memory management
- Voice pipeline: mic → STT → WebSocket → LLM stream → parallel TTS → merged WAV → playback
- Text pipeline: type → WebSocket → LLM stream → parallel TTS → merged WAV → playback
- TTS text normalisation (₹ amounts, LPA, percentages, age patterns, product names)
- Language detection from voice (STT) and typed text (Unicode script detection)
- Deterministic profile extraction (10 fields via regex)
- Customer profiling with CustomerIntelligence scoring (interest, close_readiness, lead_score)
- Stage machine with Python gates (9 stages, 5 CLOSE substages)
- Risk narrative generation (deterministic, no LLM)
- Cover recommendation engine (deterministic, actuarial constants)
- Quote engine (document-derived premium tables with interpolation, GST, 4 frequencies)
- BM25 retrieval (section-aware chunks, rank-bm25 library)
- Post-conversation evaluation (LLM-generated coaching report)
- Session transcript endpoint
- Frontend: PolicyAI brand, sidebar, voice/text mode toggle, profile chips, evaluation modal, transcript modal

### What Is Partially Working
- **Quote engine**: Works but HDFC has `quote_capability_level=1` (illustrative rows, confidence=inferred, not real table data)
- **NEED_DEVELOPMENT stage**: Architecturally complete. Not verified in live conversation post Iteration 11.
- **RECOMMENDATION stage**: Same status as above.
- **Language switching**: Typed Indian scripts → correct language. Voice: first response after switch sometimes still English.
- **Objection handling**: HANDLE stage intent written; not live-verified.

### Known Issues
- HDFC `plan_type` detected as "other" instead of "term" — affects is_sufficient() and explain topics
- HDFC eligibility brief shows "70-85 years" (GPT extraction error; actual is 18-70 years)
- Smoker/non-smoker premium table split detected but not implemented (all rows tagged as non-smoker)
- Language consistency: LLM may respond in English after voice language switch
- No session persistence (server restart = all sessions lost)
- No human document approval workflow (AUTO_APPROVE_DOCUMENTS=true always)
- No voice activity detection (VAD) — user must press button to start/stop recording
- recommendation_block and policy_quote both injected at CLOSE (two premium sources)

### Technical Debt
- PERSONALIZE stage is vestigial (one-turn bridge to NEED_DEVELOPMENT). Could be removed.
- SUMMARY close substage exists but is skipped in Python (RECOMMENDATION serves that purpose). Dead code.
- `ingest_worker.py` (35 lines) — thin CLI wrapper around ingestion.py. Relationship to production code unclear.
- `regen_briefs.py` — utility to regenerate briefs for existing PDFs. Not integrated into any workflow.
- `run_tests.py` and `direct_test.py` — legacy test scripts, not a test suite.
- `max-life-stpp-axis-documents` in data/ has no `.chunks.json` or `.structure.json` — BM25/quote not available for this PDF.

### Known Limitations
- Session state in-process memory only — not horizontally scalable
- No database — audit trail only in `logs/turns.jsonl` and `logs/sessions.jsonl` (JSONL files)
- No authentication, no multi-tenancy
- No CI/CD, no Docker, no deployment infrastructure
- Frontend is a single 1344-line HTML file (CSS, HTML, JS all in one file)

### Future Risks
- gpt-4o-mini model deprecation (OpenAI frequently deprecates minor versions)
- Sarvam API changes to SDK interface (already experienced once — api_key vs api_subscription_key)
- BM25 retrieval quality degradation for very long or poorly structured PDFs
- CLOSE/PROCEED may still collect application data in edge cases (only prompt-level fix, not structural)
