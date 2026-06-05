# PolicyAI — Complete Engineering & Product Handover Document
*Generated from live codebase. Written for a new AI system with zero prior context.*
*Project root: `/Users/ud/sarvam-insurance-agent`*

---

## SECTION 1 — PROJECT OVERVIEW

### Problem Being Solved

Insurance sales in India is broken in a specific way. When a customer calls to enquire about a policy, the advisor either reads from a brochure generically or asks rote questions disconnected from the customer's actual situation. The customer receives no personalisation, no risk narrative, no real recommendation — just product features. Most calls end without a sale because the advisor never developed the customer's need or made a compelling case.

Separately, insurance sales managers uploading a new product face a cold-start problem: advisors need to learn the product, understand its pricing, and be ready to explain it before they can sell it. This typically takes days of training.

### Why This Project Was Started

This project was built as a demo for Sarvam AI, showcasing their STT and TTS APIs (saaras:v3 and bulbul:v3) combined with OpenAI's LLM capability. The business case: an AI sales agent that a manager can equip in minutes by uploading a PDF, and that then conducts personalised insurance sales conversations over voice or text.

### End Vision

An AI insurance sales advisor that:
1. Accepts any Indian insurance PDF upload
2. Ingests it and extracts pricing, coverage, eligibility, and sales positioning
3. Conducts a natural, personalised voice or text sales conversation
4. Understands the customer's financial situation and develops their sense of need
5. Recommends the right cover amount and generates a real quote from document data
6. Closes the sale naturally and hands off to onboarding

### Target User

Insurance sales teams and their managers. The manager uploads the product PDF. The agent then handles customer-facing conversations. The primary customer for the demo is Sarvam AI itself, who wants to showcase their speech APIs in a real enterprise application.

### Business Value

- Eliminates cold-start training time for new products
- Scales personalised sales conversations without additional advisors
- Consistent product knowledge across all conversations
- Voice-first, which suits the Indian market where most insurance sales happen over phone

### What Success Looks Like

A complete end-to-end demo where:
1. Upload HDFC Click2Protect Life PDF
2. Agent introduces itself, collects customer profile naturally
3. Agent develops need (makes customer feel their financial vulnerability)
4. Agent explains the plan tied to the customer's specific situation
5. Agent makes a direct personal recommendation
6. Agent generates a real quote with calculated premium
7. Agent closes naturally and hands off
8. Agent speaks clearly in English, Hindi, or Hinglish depending on the customer

---

## SECTION 2 — PRODUCT CONCEPT

### What the User Uploads

A PDF of any Indian insurance product brochure or policy document. The system is designed for life insurance (term, ULIP, savings), health insurance, and pension plans. The upload goes through an ingestion pipeline that extracts all useful information and prepares it for the agent.

### What Happens After Upload

The ingestion pipeline runs five operations and produces five output files per document:
- `{name}.txt` — full extracted text from the PDF
- `{name}.meta.json` — structured metadata (plan name, company, plan type, one-line pitch)
- `{name}.brief.txt` — an LLM-generated advisor cheat-sheet (coverage, eligibility, benefits, exclusions — no rupee amounts)
- `{name}.structure.json` — structured pricing data (premium tables, eligibility bands, GST rate, payment frequency rules)
- `{name}.chunks.json` — BM25-indexed text chunks for document retrieval

After ingestion, a session is created and the user can start a conversation.

### How the Agent Works

The agent is an `AgentSession` object that combines:
- An LLM client (OpenAI gpt-4o-mini) for conversation
- A document store (BM25 retrieval + structure JSON)
- Session memory (stage, customer profile, conversation history)
- Deterministic engines (cover recommendation, premium quote)

Every user message triggers:
1. Deterministic profile extraction (regex, no LLM)
2. Language detection from text script or STT probability
3. System prompt assembly (persona + product knowledge + customer state + stage intent)
4. LLM call — raw response with embedded META tag
5. META tag parsing to extract stage signals
6. Stage machine advancement (Python-gated)
7. Response returned to user

### Voice Flow

```
User presses mic → browser captures audio (webm)
→ POST /transcribe → Sarvam saaras:v3 → transcript + language_code
→ WebSocket /ws/chat → AgentSession.chat_stream()
→ LLM tokens stream back sentence by sentence
→ Each sentence sent as text frame to browser immediately
→ After all sentences: parallel TTS synthesis for each sentence
→ WAV files merged into one continuous audio blob
→ Binary frames streamed to browser
→ Browser plays audio
```

### Chat Flow

```
User types message → WebSocket /ws/chat
→ Same pipeline minus STT
→ Text bubbles appear as agent streams
→ Audio plays when streaming is complete
```

### Policy Understanding

The agent understands the uploaded policy through two mechanisms:

**Sales brief** — injected as "YOUR PRODUCT KNOWLEDGE" into every LLM call. Contains coverage, eligibility, death benefit, maturity benefit, riders, tax benefits, exclusions, and pitch. Written in plain English for a sales advisor. The PREMIUMS section describes payment structure only — no rupee figures. This is a hard constraint: marketing pricing figures in the brief cause premium hallucination.

**BM25 retrieval** — at every turn, the top 3 BM25 chunks most relevant to the user's question are retrieved from `{name}.chunks.json` and injected as "DOCUMENT REFERENCE". Handles specific customer questions about terms and conditions.

### Sales Interaction

The conversation follows a defined stage flow:
`INTRODUCE → PROFILE → NEED_DEVELOPMENT → EXPLAIN → RECOMMENDATION → CLOSE`

Each stage has a specific intent:
- **INTRODUCE**: 2-sentence overview, ask permission to proceed
- **PROFILE**: Collect minimum required fields for the plan type
- **NEED_DEVELOPMENT**: Help the customer feel their financial vulnerability before presenting the product
- **EXPLAIN**: Explain plan features tied to the customer's specific risk narrative
- **RECOMMENDATION**: Make a direct personal recommendation, ask for commitment
- **CLOSE**: Onboarding handoff or feedback collection

