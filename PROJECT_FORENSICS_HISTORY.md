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
- **Timeline**: Built over approximately one week (2026-05-28 to 2026-06-06)

### Success Criteria (from HANDOFF.md)
1. Upload HDFC Click2Protect Life PDF → agent introduces itself correctly
2. Agent collects customer profile naturally (age, income, family, existing cover, years of support)
3. Agent calculates the customer's protection gap deterministically (gap_engine.py)
4. Agent positions term insurance before pitching
5. Agent makes a direct named recommendation (Click2Protect Life from HDFC)
6. Agent walks through variants and closes assumptively
7. Agent closes naturally and hands off with onboarding link message
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
| LLM can compute gap on the fly | LLM produces inconsistent numbers; multiplier rules vary | Deterministic gap_engine.py built |
| 8-stage flow (INTRODUCE → PROFILE → ...) was correct | Too many stages with overlapping intent; consultative flow felt scripted | Replaced with 7-stage consultative model |

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
- **Problem**: Sarvam-m max_tokens exceeded tier cap (applied to LLM config generally)
- **Fix**: Reduced max_tokens. Slim-prompt retry path if primary fails.

### Commit 26: `34227ba` — 2026-05-30 — feat: switch LLM sarvam-m → OpenAI GPT-4o-mini
- **What**: Formal migration commit. sarvam-m removed. OpenAI SDK added. llm.py rewritten.
- **Note**: Some LLM calls to OpenAI were already present earlier (for ingestion). This commit standardises all conversation calls.

### Commit 27: `d954091` — 2026-06-05 — Major overhaul: sales pipeline, UI polish, hallucination fixes, language switching
- **What**: Largest single commit. Multiple root-cause fixes.
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
  12. detect_language_from_text() — Unicode script detection for typed input
  13. normalize_for_tts() called in /speak endpoint (fixes opener TTS)
  14. Frontend cleanup: lang-badge-sidebar null reference removed
  15. CLOSE substage redesign: turn_in_stage=0 reset prevents same-turn auto-advance

### Commit 28: `e31b3db` — 2026-06-05 — docs: comprehensive handoff document for context transfer
- **What**: PROJECT_ARCHITECTURE.md, PROJECT_FORENSICS_HISTORY.md, PROJECT_DECISIONS_AND_ROADMAP.md, PROJECT_AGENT_TRACEABILITY.md, PROJECT_CODE_INDEX.md written

### Commit 29: `05dd7cd` — 2026-06-05 — fix: stage-scoped temperature, Python rupee guard, grounding rule, ROP on objection only
- **What**: First round of consultative redesign fixes
- **Changes**:
  1. LLM temperature now stage-scoped (lower for data collection, higher for objection handling)
  2. Python rupee guard: `_guard_discovery_numbers()` replaces any ₹ amount in DISCOVERY response
  3. VOICE_RULES Rule 0: GROUNDEDNESS rule added (every rupee amount must have a source)
  4. ROP (Return of Premium): mentioned ONLY when customer explicitly asks "what if I survive?"

### Commit 30: `02c3117` — 2026-06-05 — fix: stage machine compliance, income gate, GREET double-intro, VARIANTS
- **What**: Stage machine correctness pass
- **Changes**:
  1. GREET: single-turn bridge only (no re-introduction); Python forces DISCOVERY after 1 turn
  2. DISCOVERY: income-gated — missing_fields_line only asks about income until income is known
  3. VARIANTS: "Perfect, let's get that set up for you." is the ONLY line on customer agreement
  4. VARIANTS→CLOSE: Python sets close_substage=PROCEED directly (skips PURCHASE_INTENT)
  5. RECOMMEND: age guard — do not confuse years_of_support with age in "at X" framing

### Commit 31: `8792f68` — 2026-06-06 — fix: TTS ranges, age-first discovery, rupee guard tightened, Hindi verbosity
- **What**: Discovery ordering and TTS improvements
- **Changes**:
  1. DISCOVERY: age collected first (before income, before family); missing_fields_line updated
  2. Rupee guard: tightened regex — catches more patterns including "X lakh" and "X crore"
  3. TTS: "E M I S" (all caps, spaced letters) for EMI plural; "100%" → "one hundred percent"
  4. Hindi verbosity: VOICE_RULES now explicitly states 2-sentence limit applies to Hindi responses
  5. gap_engine.py: `_fmt_lakh()` helper added to format lakh values as "₹X crore" / "₹X lakh"