### Quoting Capability

Two layers:

**Benchmark estimation** (`recommendation.py`): Uses industry-standard actuarial constants. Income × multiplier for cover. Age-loaded premium estimate. Smoker loading. Explicitly labelled "estimate". Injected at EXPLAIN, RECOMMENDATION, CLOSE.

**Document-derived quote** (`quote_engine.py`): Reads premium tables from `{name}.structure.json`. Interpolates between known data points. Scales to recommended cover. Applies GST 18%. All 4 frequency breakdowns. Fires at RECOMMENDATION and CLOSE if `quote_capability_level >= 1`.

### Closing Capability

CLOSE stage substates: `PURCHASE_INTENT → PROCEED or FEEDBACK → CLOSED`
- PROCEED: delivers handoff message only ("I will share payment and onboarding link via SMS/email") — no data collection
- FEEDBACK: collects decline reason gracefully

### Intended Customer Journey

1. Manager uploads PDF → ingestion (~10-15s) → session ready
2. Customer opens UI → clicks Start Session
3. Agent: "Hi, I'm Arjun from PolicyAI. I've gone through the [plan name] policy document..."
4. Agent gives 2-sentence overview → asks permission
5. Agent collects profile: age → smoker → income → family → existing coverage (2 per turn max, only missing fields)
6. Python advances to NEED_DEVELOPMENT when profile sufficient
7. Agent asks one question making customer feel financial vulnerability
8. After 1-2 exchanges → EXPLAIN
9. Agent explains 4 topics, each anchored to customer's specific risk narrative with calculated numbers
10. When close_readiness >= 70, Python advances to RECOMMENDATION
11. Agent: "Given that [specific situation], I genuinely think this plan makes sense for you. Would you like to take this forward?"
12. Customer yes → PROCEED → onboarding handoff
13. Customer no → FEEDBACK → graceful exit

---

## SECTION 3 — INITIAL APPROACH

### Original Architecture

The baseline had: basic FastAPI, keyword RAG, Sarvam-m LLM (broken), 4-stage machine (GREETING → DISCOVERY → PITCH → CLOSE), no profile extraction, no quote engine, no structured product JSON, text-only interface.

### Original Assumptions and Why They Were Wrong

**Sarvam-m would work**: It returned API errors constantly. Removed entirely. All LLM calls moved to OpenAI gpt-4o-mini.

**Simple keyword RAG would be sufficient**: Insufficient for complex queries. BM25 with section-aware chunking was added.

**4-stage machine would cover the arc**: Too coarse. No guidance on personalisation. No need development. Agent felt like FAQ bot.

**LLM would personalise if given profile data**: The most consequential wrong assumption. The LLM will acknowledge profile data once and continue generically. Explicit mechanisms required: a risk narrative computed from profile and injected as a story, stage intents that mandate using specific profile values.

### Models Selected and Tradeoffs

- **gpt-4o-mini**: Low cost, low latency, 128k context. Tradeoff: strong trained priors sometimes override stage instructions.
- **saaras:v3**: Required for Sarvam demo. Good codemix support.
- **bulbul:v3**: Required for Sarvam demo. Good Indian voices.
- **BM25**: No external service, no embedding cost, works offline. Tradeoff: no semantic search.
- **Deterministic quote engine**: Eliminates hallucinated premiums. Tradeoff: requires well-structured document tables.

---

## SECTION 4 — EVOLUTION OF THE SYSTEM

### Iteration 1: Sarvam-m Removed
**Problem**: API errors on every LLM call. **Fix**: All calls to OpenAI gpt-4o-mini.

### Iteration 2: Audit Fixes (I-1 through I-9, I-14)
**Problems**: smoker=None treated as non-smoker; context limits too low; INTRODUCE stuck; LLM jumping PROFILE→EXPLAIN prematurely; blank responses.
**Fixes**: Bug fixes across recommendation.py, agent.py, memory.py, conversation_analyzer.py. Context limits raised 3500/1500. Python escape from INTRODUCE after 2 turns. I-9 gate blocks PROFILE→EXPLAIN/CLOSE.

### Iteration 3: BM25 + Ingestion Pipeline
**Problem**: No structured product data, poor retrieval.
**Added**: table_parser.py, structure_builder.py, bm25_store.py. All 5 output files. Updated rag.py.

### Iteration 4: Quote Engine + 10 Profile Fields
**Problem**: LLM hallucinating premiums.
**Added**: cover_engine.py, quote_engine.py. 4 new profile fields. Quote wired at CLOSE.

### Iteration 5: Close Stage Redesign
**Problem**: CLOSE substage buggy, skipping substages.
**Fix**: 5-substage machine. Critical: `turn_in_stage=0` reset on substage transition prevents same-turn auto-advance.

### Iteration 6: Frontend Redesign
**Changes**: Removed Lalita (only Arjun), removed Live Intelligence sidebar, fixed chat bubbles, fixed `#lang-badge-sidebar` null that was preventing TTS from firing on session start, renamed upload button, switched to `dev` voice, pace 1.3→1.1.

### Iteration 7: Opener Redesign
**Problem**: Agent introducing as "from HDFC Life" — wrong brand.
**Fix**: Opener is now "Hi, I'm Arjun from PolicyAI..." — no company name, no one_line_pitch. Only depends on plan_name.

### Iteration 8: Language Detection for Typed Text
**Problem**: Language switch only worked for voice input (STT-detected).
**Fix**: `detect_language_from_text()` using Unicode script ranges in agent.py. Commits at confidence=1.0 for typed non-Latin text.