### Commit 32: `a088318` — 2026-06-06 — fix: stage lockup, wrong gap calc, PII collection, premium hallucination
- **What**: Critical correctness fixes for the full consultative flow
- **Changes**:
  1. gap_engine.py: Fixed formula (income_protection_lakh = income_lpa × years, not × 100)
  2. PROCEED: threshold changed to >= 2 (was 1) — prevents same-turn skip to CLOSED
  3. CLOSE/CLOSED: blocks QUESTION_ANSWER interrupts from terminal state
  4. ingestion.py: skips brief/meta regeneration if files already exist
  5. characters.py: Arjun persona updated to "twenty years of field experience"
  6. DISCOVERY: 8-turn fallback escape added to prevent infinite DISCOVERY lockup
  7. profile_extractor.py: added `_extract_years_of_support()` and `_extract_existing_cover()` extractors
  8. memory.py: discovery_sufficient() updated to require age + income_range + existing_cover_lakh + years_of_support
  9. gap_engine.py: `build_gap_calculation()` returns None if income unknown; `gap_to_prompt_block()` added

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
2. Runtime: PREMIUMS section stripped from brief at INTRODUCE/PROFILE/NEED_DEVELOPMENT (now GREET/DISCOVERY) stages in `_build_messages()`
3. HDFC PDF re-ingested with new prompt
**Files**: `backend/ingestion.py:_generate_brief_via_llm()`, `backend/agent.py:_build_messages()`
**Lesson**: Any rupee figure in the brief at early stages will be hallucinated as customer-specific. This is architectural, not prompt-fixable.

### Iteration 5: Profile Gate Never Firing
**Problem**: `is_sufficient()` required `gender` and `financial_goal` among 4 required fields. Customers almost never volunteer these. Gate never fired. Stage machine stuck at PROFILE indefinitely.
**Root cause**: Requirements designed from ideal customer, not real customer utterances.
**Fix**: Simplified to `age + smoker + income_range + (dependents OR marital_status)` for term plans (old design). Later replaced entirely by consultative redesign (Iteration 13).
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

### Iteration 13: 8-Stage Machine Replaced with 7-Stage Consultative Model (Pivot 7)
**Problem**: The INTRODUCE → PROFILE → PERSONALIZE → NEED_DEVELOPMENT → EXPLAIN → RECOMMENDATION → HANDLE → CLOSE flow had multiple issues:
  - PERSONALIZE was a vestigial one-turn bridge stage
  - NEED_DEVELOPMENT was conceptually merged into DISCOVERY in the new design
  - HANDLE was an interrupt stage that duplicated OBJECTIONS logic
  - EXPLAIN for term plans should be VARIANTS (variant selection, not topic explanation)
  - RECOMMENDATION stage intent was vague — no specific product named
**Root cause**: The original 8-stage design predated the requirement to be highly specific: name the plan, name the gap, name the variant.
**Fix**: Full redesign to: GREET → DISCOVERY → GAP_CALC → POSITION → RECOMMEND → VARIANTS → CLOSE
  - GREET: single-turn bridge (no re-intro, just bridge to DISCOVERY)
  - DISCOVERY: collect 4 gating fields (age, income, existing_cover_lakh, years_of_support)
  - GAP_CALC: deterministic gap walkthrough from gap_engine.py
  - POSITION: car-insurance reframe for customers who see term as "wasted money"
  - RECOMMEND: 3-4 sentences naming Click2Protect Life
  - VARIANTS: variant selection + rider questions + assumptive close
  - CLOSE: PURCHASE_INTENT → PROCEED → CLOSED (SUMMARY removed)
  - OBJECTIONS and QUESTION_ANSWER: interrupt stages, return after 1 turn