### Iteration 9: normalize_for_tts in Opener
**Problem**: GET /speak endpoint bypassed normalize_for_tts(). "Click2Protect" spelled letter by letter in opener.
**Fix**: normalize_for_tts() now called in /speak endpoint.

### Iteration 10: New Sales Stages
**Added**: NEED_DEVELOPMENT and RECOMMENDATION stages. `build_risk_narrative()` — deterministic profile→vulnerability story. Updated all stage intents. Updated conversation_analyzer.py.
**Problem discovered later**: These stages were never reached because PROFILE was getting stuck (see Iteration 11).

### Iteration 11: Root Cause Fixes (Current State)
**Root causes identified and fixed**:
1. Brief PREMIUMS section contained "₹22/day" — LLM presented as customer premium at PROFILE stage
2. `is_sufficient()` required 4 of 5 fields including gender/financial_goal — never fired
3. PROFILE→PERSONALIZE not gated — LLM could exit PROFILE early; when LLM went off-script, stage stuck forever
4. No mechanism telling LLM exactly which profile fields were still missing

**Fixes**:
- ingestion.py: PREMIUMS section now payment structure only, no rupee examples
- agent.py: Strip PREMIUMS section from brief at INTRODUCE/PROFILE/NEED_DEVELOPMENT runtime
- agent.py: missing_fields_line injected at PROFILE stage
- memory.py: is_sufficient() simplified to age + smoker + income + family context
- conversation_analyzer.py: PROFILE→PERSONALIZE gated on minimum fields
- HDFC PDF re-ingested with corrected prompt

---

## SECTION 5 — CURRENT ARCHITECTURE

### Component Map

```
Browser / Phone
     │  WebSocket / HTTP
     ▼
FastAPI (main.py)
  ├── POST /upload        → _run_ingestion() → ingestion.py → 5 output files
  ├── GET  /status/{job}  → poll ingestion job status
  ├── POST /chat          → AgentSession.chat() [plain JSON]
  ├── WebSocket /ws/chat  → run_voice_pipeline() [streaming text + audio]
  ├── POST /transcribe    → stt.py → Sarvam saaras:v3
  ├── GET  /speak         → normalize_for_tts() → tts.py → Sarvam bulbul:v3
  ├── POST /evaluate      → evaluate_session() → GPT-4o-mini report
  ├── GET  /transcript    → session turn log
  └── DELETE /session     → cleanup

AgentSession (agent.py)
  ├── SessionMemory (memory.py)
  ├── DocumentStore (rag.py) → BM25Store (bm25_store.py)
  ├── LLMClient (llm.py) → OpenAI gpt-4o-mini
  ├── build_risk_narrative() → deterministic profile→story
  ├── cover_engine.py → deterministic cover recommendation
  └── quote_engine.py → deterministic premium quote

Ingestion (ingestion.py):
  pdfplumber → text + tables
  → table_parser.py (premium table extraction)
  → structure_builder.py (structure.json)
  → bm25_store.py (chunks.json)
  → gpt-4o-mini ×2 (meta.json + brief.txt)
```

### Data Flow Per Turn

```
1. User message arrives (text or transcribed audio)
2. detect_language_from_text() — Unicode script detection
3. extract_profile_fields() — deterministic regex, 10 fields
4. memory.customer_profile.apply_updates()
5. _build_messages():
   a. Strip PREMIUMS from brief if stage in (INTRODUCE, PROFILE, NEED_DEVELOPMENT)
   b. Compute missing_fields_line if stage == PROFILE
   c. BM25 retrieve top 3 chunks for user_text
   d. build_risk_narrative() if stage in (NEED_DEVELOPMENT, EXPLAIN, RECOMMENDATION, CLOSE, HANDLE)
   e. build_recommendation_block() if stage in (EXPLAIN, RECOMMENDATION, CLOSE)
   f. generate_quote() if stage in (RECOMMENDATION, CLOSE) and structure available
   g. Assemble MAIN_SYSTEM_PROMPT
   h. Append last 6 turns of history + current user message
6. LLMClient.complete() or .stream()
7. parse_meta_tag() → (clean_text, TurnAnalysis)
8. apply_analysis() → update stage, emotional_state, close_readiness, objections
9. _auto_advance_stage() → Python-gated transitions
10. Return clean_text
```

### System Prompt Structure (assembled every turn)

```
{persona} + {style_guide} + {emotional_guide}
YOUR PRODUCT KNOWLEDGE: {sales_brief}         ← PREMIUMS stripped at early stages
DOCUMENT REFERENCE: {document_context}         ← BM25 top 3 chunks
LANGUAGE RULE: mandatory if/then rules         ← hard rule, not suggestion
CUSTOMER PROFILE COLLECTED SO FAR: {profile}
{missing_fields_line}                           ← only at PROFILE stage
{risk_narrative}                                ← only at sales-active stages
WHAT ELSE YOU KNOW: {memory_summary}
{recommendation_block}                          ← EXPLAIN/RECOMMENDATION/CLOSE
{policy_quote}                                  ← RECOMMENDATION/CLOSE
CURRENT STAGE: {stage}
{explain_subtopic_line}                         ← EXPLAIN only
{close_substage_line}                           ← CLOSE only
YOUR GOAL THIS TURN: {stage_intent}
SPEAKING RULES: {voice_rules}
ADVISOR RULES: {advisor_rules}
OBJECTIONS: {deflection_playbook}
META TAG INSTRUCTION: {meta_tag_instruction}
```

**IMPORTANT**: Product knowledge (brief) comes before stage instructions. This means the LLM processes it first and forms strong priors before reading the stage intent. Critical constraints must either appear early OR be enforced by removing data from the prompt (e.g. stripping PREMIUMS section).

### Stage Machine

```
INTRODUCE
  → PROFILE  (LLM signals, Python allows)
  → PROFILE  (Python forces after 2 turns)

PROFILE
  → PERSONALIZE  (LLM signals — gated: age + smoker or income required)
  → NEED_DEVELOPMENT  (Python forces when is_sufficient() True)
  BLOCKED: LLM cannot jump to EXPLAIN, CLOSE, RECOMMENDATION

PERSONALIZE
  → NEED_DEVELOPMENT  (Python forces after 1 turn)

NEED_DEVELOPMENT
  → EXPLAIN  (LLM signals after 1-2 exchanges)
  → EXPLAIN  (Python forces after 2 turns)
  BLOCKED: LLM cannot jump to RECOMMENDATION, CLOSE

EXPLAIN
  → RECOMMENDATION  (LLM signals after final topic)
  → RECOMMENDATION  (Python forces when close_readiness >= 70 AND turn_in_stage >= 2)
  BLOCKED: LLM cannot jump to CLOSE directly (intercepted, redirected to RECOMMENDATION)

RECOMMENDATION
  → CLOSE  (Python forces after 1 turn, substage=PURCHASE_INTENT)

HANDLE  (any stage → HANDLE on objection)
  → returns to previous stage after 1 turn

QUESTION_ANSWER  (any stage → QA on direct question)
  → returns to previous stage after 1 turn

CLOSE substage machine:
  PURCHASE_INTENT → PROCEED  (LLM signals on customer yes)
  PURCHASE_INTENT → FEEDBACK  (LLM signals on customer no)
  PROCEED → CLOSED  (Python forces after 1 turn)
  FEEDBACK → CLOSED  (LLM signals, Python forces after 3 turns)
```

### Memory Model (SessionMemory in memory.py)

- `stage`, `previous_stage`, `return_to_stage`, `turn_in_stage`
- `close_substage`
- `detected_language`, `language_confidence`
- `emotional_state` (curious/engaged/hesitant/resistant/anxious/satisfied)
- `customer_profile` (CustomerProfile — 13 fields)
- `explain_topics` (dynamic list based on plan_type + profile)
- `explain_subtopic_index`
- `intelligence` (CustomerIntelligence: interest_level 0-100, close_readiness 0-100, objections list, buying_intent)
- `turn_log` (full history)

**CustomerProfile fields**: age, gender, marital_status, dependents, smoker, existing_coverage, financial_goal, income_range, health_conditions, policy_term, payment_frequency, liabilities_lakh, cover_amount_override_lakh

**is_sufficient() for term plan**: age + smoker + income_range + (dependents or marital_status). Gender and financial_goal NOT required.

### Recommendation Logic

`recommendation.py` (benchmark-based, no LLM):
- Cover: income_lpa × multiplier (10/15/20x based on dependents) + liabilities - existing_coverage
- Premium: ₹8,500/crore/year base, 3.5% compound per year above age 25, 65% smoker loading
- Returns None for premium if smoker=None (does not estimate)
- Injected at EXPLAIN, RECOMMENDATION, CLOSE

`quote_engine.py` (document-derived, no LLM):
- Reads premium_tables from structure.json
- Interpolates age/term data points
- Scales to recommended cover
- GST 18%, 4 frequency breakdowns
- Injected at RECOMMENDATION, CLOSE only

### Retrieval Logic

BM25Okapi index, section-aware chunks, top 3 per turn, keyword fallback if store unavailable.

---

## SECTION 6 — MODEL SELECTION

### OpenAI gpt-4o-mini
- **Purpose**: All conversation, metadata extraction, brief generation, evaluation
- **Temperature**: 0.7 (conversation), 0.1 (metadata), 0.0 (table extraction), 0.3 (brief)
- **Max tokens**: 600 (conversation), 200-900 (extraction)
- **Known limitation**: Strong trained priors override stage instructions in long prompts. Important constraints must be structural (data removal) not just instructional (prompt rules).

### Sarvam saaras:v3
- **Purpose**: STT — customer voice to text
- **Mode**: codemix (handles Hindi-English mixing)
- **CRITICAL**: Always pass `language_code="unknown"`. Specific codes cause language_probability=None.
- **Language commit**: ≥0.85 single detection, or two consecutive ≥0.70

### Sarvam bulbul:v3
- **Purpose**: TTS — agent text to voice
- **Voice**: `dev` (male, for Arjun)
- **Pace**: 1.1
- **Hard cap**: 400 chars per call
- **Text normalisation**: normalize_for_tts() converts ₹ amounts, LPA, percentages, age patterns, product names. Called in both pipeline.py AND /speak endpoint.

### No embedding model
BM25 chosen over ChromaDB/FAISS. Reasons: no external service, no cost, works offline, insurance vocabulary is keyword-rich. Do not add ChromaDB.

---

## SECTION 7 — DOCUMENT INGESTION PIPELINE

### PDF Processing
`pdfplumber` extracts text and tables per page. Tables formatted as pipe-delimited strings. Combined into single text block.

### Metadata Extraction
`ingestion.py:_extract_metadata()` — gpt-4o-mini, temperature=0.1.
Output: plan_name, company_name, plan_type (term/health/savings/ulip/pension/child/other), one_line_pitch.
Saved to `{name}.meta.json`.

### Sales Brief Generation
`ingestion.py:_generate_brief_via_llm()` — gpt-4o-mini, temperature=0.3.
Sections: COVERAGE, PREMIUMS (payment structure ONLY — no rupee amounts), ELIGIBILITY, DEATH BENEFIT, MATURITY BENEFIT, RIDERS, TAX BENEFITS, EXCLUSIONS, PITCH.
Saved to `{name}.brief.txt`.