**Files**: `backend/agent.py`, `backend/conversation_analyzer.py`, `backend/memory.py`, `backend/prompts.py`

### Iteration 14: GREET Re-Introduction Bug
**Problem**: Agent re-introduced itself in GREET stage ("Hi, I'm Arjun from PolicyAI...") even though the opener had already done that.
**Root cause**: GREET stage intent was written as an introduction stage. The opener already handles introduction.
**Fix**: GREET stage intent rewritten — agent only acknowledges customer's opener response and bridges to DISCOVERY. GREET is a single-turn stage forced to DISCOVERY by Python.
**Files**: `backend/prompts.py:STAGE_INTENTS["GREET"]`, `backend/agent.py:_auto_advance_stage()`

### Iteration 15: DISCOVERY Rupee Hallucination
**Problem**: LLM quoted cover amounts or premiums during DISCOVERY when customer asked "how much cover do I need?"
**Root cause**: LLM tried to be helpful but had incomplete data; quote amounts were fabricated.
**Fix**: Two-layer fix:
  1. `_guard_discovery_numbers(text, profile)` in agent.py — Python post-processes LLM response at DISCOVERY stage; any ₹ match triggers replacement with a redirect to the missing field
  2. DISCOVERY missing_fields_line includes explicit instruction: "DO NOT give any cover amount, ballpark, or recommendation without income."
**Files**: `backend/agent.py:_guard_discovery_numbers()`, `backend/agent.py:_build_messages()`

### Iteration 16: DISCOVERY Lockup (8-turn escape)
**Problem**: If profile_extractor fails to parse all 4 required fields for discovery_sufficient() (age + income_range + existing_cover_lakh + years_of_support), the session gets permanently stuck in DISCOVERY.
**Root cause**: Customers phrase responses in ways the regex extractors don't match. Without a fallback, DISCOVERY never ends.
**Fix**: 8-turn fallback escape in `_auto_advance_stage()` — if turn_in_stage >= 8, advance to GAP_CALC (term) or RECOMMEND (savings) regardless.
**Files**: `backend/agent.py:_auto_advance_stage()`

### Iteration 17: Gap Calculation Formula Error
**Problem**: Gap calculation was producing wildly incorrect numbers.
**Root cause**: Formula had `income_protection_lakh = income_lpa * years * 100 / 100` with a comment — the initial version accidentally preserved the division, making it correct, but a refactor removed the comment and fixed what looked like a redundant multiply-divide pair, breaking the formula.
**Fix**: Correct formula is `income_protection_lakh = income_lpa * years` (income in lakh/year × years = lakh total).
**Files**: `backend/gap_engine.py:build_gap_calculation()`

### Iteration 18: PROCEED Same-Turn Skip to CLOSED
**Problem**: When customer agreed in VARIANTS stage, the PROCEED message was delivered but Python immediately advanced to CLOSED in the same turn, so the agent said "Perfect, let's get that set up" and then immediately delivered the CLOSED terminal message in the same response.
**Root cause**: VARIANTS→CLOSE transition incremented turn_in_stage to 1 in the same Python call. PROCEED threshold was >= 1. So on the first PROCEED turn, Python immediately advanced to CLOSED.
**Fix**: PROCEED threshold changed to >= 2 in `_auto_advance_close_substage()`. This gives the PROCEED message one full LLM turn before advancing to CLOSED.
**Files**: `backend/agent.py:_auto_advance_close_substage()`

### Iteration 19: CLOSED Stage Answering Questions
**Problem**: Customer asked a question after the CLOSED message and the agent answered it, restarting the conversation.
**Root cause**: QUESTION_ANSWER interrupt was allowed from all stages including CLOSED. CLOSED stage should be truly terminal.
**Fix**: In `apply_analysis()`, interrupt stages (QUESTION_ANSWER, OBJECTIONS) blocked when `current == "CLOSE" and memory.close_substage == "CLOSED"`.
**Files**: `backend/conversation_analyzer.py:apply_analysis()`