**HARD CONSTRAINT**: The PREMIUMS section must never contain illustrative rupee amounts ("₹22/day", "starting from ₹X"). These will be read by the LLM at PROFILE stage and presented as customer-specific premiums. This is a confirmed, serious hallucination vector. The ingestion prompt was specifically rewritten to exclude pricing examples from the brief.

### Structured Extraction
`table_parser.py` — deterministic premium table extraction from PDF tables.
`structure_builder.py` — builds structure.json with premium tables, eligibility, payment rules, GST rate, quote_capability_level (0-3).
GPT fallback in `_gpt_extract_illustrative_premium()` if no tables found.
Saved to `{name}.structure.json`.

### BM25 Indexing
`bm25_store.py` — section-aware chunking, BM25Okapi index.
Saved to `{name}.chunks.json`.

### Current HDFC Brochure Status
- plan_type: "other" (should be "term" — GPT extraction error)
- quote_capability_level: 1 (illustrative rows, not real table)
- Brief PREMIUMS section: correctly has no rupee amounts (re-ingested in Iteration 11)
- Brief ELIGIBILITY: shows "70-85 years" — GPT extraction error. Actual: 18-70 years.

---

## SECTION 8 — CONVERSATION ARCHITECTURE

### Stage Intent Summaries

**INTRODUCE**: Give 2-sentence overview, ask permission. Python escape after 2 turns.

**PROFILE**: Ask only missing fields (injected as STILL NEEDED list). Max 2 questions per turn. No premium discussion. Transitions gated.

**NEED_DEVELOPMENT**: One question making customer articulate their financial vulnerability. No product pitching. Python escape after 2 turns.

**EXPLAIN**: One topic per turn. Structure: connect to risk narrative → explain benefit → concrete numbers → check-in. After final topic: RECOMMENDATION.

**RECOMMENDATION**: Direct personal recommendation. "Given that [risk]... this plan ensures [outcome]... cost is [amount if available]... Would you like to take this forward?" Python auto-advances to CLOSE after 1 turn.

**HANDLE**: 4-step: acknowledge → explore → respond with document fact → check. Returns to previous stage.

**QUESTION_ANSWER**: Answer with profile + document facts only. Return to previous stage.

**CLOSE/PURCHASE_INTENT**: Single question: "Would you like to proceed with purchasing this policy?"

**CLOSE/PROCEED**: Deliver handoff ONLY. Forbidden: collecting any personal data, inventing application steps, generating links.

**CLOSE/FEEDBACK**: Collect decline reason gracefully. Do not argue or re-sell.

**CLOSE/CLOSED**: "Thank you for your time today. If you have any questions in the future, our support team will be happy to assist. Have a great day."

### Customer Profiling

**Layer 1** (deterministic): `profile_extractor.py` fires on every message before LLM. Extracts age, smoker, income, dependents, marital_status, gender, policy_term, payment_frequency, liabilities_lakh, cover_amount_override_lakh via regex.

**Layer 2** (LLM): Collects nuanced context. Cannot write to CustomerProfile directly.

### Risk Narrative

`build_risk_narrative()` in `agent.py` converts CustomerProfile fields into a financial vulnerability story. Example:

*"At 35, this is still a strong window to secure adequate cover. A spouse and 2 dependents rely on this income entirely. If that income stopped unexpectedly, their financial stability would be immediately at risk. There is currently no insurance coverage in place. An income of 50 LPA funds the household, any loans, and the family's future goals — all of which stop the moment that income stops."*

Injected into system prompt at NEED_DEVELOPMENT, EXPLAIN, RECOMMENDATION, CLOSE, HANDLE.

### Intended vs Observed Behaviour

| Aspect | Intended | Observed pre-Iteration 11 |
|---|---|---|
| Profile collection | 1-2 missing fields per turn | All 5 fields at once, then premium discussion |
| Premium at PROFILE | Never | ₹22/day from brief |
| Stage progression | PROFILE→NEED_DEV→EXPLAIN | Stuck at PROFILE |
| Need development | One vulnerability question | Never reached |
| Recommendation | Personalised with numbers | Never reached |
| Language | Consistent with customer | Mostly English regardless |
| Close | Handoff message only | Collecting application data |

---

## SECTION 9 — MAJOR CHALLENGES ENCOUNTERED

### Challenge 1: Premium Hallucination (Resolved)

**Root cause**: `ingestion.py` brief prompt included "include a specific rupee example with age if available". HDFC brief contained "₹22/day for 25yr non-smoker". This was injected as product knowledge at every stage including PROFILE. At PROFILE stage, no CALCULATED NUMBERS block exists. LLM quoted ₹22/day as customer-specific premium and calculated 22×365=8,000/year independently.

**Diagnosis**: Traced exact execution — confirmed number from brief, not recommendation engine; recommendation engine not called at PROFILE stage.

**Solution**:
1. Changed ingestion prompt: PREMIUMS section now describes payment structure only
2. Runtime filter: strips PREMIUMS section from brief at INTRODUCE/PROFILE/NEED_DEVELOPMENT
3. HDFC PDF re-ingested
**Status**: Resolved.

### Challenge 2: is_sufficient() Never Firing (Resolved)

**Root cause**: Required 4 of [age, gender, dependents, existing_coverage, financial_goal]. Gender and financial_goal almost never stated. Gate never fired. Stage progression relied entirely on LLM emitting PERSONALIZE.

**Solution**: Simplified to age + smoker + income + family context for term plans.
**Status**: Resolved.

### Challenge 3: PROFILE→PERSONALIZE Not Gated (Resolved)

**Root cause**: I-9 fix blocked PROFILE→EXPLAIN and PROFILE→CLOSE but not PROFILE→PERSONALIZE. LLM could exit PROFILE early, or when off-script, stage stuck forever.

**Solution**: Gate added in apply_analysis(): PROFILE→PERSONALIZE requires age + (smoker or income).
**Status**: Resolved.