### Iteration 20: ingestion.py Revert-on-Upload Bug
**Problem**: Re-uploading a PDF after making manual edits to the brief or metadata caused those edits to be overwritten.
**Root cause**: ingestion.py regenerated brief and metadata on every upload, even if the files existed.
**Fix**: Added skip logic — if `{name}.brief.txt` and `{name}.meta.json` already exist, skip regeneration.
**Files**: `backend/ingestion.py:ingest()`

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
- v7: Skip-if-exists logic to prevent revert on re-upload
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
- v10 (Pivot 7): Complete redesign to GREET→DISCOVERY→GAP_CALC→POSITION→RECOMMEND→VARIANTS→CLOSE; discovery_sufficient() gates on 4 fields; interrupt stages (OBJECTIONS, QUESTION_ANSWER) return after 1 turn; GREET is single-turn only

### Feature: Customer Profiling
**Why introduced**: Personalisation requires knowing the customer.
**Evolution**:
- v1: LLM-extracted only (implicit in conversation history)
- v2: CustomerProfile dataclass with 5 fields
- v3: profile_extractor.py — deterministic regex extraction before every LLM call
- v4: 10 profile fields (added policy_term, payment_frequency, liabilities_lakh, cover_amount_override_lakh)
- v5: 12 profile fields (added years_of_support, existing_cover_lakh — both gate discovery_sufficient)
- v6: discovery_sufficient() redesigned — 4 hard gates: age + income_range + existing_cover_lakh + years_of_support
  - existing_cover_lakh = 0.0 means "no insurance" explicitly answered
  - None means not asked yet (blocks gate)

### Feature: Gap Engine (NEW)
**Why introduced**: LLM computed gap inconsistently. "10x income" rule was being applied wrong. No transparency to customer on how the gap was calculated.
**Implementation**: `gap_engine.py` — deterministic Python:
  - `build_gap_calculation(profile)` → dict with income_lpa, years_of_support, income_protection_lakh, liabilities_lakh, existing_cover_lakh, gap_lakh, gap_display, spoken_walkthrough, assumptions_made
  - `gap_to_prompt_block(gap)` → ready-to-inject prompt block at GAP_CALC stage
  - Formula: gap_lakh = income_lpa × years_of_support + liabilities_lakh − existing_cover_lakh
  - Defaults: 20 years, 0 liabilities, 0 existing cover if not collected
  - Stores computed gap_lakh in `memory.intelligence.gap_lakh` for use in later stages

### Feature: Risk Narrative
**Why introduced**: LLM personalises generically. Need to force specific vulnerability framing.
**How**: `build_risk_narrative()` — pure deterministic Python, converts profile fields into a 5-6 sentence financial vulnerability story. Injected into system prompt at RECOMMEND, VARIANTS, EXPLAIN, CLOSE, OBJECTIONS.
**Why deterministic**: LLM-generated narratives varied and sometimes inaccurate. Deterministic = auditable, consistent.

### Feature: Quote Engine
**Why introduced**: LLM hallucinated premiums. Insurance customers trust numbers or don't buy.
**Two-tier design**:
1. `recommendation.py` — industry benchmark estimates (income × multiplier, actuarial constants). Injected at RECOMMEND/VARIANTS/EXPLAIN/CLOSE.
2. `quote_engine.py` — document-derived from structure.json. Interpolates premium tables, applies GST 18%, all 4 frequency breakdowns. Injected at CLOSE only.
**Critical**: If smoker=None, premium estimate is suppressed entirely. Never assumes non-smoker.

### Feature: BM25 Retrieval
**Why introduced**: Keyword bag-of-words scored poorly on multi-word insurance queries.
**Implementation**: `bm25_store.py` — section-aware chunking (detects insurance document headers), BM25Okapi scoring, fallback to first N chunks if no matches.
**Why not vector search**: No external service, no cost, works offline, insurance vocabulary is keyword-rich.

### Feature: Character Registry
**Why introduced**: Sales persona must be consistent — not just prompt text but emotional handling.
**Characters**:
- `arjun` — high-performing male advisor, 30s, energetic and consultative, `dev` voice; persona updated to "twenty years of field experience"
- `lalita` — patient female advisor, 40s, empathetic and trust-building, `ritu` voice (defined but inactive in UI)
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
  - Conversation: stage-scoped temperature (lower at GREET/DISCOVERY, higher at VARIANTS/OBJECTIONS); max_tokens=600
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
- **Text normalisation**: `normalize_for_tts()` called before every TTS call
  - "EMIs" → "E M I S" (spaced capital letters)
  - "100%" → "one hundred percent"
  - ₹ amounts, LPA, product names
- **Constraint**: Required (Sarvam AI demo requirement)

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
- **Fix**: turn_in_stage >= 2 → force to PROFILE (now replaced by GREET single-turn advance)

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

### BUG-12: GREET re-introducing agent
- **Symptom**: After opener played, GREET stage LLM response said "Hi, I'm Arjun from PolicyAI" again
- **Root cause**: GREET stage intent was written as if GREET was the opener
- **Fix**: GREET intent rewritten to acknowledge and bridge only; Python forces DISCOVERY after 1 turn

### BUG-13: DISCOVERY rupee hallucination
- **Symptom**: Agent quoted cover amounts ("you'll need about ₹1 crore") when customer asked during DISCOVERY
- **Root cause**: LLM tried to answer helpfully without data
- **Fix**: `_guard_discovery_numbers()` Python post-processor + income-gated missing_fields_line

### BUG-14: DISCOVERY infinite lockup
- **Symptom**: Session stuck in DISCOVERY permanently when customer's phrasing didn't match extractors
- **Root cause**: discovery_sufficient() required 4 fields; regex extractors missed some phrasings
- **Fix**: 8-turn fallback escape added to _auto_advance_stage()

### BUG-15: Gap calculation formula error
- **Symptom**: Gap amounts were either 100x too large or 100x too small
- **Root cause**: Residual `* 100 / 100` in formula was removed without understanding intent
- **Fix**: Correct formula confirmed as `income_protection_lakh = income_lpa * years`

### BUG-16: PROCEED same-turn skip to CLOSED
- **Symptom**: Agent said PROCEED message and CLOSED message in same response
- **Root cause**: VARIANTS→CLOSE transition set turn_in_stage=1; PROCEED threshold was >=1
- **Fix**: PROCEED threshold changed to >= 2

### BUG-17: CLOSED state answers questions
- **Symptom**: After closing, customer could ask a question and agent would re-engage
- **Root cause**: QUESTION_ANSWER interrupts were allowed from all stages
- **Fix**: Interrupt blocked when close_substage == "CLOSED"

### BUG-18: Brief overwritten on re-upload
- **Symptom**: Manual edits to brief.txt lost on PDF re-upload
- **Root cause**: ingestion.py regenerated files unconditionally
- **Fix**: Skip-if-exists logic added

### BUG-19: Arjun age claim mismatch
- **Symptom**: Arjun persona said "eight years of experience" but was framed as "early 30s" — implied starting at 22, plausible but inconsistent with the assertiveness expected of a top closer
- **Fix**: Updated to "twenty years of field experience"

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
- **Learned**: Insurance sales requires at minimum: intro, profiling/discovery, gap calculation, positioning, recommendation, variant selection, close.

### Failed: LLM-computed gap on the fly
- **Attempted**: Ask LLM to compute "10x income" or "15x income" gap in system prompt instructions
- **Why tried**: Seemed simple — LLM can do basic arithmetic
- **Why failed**: LLM applied the multiplier inconsistently; sometimes used 10x, sometimes 15x; sometimes confused years_of_support with the multiplier; no transparency to customer on methodology
- **Learned**: Any calculation that needs to be communicated to the customer should be deterministic Python, not LLM arithmetic

---

## J. PIVOTS

### Pivot 1: Sarvam-m → OpenAI gpt-4o-mini (LLM)
- **Trigger**: Immediate API failure
- **Impact**: All LLM calls now go to OpenAI. Sarvam APIs remain for STT/TTS only.

### Pivot 2: Generic stages → Consultative sales stages (first iteration)
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
- **To**: Runtime strip of PREMIUMS section from brief at early stages
- **Impact**: Permanently architectural. No rupee amounts possible at early stages.