### Challenge 4: CLOSE Stage Application Collection Hallucination (Resolved in prompt)

**Root cause**: LLM ignored PROCEED substage instruction and invented an application collection workflow (name, address, health, nominee). LLM's strong prior about "insurance application" overrode prompt.

**Solution**: PROCEED substage prompt rewritten with explicit forbidden list.
**Status**: Resolved in prompt. Not fully verified in live testing.

### Challenge 5: Language Consistency (Partially resolved)

**Root cause 1**: Typed text never updated language (no STT involved).
**Root cause 2**: Language instruction placed late in long prompt.
**Root cause 3**: gpt-4o-mini ignores instructions that arrive after 5,000+ chars of other content.

**Solution**: detect_language_from_text() for typed input. Language rule made mandatory with explicit if/then cases. Moved higher in system prompt.
**Status**: Partially resolved. Typed Hindi works. First voice response after switch sometimes still English.

### Challenge 6: NEED_DEVELOPMENT and RECOMMENDATION Never Reached (Resolved structurally)

**Root cause**: All of Challenges 2, 3, 6 above meant PROFILE never exited. New stages were architecturally in place but unreachable.

**Status**: Structurally resolved after Challenge 2 and 3 fixes. Not verified in live conversation.

### Challenge 7: Session Start — No TTS, Double Bubble

**Root cause**: `updateLangBadge()` called `document.getElementById("lang-badge-sidebar")` which no longer existed after removing Live Intelligence sidebar. Threw null reference. Crash in session-start try block before playTTS() was called. Catch block showed fallback "Hello! I'm ready" bubble.

**Solution**: Removed dead lang-badge-sidebar reference.
**Status**: Resolved.

### Challenge 8: Opener TTS Spelling Out "Click2Protect"

**Root cause**: GET /speak endpoint (used for opener) called synthesize_stream() directly, bypassing normalize_for_tts(). Pipeline.py called it correctly; /speak did not.

**Solution**: normalize_for_tts() called in /speak endpoint.
**Status**: Resolved.

---

## SECTION 10 — KEY ARCHITECTURAL DECISIONS

### Stage Machine vs Goal Engine

**Chosen**: Stage machine. Faster to build, more predictable, sufficient for demo.
**Rejected**: Goal engine — requires richer customer state model, dynamic goal-selection logic, more testing. Identified as correct long-term direction but deferred.
**Tradeoff**: Stage machine controls transitions but not content within a stage. LLM has complete freedom to say anything within a stage. Root cause of all off-script behaviour.

### BM25 vs Vector Search

**Chosen**: BM25. No external service, no cost, works offline, insurance vocabulary is keyword-rich.
**Rejected**: ChromaDB/FAISS — additional dependency, embedding cost, no clear quality advantage.
**Hard constraint**: Do not add ChromaDB. Decision is final for this project.

### Deterministic Quote Engine vs LLM Quoting

**Chosen**: Deterministic. Insurance customers notice wrong premiums immediately. Numbers must be auditable.
**Rejected**: LLM quoting — hallucinates confidently, wrong numbers destroy trust.
**Tradeoff**: Requires well-structured PDF. HDFC brochure only has illustrative data, so confidence=inferred.

### Sales Brief Approach

**Current**: Brief contains payment structure description only. No rupee amounts anywhere in brief.
**Why**: Any rupee amount in the brief will be quoted by the LLM at early stages as if it's the customer's specific premium. Confirmed hallucination vector.
**Future consideration**: Two-tier brief (features-brief safe everywhere, pricing-brief only at EXPLAIN+). Not yet implemented.

### Human Approval

**Current**: AUTO_APPROVE_DOCUMENTS=true. All uploads approved immediately.
**Not built**: status="pending_review" path defined in structure.json schema but UI and workflow not implemented.

### No Database

**Decision**: File-based persistence only. Sessions lost on server restart.
**Tradeoff**: Acceptable for demo. Not acceptable for production.

### Sarvam STT/TTS Mandatory

Required by project brief (Sarvam AI demo). Not a choice.

---

## SECTION 11 — CURRENT IMPLEMENTATION STATUS

### Working Well

- PDF upload, ingestion, all 5 output files
- OpenAI gpt-4o-mini integration
- Sarvam STT/TTS (codemix, dev voice, pace 1.1)
- TTS text normalisation including opener
- BM25 retrieval
- Deterministic profile extraction (regex, 10 fields)
- Cover recommendation engine
- Stage machine state tracking
- Frontend UI (clean, single advisor, voice/text)
- Evaluation and transcript endpoints

### Partially Working

- Quote engine: works but HDFC has capability_level=1 (illustrative rows, confidence=inferred)
- NEED_DEVELOPMENT stage: architecturally complete, not yet live-verified post Iteration 11
- RECOMMENDATION stage: same
- Language switching: typed Indian scripts work; voice switching imperfect on first response
- Objection handling: playbook and 4-step HANDLE intent written, not verified

### Not Working / Known Issues

- HDFC plan_type detected as "other" (should be "term") — affects is_sufficient() and explain topics
- HDFC eligibility brief shows "70-85 years" (GPT error, actual 18-70)
- Smoker premium table split: detected but not implemented
- Language consistency: LLM may respond in English after switch
- No session persistence
- No human approval workflow
- No voice activity detection

### Known Technical Debt

- PERSONALIZE stage is vestigial (one-turn bridge). Could be removed.
- recommendation_block and policy_quote both injected at CLOSE. Should suppress recommendation_block when policy_quote is available.
- ingest_worker.py (35 lines) — thin wrapper, relationship to ingestion.py unclear.

### Demo-Ready Features

Upload→ingest→start flow, voice+chat conversation, profile collection, BM25 Q&A, deterministic cover recommendation, quote generation (inferred confidence for HDFC), close flow with handoff message, evaluation report.