### Pivot 5: LLM-only profile extraction → deterministic regex + LLM
- **Trigger**: LLM sometimes missed explicit profile statements; profile gate never fired
- **From**: LLM-implicit profile understanding
- **To**: profile_extractor.py runs deterministic regex on every user message BEFORE LLM call
- **Impact**: Profile fields collected reliably. discovery_sufficient() can now fire correctly.

### Pivot 6: Free-form LLM stage control → Python-gated stage machine
- **Trigger**: LLM stuck in stages, skipping stages, not advancing
- **From**: Stage transitions entirely LLM-controlled via META tags
- **To**: LLM signals transitions; Python enforces via _auto_advance_stage() + conversation_analyzer.py gates
- **Impact**: Predictable stage progression. Python escape hatches prevent permanent stucks.

### Pivot 7: 8-stage model (INTRODUCE→HANDLE) → 7-stage consultative model (GREET→VARIANTS) (Major Redesign)
- **Trigger**: Multiple issues with old 8-stage design; agent wasn't naming the product, wasn't calculating the gap, wasn't doing assumptive close
- **From**: INTRODUCE → PROFILE → PERSONALIZE → NEED_DEVELOPMENT → EXPLAIN → RECOMMENDATION → HANDLE → CLOSE
- **To**: GREET → DISCOVERY → GAP_CALC → POSITION → RECOMMEND → VARIANTS → CLOSE (term); GREET → DISCOVERY → RECOMMEND → EXPLAIN → CLOSE (savings); OBJECTIONS / QUESTION_ANSWER as interrupt stages
- **Key changes**:
  - GREET: 1-turn bridge only (no re-intro)
  - DISCOVERY: 4-field gate (age + income + existing_cover_lakh + years_of_support); income-gated priority; 8-turn escape
  - GAP_CALC: entirely new — deterministic gap walkthrough via gap_engine.py
  - POSITION: car-insurance reframe; skippable with position_skip=true
  - RECOMMEND: 3-4 sentences naming specific product
  - VARIANTS: replaces EXPLAIN for term plans; assumptive close built in; PURCHASE_INTENT skipped on agreement
  - CLOSE: SUMMARY removed; starts at PURCHASE_INTENT; PROCEED threshold >= 2; CLOSED blocks interrupts
  - discovery_sufficient(): redesigned with 4 hard gates
  - profile_extractor.py: 2 new extractors (years_of_support, existing_cover_lakh)
  - gap_engine.py: entirely new file
  - memory.py: 3 new CustomerProfile fields (existing_cover_lakh, years_of_support, chosen_variant)
  - conversation_analyzer.py: _LLM_ALLOWED_TRANSITIONS rewritten for new stage set; position_skip field added
- **Impact**: Complete rewrite of the sales flow. Old sessions on old code would follow legacy stage handling via compatibility shim.

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
- **Skip-if-exists**: Re-uploading same PDF does not regenerate existing brief/metadata files.

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
  - PREMIUMS stripped from brief at early stages (GREET/DISCOVERY)
  - Calculated numbers block and gap_engine.py block are the only sources of financial figures
  - `_guard_discovery_numbers()` Python post-processor hard-blocks ₹ amounts at DISCOVERY
- **Hallucination prevention (prompt)**:
  - RULE 0 — GROUNDEDNESS: every rupee amount must exist in PRODUCT KNOWLEDGE, CALCULATED NUMBERS, or GAP CALCULATION block
  - VOICE_RULES: "HALLUCINATION IS FORBIDDEN" with exact fallback phrase
  - ADVISOR_RULES: "Numbers must come from the document or CALCULATED NUMBERS block only"
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

## M. CURRENT STATE (as of 2026-06-06, commit `a088318`)