### Production-Ready Features

None. Auth, persistent sessions, document storage, monitoring, load testing, security all needed.

---

## SECTION 12 — FUTURE ROADMAP

### Short-Term (1-2 weeks, Demo Polish)

1. Verify Iteration 11 fixes in live conversation (profile advancing, no premium hallucination, new stages reached)
2. Fix HDFC plan_type classification error
3. Fix HDFC eligibility extraction error
4. Verify full PROFILE→NEED_DEVELOPMENT→EXPLAIN→RECOMMENDATION→CLOSE journey
5. Test Hindi conversation end-to-end
6. Suppress recommendation_block when policy_quote available
7. Upload a better PDF with real age×term premium table (Max Life STPP recommended)

### Medium-Term (1-2 months, Production-Ready Demo)

1. Goal-based conversation engine (replace stage machine)
2. Persistent sessions (Redis)
3. Multi-document comparison
4. Smoker premium table split
5. Human approval workflow
6. Better language consistency (consider fine-tuned model)

### Long-Term (3+ months, Production)

1. Authentication and multi-tenancy
2. CRM integration
3. Fine-tuned sales model on Indian insurance conversations
4. Real-time supervisor monitoring
5. Post-call analytics
6. Mobile app
7. Docker and CI/CD

### What to Remove

- PERSONALIZE stage (vestigial)
- SUMMARY close substage (replaced by RECOMMENDATION stage)
- recommendation_block at CLOSE when policy_quote available

### What to Postpone

- Goal engine (correct but needs focused time)
- Embedding-based search (BM25 sufficient)
- Voice activity detection (nice to have)

---

## SECTION 13 — LESSONS LEARNED

### Critical Technical Lessons

**1. LLMs follow content they see first, not instructions they receive last.**
In a 300-line system prompt, product knowledge at line 10 dominates. Stage instructions at line 200 are weak. If you need the LLM to not use certain information, remove it from the prompt entirely. Do not rely on a prohibition instruction appearing after the information it prohibits.

**2. The sales brief is not a safe general-purpose knowledge base.**
Marketing language in a brief ("₹22/day for a young non-smoker") becomes a "fact" the LLM applies to any customer. Product knowledge and customer-specific calculated numbers must be strictly separated. Brief = features and structure. Numbers = calculated engines only.

**3. Stage machines control transitions, not content within stages.**
Every "off-script" behaviour observed happened within a stage, not at a transition. The LLM can say anything it wants during a turn. Stage gates only activate after the response is generated. This is the fundamental limitation of the current architecture.

**4. Gate every exit from every stage, not just the obvious ones.**
We gated PROFILE→EXPLAIN and PROFILE→CLOSE. We forgot PROFILE→PERSONALIZE. The LLM found the ungated exit. Every possible stage transition needs to be evaluated for whether it should be gated.

**5. Design is_sufficient() around what customers actually say, not what you wish they'd say.**
Gender and financial_goal are almost never volunteered in natural conversation. A gate requiring these fields will never fire. Profile sufficiency requirements must be validated against realistic customer utterances.

**6. Verify stage reachability before improving stage content.**
We built NEED_DEVELOPMENT, RECOMMENDATION, risk narrative, better close prompts — none of it mattered because the conversation never reached those stages. The correct workflow: first confirm every stage can be reached in live testing. Then improve what happens inside each stage.

### Product Lessons

**Need development is not optional for insurance sales.**
Presenting features before developing need consistently fails. The customer must feel their financial vulnerability before a product makes sense. The NEED_DEVELOPMENT stage is architecturally correct but must be genuinely conversational, not a one-line script.

**Premium accuracy is non-negotiable.**
Any inaccurate premium number immediately destroys trust. The hallucinated ₹22/day was not just wrong — it was presented confidently for the wrong customer profile. Customers in insurance are attuned to numbers. The "never mention premium without calculated data" rule must be architectural.

**Closing is not a terminal stage, it's a mindset.**
The current architecture treats CLOSE as a stage you enter after RECOMMENDATION. In reality, closing orientation should be woven throughout EXPLAIN and RECOMMENDATION. Each explanation should end with a micro-commitment, not just a check-in question.

**Language is trust.**
An English response to a Hindi question signals that the agent is not really listening. Language consistency is not a nice-to-have — it directly affects whether the customer trusts the conversation.

---

## SECTION 14 — CONTEXT TRANSFER FOR ANOTHER AI

**This section is designed to be pasted directly into another AI system. It contains everything needed to continue this project immediately.**

---

### Project Identity

You are continuing development of **PolicyAI** — a voice-first AI insurance sales agent. Project location: `/Users/ud/sarvam-insurance-agent`. This is a Python/FastAPI backend with a static HTML/JS frontend.

### How to Run

```bash
# Always use venv, not system Python
.venv/bin/uvicorn backend.main:app --reload --port 8000
# Open http://localhost:8000
```

### Environment

Create `.env` at project root:
```
SARVAM_API_KEY=<from sarvam.ai dashboard>
OPENAI_API_KEY=<from platform.openai.com>
AUTO_APPROVE_DOCUMENTS=true
```

### Hard Constraints — Never Violate These

1. **Sarvam APIs for speech only**: saaras:v3 (STT), bulbul:v3 (TTS). Never for LLM.
2. **OpenAI gpt-4o-mini for all LLM calls**: Conversation, extraction, brief, evaluation.
3. **No ChromaDB**: BM25 is the RAG layer. This decision is final.
4. **All premium numbers must be deterministic Python**: Never LLM-generated. `recommendation.py` for estimates, `quote_engine.py` for document-derived quotes.
5. **Brief PREMIUMS section must never contain rupee amounts**: Any rupee figure in the brief at PROFILE stage causes hallucination. The ingestion prompt was specifically fixed. Do not undo this.
6. **STT always passes `language_code="unknown"`**: Specific codes break language_probability.
7. **Stage machine is Python-gated**: LLM signals transitions via META tags; Python enforces them.