### What Exists and Works
- PDF upload → full ingestion pipeline (5 output files in ~10-15s); skip-if-exists prevents revert
- Session creation and in-memory management
- Voice pipeline: mic → STT → WebSocket → LLM stream → parallel TTS → merged WAV → playback
- Text pipeline: type → WebSocket → LLM stream → parallel TTS → merged WAV → playback
- TTS text normalisation (₹ amounts, LPA, percentages, EMIs, age patterns, product names)
- Language detection from voice (STT) and typed text (Unicode script detection)
- Per-turn ⚠️ LANGUAGE THIS TURN reminder in system prompt
- Deterministic profile extraction (12 fields via regex including years_of_support, existing_cover_lakh)
- Customer profiling with CustomerIntelligence scoring (interest, close_readiness, gap_lakh, lead_score)
- Stage machine with Python gates: GREET→DISCOVERY→GAP_CALC→POSITION→RECOMMEND→VARIANTS→CLOSE (term)
- 8-turn DISCOVERY fallback escape; GREET forced after 1 turn; income-gated DISCOVERY priority
- Deterministic gap calculation (gap_engine.py); gap_lakh stored in memory.intelligence
- Rupee guard in DISCOVERY (_guard_discovery_numbers)
- Risk narrative generation (deterministic, no LLM)
- Cover recommendation engine (deterministic, actuarial constants)
- Quote engine (document-derived premium tables with interpolation, GST, 4 frequencies)
- BM25 retrieval (section-aware chunks, rank-bm25 library)
- CLOSE substage machine: PURCHASE_INTENT → PROCEED (2 turns) → CLOSED; FEEDBACK path
- CLOSED blocks QUESTION_ANSWER/OBJECTIONS interrupts
- Post-conversation evaluation (LLM-generated coaching report)
- Session transcript endpoint
- Frontend: PolicyAI brand, sidebar, voice/text mode toggle, profile chips, evaluation modal, transcript modal

### What Is Partially Working
- **Quote engine**: Works but HDFC has `quote_capability_level=1` (illustrative rows, not real table data)
- **Language switching**: Typed Indian scripts → correct language. Voice: first response after switch sometimes still English.
- **POSITION skip**: position_skip=true META field implemented; not extensively tested

### Known Issues
- HDFC `plan_type` detected as "other" instead of "term" — affects discovery flow and explain topics
- HDFC eligibility brief shows "70-85 years" (GPT extraction error; actual is 18-70 years)
- Smoker/non-smoker premium table split detected but not implemented (all rows tagged as non-smoker)
- Language consistency: LLM may respond in English after voice language switch
- No session persistence (server restart = all sessions lost)
- No human document approval workflow (AUTO_APPROVE_DOCUMENTS=true always)
- No voice activity detection (VAD) — user must press button to start/stop recording
- recommendation_block and policy_quote both injected at CLOSE (two premium sources)
- Arjun "twenty years of field experience" with "early 30s" is implausible — intentional creative choice

### Technical Debt
- Old stage names (INTRODUCE, PROFILE, PERSONALIZE, NEED_DEVELOPMENT, RECOMMENDATION, HANDLE) still referenced in STAGE_INTENTS dict as stub entries for backward compatibility
- SUMMARY close substage intent exists in prompts.py but the close_substage never starts there — close_substage initial value is PURCHASE_INTENT
- `ingest_worker.py` (orphaned) — not used in current flow
- `regen_briefs.py` — utility to regenerate briefs for existing PDFs. Not integrated into any workflow.
- `run_tests.py` and `direct_test.py` — legacy test scripts, not a test suite.
- `max-life-stpp-axis-documents` in data/ has no `.chunks.json` or `.structure.json` — BM25/quote not available for this PDF.

### Known Limitations
- Session state in-process memory only — not horizontally scalable
- No database — audit trail only in `logs/turns.jsonl` and `logs/sessions.jsonl` (JSONL files)
- No authentication, no multi-tenancy
- No CI/CD, no Docker, no deployment infrastructure
- Frontend is a single HTML file (CSS, HTML, JS all in one file)

### Future Risks
- gpt-4o-mini model deprecation (OpenAI frequently deprecates minor versions)
- Sarvam API changes to SDK interface (already experienced once — api_key vs api_subscription_key)
- BM25 retrieval quality degradation for very long or poorly structured PDFs
- CLOSE/PROCEED may still collect application data in edge cases (only prompt-level fix, not structural)