### Current Conversation Flow

```
INTRODUCE → PROFILE → NEED_DEVELOPMENT → EXPLAIN → RECOMMENDATION → CLOSE
```

Close substages: `PURCHASE_INTENT → PROCEED or FEEDBACK → CLOSED`

Note: PERSONALIZE stage exists but is vestigial (one-turn bridge to NEED_DEVELOPMENT). SUMMARY close substage exists but is skipped — RECOMMENDATION serves that purpose.

### Most Recent Changes (Iteration 11 — verify these work first)

1. `ingestion.py` line 303: PREMIUMS brief instruction now excludes rupee examples
2. `agent.py:_build_messages()`: strips PREMIUMS section from brief at INTRODUCE/PROFILE/NEED_DEVELOPMENT stages
3. `agent.py:_build_messages()`: injects `missing_fields_line` at PROFILE stage
4. `memory.py:is_sufficient()`: simplified to age + smoker + income + family context (term)
5. `conversation_analyzer.py:apply_analysis()`: PROFILE→PERSONALIZE now gated on minimum fields
6. HDFC PDF re-ingested with corrected prompt

### Open Issues (prioritised)

1. **VERIFY**: Run complete Hindi conversation (age 35, 50 LPA, non-smoker, parents dependent). Confirm: no premium at PROFILE stage, NEED_DEVELOPMENT reached, RECOMMENDATION reached, close handled correctly.
2. **FIX**: HDFC plan_type="other" (should be "term"). Affects is_sufficient() and explain topics.
3. **FIX**: HDFC eligibility brief shows "70-85 years" (GPT error, actual 18-70).
4. **FIX**: Suppress recommendation_block when policy_quote is available (prevents two premium sources).
5. **VERIFY**: PROCEED substage — agent delivers handoff only, no data collection.
6. **VERIFY**: Language consistency — Hindi input → Hindi response throughout.

### Pending Decisions

1. Remove PERSONALIZE stage? Low risk, would simplify code.
2. Remove SUMMARY close substage? Already effectively replaced by RECOMMENDATION.
3. Two-tier brief (features-brief vs pricing-brief)? Better separation, prevents future hallucination.
4. Upload a PDF with real premium table for better demo? HDFC brochure has only illustrative data.

### Smoke Test

Run this before touching anything:
```bash
.venv/bin/python3 -c "
import sys; sys.path.insert(0, 'backend')
from dotenv import load_dotenv; load_dotenv()
from memory import CustomerProfile
from agent import build_risk_narrative

p = CustomerProfile()
p.age = 35; p.income_range = '50 LPA'; p.smoker = False
p.dependents = 2; p.existing_coverage = 'none'
print('is_sufficient (term):', p.is_sufficient('term'))
print('Risk narrative:', build_risk_narrative(p)[:150])
"
```

Expected: `is_sufficient (term): True` and a multi-sentence risk narrative.

Check brief has no rupee amounts:
```bash
grep -i "per day\|per year\|₹[0-9]\|Rs\.[0-9]" data/HDFC-Life-Click-2-Protect-Life-101N139V02-Brochure.brief.txt
```
Should return nothing.

### File Quick Reference

| What to change | File |
|---|---|
| Stage intent prompts | `backend/prompts.py:STAGE_INTENTS` |
| Close substage prompts | `backend/prompts.py:CLOSE_SUBSTAGE_INTENTS` |
| Agent persona and style | `backend/characters.py` |
| Stage transition (Python gates) | `backend/agent.py:_auto_advance_stage()` |
| System prompt assembly | `backend/agent.py:_build_messages()` |
| Profile sufficiency | `backend/memory.py:CustomerProfile.is_sufficient()` |
| Stage transition from LLM signals | `backend/conversation_analyzer.py:apply_analysis()` |
| Deterministic profile extraction | `backend/profile_extractor.py` |
| Cover recommendation | `backend/recommendation.py` |
| Premium quote (doc-derived) | `backend/quote_engine.py` |
| Cover amount calculation | `backend/cover_engine.py` |
| Risk narrative | `backend/agent.py:build_risk_narrative()` |
| PDF ingestion + brief generation | `backend/ingestion.py` |
| BM25 retrieval | `backend/rag.py`, `backend/bm25_store.py` |
| Premium table extraction | `backend/table_parser.py` |
| Product structure JSON | `backend/structure_builder.py` |
| TTS (voice + normalisation) | `backend/tts.py` |
| STT (transcription) | `backend/stt.py` |
| WebSocket voice pipeline | `backend/pipeline.py` |
| HTTP endpoints | `backend/main.py` |
| Frontend UI | `frontend/index.html` |

### Why the Conversation Feels Robotic (Architectural Root Cause)

The stage machine controls TRANSITIONS but not CONTENT within stages. The LLM has complete freedom to say anything during a turn. Stage intent instructions arrive late in a ~300-line system prompt, after 3,500 chars of product knowledge. gpt-4o-mini has strong trained priors about sales conversations and follows them when stage instructions are unclear or insufficiently prominent.

The current fixes (missing_fields_line, PREMIUMS stripping, is_sufficient simplification, PERSONALIZE gate) address the most critical failure modes but do not solve the underlying problem. The correct long-term solution is a goal-based conversation engine where Python determines what the conversation needs to achieve each turn (develop_need / connect_to_product / handle_objection / build_confidence / ask_for_commitment) and injects that as the primary directive rather than a stage label.

This architectural change was deferred due to deadline pressure. It remains the highest-value improvement not yet implemented.

---

*End of handover document.*
