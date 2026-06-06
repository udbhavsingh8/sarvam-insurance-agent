# COMPLETE CODE INDEX

---

## BACKEND FILES

---

### backend/agent.py

**Purpose:** Stateful session object for the insurance sales agent. Wires together LLMClient, DocumentStore, SessionMemory, CharacterRegistry, ConversationAnalyzer, gap_engine, and metrics. One AgentSession per customer session.

**Key classes:**

| Class | Description |
|---|---|
| AgentSession | One session. Owns memory, LLM client, document store, character config. |

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| _guard_discovery_numbers | `(text: str, profile: object) -> str` | Hard Python safety net: replace any ₹ amount in DISCOVERY response with redirect to next missing field | LLM response text, CustomerProfile | Safe redirect text or original text |
| build_risk_narrative | `(profile: CustomerProfile) -> str` | Deterministic personalised risk story for system prompt injection | CustomerProfile dataclass | Multi-sentence risk narrative string or "" |
| _auto_advance_stage | `(memory: SessionMemory, plan_type: str) -> None` | Python stage transition controller — runs after every LLM turn. New flow: GREET→DISCOVERY→GAP_CALC→POSITION→RECOMMEND→VARIANTS→CLOSE (term) | SessionMemory, plan_type string | Mutates memory.stage, memory.turn_in_stage |
| _auto_advance_close_substage | `(memory: SessionMemory) -> None` | Python close substage controller. PROCEED threshold >= 2 prevents same-turn skip. | SessionMemory | Mutates memory.close_substage |
| AgentSession.__init__ | `(store, character_id, session_id) -> None` | Initialize session with document store and character | DocumentStore, character_id str, optional session_id | AgentSession instance |
| AgentSession.generate_opener | `() -> str` | Build deterministic opening line — no LLM call | None (uses store.metadata) | Opening sentence string |
| AgentSession.chat | `(user_text: str) -> str` | Process one user turn, return agent response | User text string | Clean response string |
| AgentSession.chat_stream | `(user_text: str) -> Iterator[str]` | Stream agent response tokens | User text string | Token iterator |
| AgentSession.record_turn | `(llm_ms, stt_ms, tts_ms, ...) -> None` | Post-streaming: assemble response, parse META, update memory | Latency ints, error flags | Mutates memory; logs metrics |
| AgentSession.update_language | `(language_code: str, probability: float) -> None` | Propagate STT-detected language into memory | BCP-47 code, float probability | Mutates memory.detected_language |
| AgentSession.detect_language_from_text | `(text: str) -> None` | Unicode code-point language detection for typed text | User text | Mutates memory.detected_language |
| AgentSession.end_session | `() -> None` | Log session metrics | None | Logs to sessions.jsonl |
| AgentSession._build_messages | `(user_text: str) -> list[dict]` | Assemble full system prompt + history message list for LLM. Injects gap block at GAP_CALC, risk narrative at RECOMMEND/VARIANTS/CLOSE/OBJECTIONS. | User text | OpenAI messages list |

**Key constants (agent.py):**
- `MAX_HISTORY_TURNS = 6` — last 12 log entries in context
- `BRIEF_CHAR_LIMIT = 3500` — max sales brief chars in prompt
- `DOC_CONTEXT_CHAR_LIMIT = 1500` — max BM25 context chars
- `_NARRATIVE_STAGES = ("RECOMMEND", "VARIANTS", "EXPLAIN", "CLOSE", "OBJECTIONS")`
- `_FALLBACK = "I'm having a connection issue..."` — used on LLM error
- `_RUPEE_RE` — compiled regex for rupee amount detection in DISCOVERY guard

**Dependencies:** characters, conversation_analyzer, errors, gap_engine, llm, memory, metrics, profile_extractor, prompts, recommendation, rag, cover_engine, quote_engine

**Called by:** main.py (via AgentSession), pipeline.py (via session.chat_stream, session.record_turn)

---

### backend/gap_engine.py

**Purpose:** Deterministic income-replacement protection gap calculator for term plans. Called at GAP_CALC stage. Produces a structured dict AND a ready-to-speak text block that Arjun reads out loud to show the customer their protection gap.

**Key classes:** None

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| _parse_income_lpa | `(income_range: Optional[str]) -> Optional[float]` | Convert income_range string to LPA float. Handles "25 LPA", "₹2,00,000/month", "25 lakhs", etc. | income_range string | float (LPA) or None |
| _fmt_lakh | `(lakh: float) -> str` | Format lakh amount as "₹X crore" or "₹X lakh" | float | str |
| build_gap_calculation | `(profile: CustomerProfile) -> Optional[dict]` | Compute protection gap from customer profile. Returns None if income unknown. | CustomerProfile | gap dict or None |
| gap_to_prompt_block | `(gap: dict) -> str` | Format gap dict as system prompt block for injection at GAP_CALC stage | gap dict from build_gap_calculation | Multi-line prompt block string |

**Output dict keys from build_gap_calculation:**
- `income_lpa`: float — parsed annual income in lakh
- `years_of_support`: int — years of income replacement (default 20 if not stated)
- `income_protection_lakh`: float — income_lpa × years_of_support
- `liabilities_lakh`: float — outstanding loans (default 0)
- `existing_cover_lakh`: float — existing life cover (default 0)
- `gap_lakh`: float — income_protection + liabilities − existing (floored at 0)
- `gap_display`: str — formatted gap ("₹3.3 crore" or "₹50 lakh")
- `spoken_walkthrough`: str — line-by-line calculation for Arjun to read aloud
- `assumptions_made`: list[str] — defaults applied (shown transparently)

**Formula:**
```
income_protection_lakh = income_lpa × years_of_support
gap_lakh = income_protection_lakh + liabilities_lakh − existing_cover_lakh
gap_lakh = max(0.0, gap_lakh)
```

**Defaults:** _DEFAULT_YEARS = 20, _DEFAULT_EXISTING = 0.0, _DEFAULT_LIABILITIES = 0.0

**Dependencies:** memory (TYPE_CHECKING)

**Called by:** agent.py _build_messages() at GAP_CALC stage

---

### backend/main.py

**Purpose:** FastAPI application. Exposes HTTP + WebSocket endpoints. Manages session and job dicts. Wires ingestion, voice pipeline, evaluation, and static frontend serving.

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| _run_ingestion | `(job_id, pdf_path, character_id) -> None` | Async background ingestion + session creation | job_id, pdf_path, character_id | Mutates _jobs, _sessions |
| health | `() -> JSONResponse` | Liveness probe | None | {"status": "ok"} |
| upload_pdf | `(file, character) -> JSONResponse` | Accept PDF, start background ingestion | UploadFile, character str | {"job_id": ..., "status": "ingesting"} |
| job_status | `(job_id) -> JSONResponse` | Poll ingestion status | job_id str | {"status": ..., "session_id": ...} |
| chat | `(session_id, message, stream, stt_latency_ms) -> Response` | Process LLM turn. Handles `__opener__` special token. | Form params | StreamingResponse (SSE) or JSONResponse |
| transcribe_audio | `(audio, session_id) -> JSONResponse` | STT endpoint. Propagates detected language to session. | UploadFile audio, session_id | {"transcript": ..., "language_code": ..., "language_probability": ...} |
| speak | `(text, session_id, language_code) -> StreamingResponse` | TTS endpoint. Uses session speaker and language. | Query params | Streaming WAV audio |
| evaluate | `(session_id) -> JSONResponse` | Post-conversation evaluation + session close | session_id | Evaluation report dict |
| get_transcript | `(session_id) -> JSONResponse` | Return full turn log | session_id | {"turns": [...], "stage": ...} |
| delete_session | `(session_id) -> JSONResponse` | End and remove session | session_id | {"deleted": session_id} |
| ws_chat | `(websocket) -> None` | WebSocket voice pipeline endpoint | WebSocket | Sends sentence/audio/done frames |

**Key constants:**
- `MAX_AUDIO_BYTES = 10 * 1024 * 1024` — 10MB audio limit
- `DATA_DIR` — absolute path to data/ directory
- `_sessions: dict[str, AgentSession]` — in-memory session store
- `_jobs: dict[str, dict]` — in-memory job store
- `_session_locks: dict[str, asyncio.Lock]` — per-session concurrency lock

**Dependencies:** agent, evaluation, ingestion, pipeline, rag, stt, tts, characters

**Called by:** Uvicorn ASGI server

---

### backend/prompts.py

**Purpose:** All prompt templates, stage intents, and behavioral rules. Pure data — no logic. Templates are string-formatted in agent.py _build_messages().

**Key functions:**
| Function | Signature | Purpose |
|---|---|---|
| language_display_name | `(code: str) -> str` | BCP-47 code → display name ("hi-IN" → "Hindi") |

**Key constants:**
- `LANGUAGE_NAMES` — BCP-47 → display name dict, 10 languages
- `VOICE_RULES` — 10 formatting, hallucination, and language rules; 2-sentence limit explicitly for Hindi
- `ADVISOR_RULES` — 12 behavioral advisor rules including direct recommendation rule and age guard
- `DEFLECTION_PLAYBOOK` — 5 objection scripts; ROP on explicit "survival" objection only
- `OPENER_PROMPT` — UNUSED LLM opener template
- `STAGE_INTENTS` — dict of active consultative stage intents (GREET, DISCOVERY, GAP_CALC, POSITION, RECOMMEND, VARIANTS, EXPLAIN, OBJECTIONS, QUESTION_ANSWER, CLOSE) plus legacy stubs
- `CLOSE_SUBSTAGE_INTENTS` — dict of substage intents (PURCHASE_INTENT, PROCEED, FEEDBACK, CLOSED, SUMMARY[vestigial])
- `META_TAG_INSTRUCTION` — structured output tag format including position_skip field
- `MAIN_SYSTEM_PROMPT` — master template with 21 placeholders; RULE 0 GROUNDEDNESS prepended; ⚠️ LANGUAGE THIS TURN appended
- `EVALUATION_PROMPT` — post-conversation coaching report template

**Dependencies:** None

**Called by:** agent.py (all constants), evaluation.py (EVALUATION_PROMPT)

---

### backend/memory.py

**Purpose:** All session state dataclasses. CustomerProfile (collected facts, 15 fields), CustomerIntelligence (lead scoring + gap_lakh), SessionMemory (full session state). No LLM calls.

**Key classes:**

| Class | Description |
|---|---|
| CustomerProfile | Progressively collected customer facts. 15 fields. Includes years_of_support, existing_cover_lakh, chosen_variant. |
| CustomerIntelligence | Live lead scoring: interest, close_readiness, gap_lakh, objections, buying_intent. |
| SessionMemory | All session state: stage (initial "GREET"), substage (initial "PURCHASE_INTENT"), profile, intelligence, turn_log, language, position_skipped. |

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| choose_explain_topics | `(plan_type: str, profile: CustomerProfile) -> list[str]` | Return 3-4 relevant EXPLAIN topics for this plan type (non-term plans only; term uses VARIANTS) | plan_type str, CustomerProfile | List of topic name strings |
| CustomerProfile.discovery_sufficient | `(plan_type: str) -> bool` | True when age + income_range + existing_cover_lakh + years_of_support are all non-None. existing_cover_lakh=0.0 counts as answered. | plan_type str | bool |
| CustomerProfile.gap_calc_inputs_ready | `() -> bool` | True if age and income_range are known (minimum for gap calculation) | None | bool |
| CustomerProfile.apply_updates | `(updates: dict) -> None` | Apply profile_extractor output to fields | dict of field:value | Mutates self |
| CustomerProfile.summary | `() -> str` | Format collected fields as readable bullet list | None | Multi-line string |
| CustomerIntelligence.lead_score | `() -> int` | Weighted score: 40% interest + 30% close_readiness + 15% objection resolution + 15% signals | None | int 0-100 |
| CustomerIntelligence.update_intent | `() -> None` | Derive buying_intent from interest_level and close_readiness | None | Mutates self.buying_intent |
| SessionMemory.update_language | `(language_code: str, confidence: float) -> None` | Commit language if confidence >= 0.70 | BCP-47 code, float | Mutates detected_language |
| SessionMemory.log_turn | `(role: str, text: str) -> None` | Append turn to turn_log | role str, text str | Mutates turn_log |
| SessionMemory.memory_summary | `() -> str` | Compact context block (~200 tokens) for system prompt injection. Includes gap_lakh if computed. | None | Multi-line summary string |
| SessionMemory.stages_visited | `() -> list[str]` | Ordered unique stages visited | None | list of stage strings |

**Key changes vs old design:**
- `stage` initial value: `"GREET"` (was `"INTRODUCE"`)
- `close_substage` initial value: `"PURCHASE_INTENT"` (was `"SUMMARY"`)
- New CustomerProfile fields: `existing_cover_lakh`, `years_of_support`, `chosen_variant`
- New SessionMemory field: `position_skipped: bool`
- New CustomerIntelligence field: `gap_lakh: Optional[float]`
- `discovery_sufficient()` redesigned: 4 hard gates, no per-type variation

**Dependencies:** None (pure Python dataclasses)

**Called by:** agent.py (all), conversation_analyzer.py (apply_analysis), evaluation.py, metrics.py

---

### backend/conversation_analyzer.py

**Purpose:** Parses [META ...] tags from LLM responses and applies the resulting TurnAnalysis to SessionMemory. Contains all stage transition gate logic. Designed to be swappable (interface is parse_meta_tag + apply_analysis).

**Key classes:**

| Class | Description |
|---|---|
| TurnAnalysis | Dataclass: stage, interest_delta, objection_category, objection_resolved, close_readiness_delta, emotional_state, close_substage, position_skip |

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| parse_meta_tag | `(text: str) -> tuple[str, Optional[TurnAnalysis]]` | Strip META tag, return clean text + analysis | Raw LLM response | (clean_text, TurnAnalysis or None) |
| apply_analysis | `(memory, analysis, user_text) -> None` | Apply TurnAnalysis to memory: stage gates, position_skip handling, VARIANTS→CLOSE shortcut, topic advance, scoring | SessionMemory, TurnAnalysis, user text | Mutates memory |
| _apply_close_substage | `(memory, requested) -> None` | Validate and apply close substage transition | SessionMemory, requested substage | Mutates memory.close_substage |

**Key constants:**
- `VALID_STAGES` — set of 10 valid stage names: GREET, DISCOVERY, GAP_CALC, POSITION, RECOMMEND, VARIANTS, EXPLAIN, OBJECTIONS, CLOSE, QUESTION_ANSWER
- `VALID_CLOSE_SUBSTAGES` — set of 4 valid substage names: PURCHASE_INTENT, PROCEED, FEEDBACK, CLOSED
- `VALID_EMOTIONAL_STATES` — set of 6 valid emotional state names
- `_META_PATTERN` — compiled regex for `[META...]` tag
- `_LLM_ALLOWED_TRANSITIONS` — per-stage dict of allowed LLM-requested transitions

**Key behaviors:**
- DISCOVERY: LLM cannot advance; `memory.turn_in_stage += 1` if LLM tries
- POSITION skip: if `position_skip=true` and requested=RECOMMEND → sets `memory.position_skipped=True`, allows
- VARIANTS→CLOSE: Python sets `close_substage="PROCEED"` directly (bypasses PURCHASE_INTENT)
- CLOSED: blocks QUESTION_ANSWER and OBJECTIONS interrupts

**Dependencies:** memory (TYPE_CHECKING)

**Called by:** agent.py (parse_meta_tag, apply_analysis), pipeline.py (parse_meta_tag)

---

### backend/recommendation.py

**Purpose:** Deterministic actuarial-benchmark-based cover and premium estimates. Injected into system prompt at RECOMMEND/VARIANTS/EXPLAIN/CLOSE stages. Uses industry benchmarks when document rates are unavailable. Never calls LLM.

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| build_recommendation_block | `(profile, plan_meta, brief_text) -> str` | Build compact text block for system prompt injection | CustomerProfile, plan metadata dict, brief text | Multi-line string or "" |
| _compute | `(profile, plan_type, brief_text) -> Optional[dict]` | Route to term/health/non-term rec | CustomerProfile, plan_type, brief | Result dict or None |
| _term_rec | `(profile, brief_text) -> Optional[dict]` | Term plan cover + premium calculation | CustomerProfile, brief text | Result dict with cover_display, premium_display |
| _health_rec | `(profile) -> Optional[dict]` | Health plan cover + premium calculation | CustomerProfile | Result dict |
| _non_term_guidance | `(profile, plan_type, brief_text) -> Optional[dict]` | Savings/ULIP/pension/child — cover guidance only | CustomerProfile, plan_type, brief | Result dict with premium_display=None |
| _parse_income_lpa | `(income_range: str) -> Optional[float]` | Parse income string to LPA float | income_range string | float or None |
| _extract_reference_premium | `(brief_text: str) -> Optional[int]` | Extract base annual premium per crore from brief PREMIUMS section | brief text | int or None |
| _format_cover | `(cover_lakh: float) -> str` | Format lakh amount to "₹X crore" or "₹X lakh" | float | str |

**Key constants:**
- `_TERM_BASE_PREMIUM_PER_CRORE = 8500`
- `_TERM_BASE_AGE = 25`
- `_AGE_LOADING_PER_YEAR = 0.035` — 3.5% compound per year above base age
- `_SMOKER_LOADING = 0.65` — 65% extra for smokers
- `_COVER_MULTIPLIER_WITH_DEPENDENTS = 15`
- `_COVER_MULTIPLIER_NO_DEPENDENTS = 10`
- `_HEALTH_BASE_PREMIUM = 8000`
- `_HEALTH_BASE_COVER_LAKH = 5`

**Dependencies:** memory (TYPE_CHECKING)

**Called by:** agent.py _build_messages()

---

### backend/quote_engine.py

**Purpose:** Deterministic premium calculation from structure.json premium tables. Lookup → interpolation → GST → frequency loading → Quote object. Called at CLOSE when structure.json has tables. QuoteError raised (not swallowed) on missing data.

**Key classes:**

| Class | Description |
|---|---|
| QuoteError | Exception with reason and capability_level fields |
| FrequencyBreakdown | Dataclass: frequency, installment_amount, installments_per_year, total_annual, display |
| Quote | Full quote result: cover, term, age, smoker, premiums, frequencies, confidence, trail |

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| generate_quote | `(profile, cover_lakh, structure) -> Quote` | Main entry point. Raises QuoteError if data unavailable. | CustomerProfile, cover_lakh float, structure dict | Quote dataclass |
| quote_to_prompt_block | `(quote, payment_frequency) -> str` | Format Quote as system prompt block | Quote, frequency str | Multi-line string with trail |
| _select_table | `(premium_tables, smoker) -> tuple[dict, str]` | Pick best smoker-matched premium table | tables list, smoker bool | (table dict, basis str) |
| _interpolate | `(rows, age, term) -> tuple[int, str, list]` | Find per-crore premium: exact → age interpolation → nearest term → fallback | rows list, age int, term int | (premium int, confidence str, trail list) |
| _age_interpolate | `(term_rows, target_age, term) -> tuple[int, list]` | Linear interpolation between age brackets | sorted rows, target age, term | (premium int, trail list) |
| _default_term | `(age: int) -> int` | Suggest policy term: max(10, min(65-age, 40)) | age int | term int |

**Key constants:**
- `_DEFAULT_FREQ_RULES` — annual/semi_annual/quarterly/monthly factors and counts
- `_GST_RATE = 0.18`
- `_FREQ_LABELS` — frequency → spoken label dict

**Dependencies:** memory (TYPE_CHECKING)

**Called by:** agent.py _build_messages()

---

### backend/cover_engine.py

**Purpose:** Deterministic cover amount recommendation from customer profile. Separated from premium calculation so each evolves independently. Returns CoverRecommendation consumed by quote_engine.

**Key classes:**

| Class | Description |
|---|---|
| CoverRecommendation | cover_lakh, cover_display, rationale_steps, is_override |

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| recommend_cover | `(profile: CustomerProfile) -> Optional[CoverRecommendation]` | Calculate cover: income × multiplier + liabilities - existing, clamped ₹25L–₹10Cr | CustomerProfile | CoverRecommendation or None |
| _parse_income_lpa | `(income_range: str) -> Optional[float]` | Parse income string to LPA float | income_range str | float or None |
| _parse_existing_coverage_lakh | `(existing: str) -> float` | Convert existing_coverage string to lakh float (none=0, some=25, adequate=50) | existing str | float |

**Key constants:**
- `_COVER_CAP_LAKH = 1000` — ₹10 crore cap
- `_COVER_FLOOR_LAKH = 25` — ₹25 lakh floor
- Multipliers: 20 (dependents + income < 10 LPA), 15 (dependents), 10 (no dependents)

**Dependencies:** memory (TYPE_CHECKING)

**Called by:** agent.py _build_messages()

---

### backend/characters.py

**Purpose:** Character registry. Each entry defines identity, communication style, emotional handling scripts, and TTS voice speaker name. Product knowledge is separate (from DocumentStore). Two characters: arjun (active), lalita (inactive in UI).

**Key constants:**
- `CHARACTERS: dict[str, dict]` — character registry with "arjun" and "lalita"
  - Arjun persona: "twenty years of field experience" (updated from "eight years")
- `SUPPORTED_LANGUAGES: dict[str, str]` — BCP-47 → display name, 10 languages
- `DEFAULT_LANGUAGE = "en-IN"`
- `DEFAULT_CHARACTER = "arjun"`

**Character fields:** id, name, gender, persona, style_guide, emotional_guide, opener (unused ""), voice (Sarvam speaker name)

**Voice assignments:**
- arjun → "dev"
- lalita → "ritu"

**Dependencies:** None

**Called by:** agent.py (CHARACTERS.get()), main.py (CHARACTERS validation), tts.py (SUPPORTED_LANGUAGES)

---

### backend/ingestion.py

**Purpose:** Full document ingestion pipeline. Takes a PDF, produces .txt, .meta.json, .brief.txt, .structure.json, .chunks.json in data/. Two LLM calls (metadata + brief). Falls back to keyword extraction on LLM failure. Skips brief/meta regeneration if files already exist (prevents revert-on-upload bug).

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| ingest | `(pdf_path: str, index_dir: str) -> tuple[int, str]` | Main entry point. Extracts, saves all artifacts. Skips if brief/meta already exist. | pdf_path, index_dir | (page_count, name) |
| extract_text | `(pdf_path: str) -> str` | pdfplumber page-by-page text extraction | pdf_path | Full document text |
| _extract_pages_data | `(pdf_path: str) -> list[dict]` | Per-page text + tables for structure builder | pdf_path | [{page_num, text, tables}] |
| _extract_metadata | `(text: str) -> dict` | GPT-4o-mini → 4 metadata fields. Falls back to keyword extraction. | document text | {plan_name, company_name, plan_type, one_line_pitch} |
| _extract_metadata_from_text | `(text: str) -> dict` | Keyword-based metadata fallback | text | same dict |
| _generate_product_profile | `(text, meta) -> str` | LLM brief generation with keyword fallback | text, meta dict | Brief string |
| _generate_brief_via_llm | `(text, meta) -> str` | GPT-4o-mini brief generation. Returns "" on failure. PREMIUMS section excludes rupee amounts. | text, meta | Brief string or "" |
| _generate_brief_via_keywords | `(text, meta) -> str` | Keyword extraction fallback brief | text, meta | Brief string |
| _detect_plan_type | `(text, meta_type) -> str` | Keyword-based plan type detection. Text wins over meta hint. | text, meta_type | plan_type string |
| _extract_section | `(text, keywords, max_chars) -> str` | Extract relevant lines for given keywords | text, keywords, max_chars | Section text |
| load_document | `(index_dir, name) -> str` | Load {name}.txt | index_dir, name | document text |
| load_sales_brief | `(index_dir, name) -> str` | Load {name}.brief.txt | index_dir, name | brief text or "" |
| load_metadata | `(index_dir, name) -> dict` | Load {name}.meta.json | index_dir, name | metadata dict (fallback defaults on error) |

**Dependencies:** pdfplumber, openai, structure_builder, bm25_store

**Called by:** main.py _run_ingestion() via asyncio executor

---

### backend/structure_builder.py

**Purpose:** Build structure.json from parsed PDF pages. Orchestrates deterministic table extraction (table_parser) → GPT fallback → actuarial validation → eligibility/frequency extraction → capability level assignment.

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| build_product_structure | `(text, pages_data, meta, doc_hash) -> dict` | Main entry point. Returns complete structure dict. | text, pages_data list, meta dict, doc_hash str | structure dict ready for JSON serialization |
| _validate_premium_rows | `(rows) -> list[str]` | Actuarial validation: age range, premium range, monotonicity | rows list | list of warning strings |
| _extract_eligibility | `(text: str) -> dict` | Regex-based eligibility extraction: min/max age, term, sum assured | text | eligibility dict |
| _extract_frequency_rules | `(text: str) -> dict` | Extract payment frequency factors from document text | text | frequency rules dict |
| _gpt_extract_illustrative_premium | `(text, plan_name) -> list[dict]` | GPT fallback: extract premium examples when no table found | text, plan_name | [{age, term, annual_premium}] or [] |
| _assign_capability_level | `(premium_tables) -> int` | 0=none, 1=illustrative, 2=table, 3=full | premium_tables list | int 0-3 |
| _auto_approve | `() -> bool` | Read AUTO_APPROVE_DOCUMENTS env var (default true) | None | bool |

**Key constants:**
- `_TERM_PREMIUM_MIN = 2000`
- `_TERM_PREMIUM_MAX = 500000`
- `_DEFAULT_FREQUENCY_RULES` — industry standard frequency factors

**Dependencies:** table_parser, openai

**Called by:** ingestion.py ingest()

---

### backend/tts.py

**Purpose:** Text-to-Speech using Sarvam bulbul:v3. Includes normalize_for_tts() which converts TTS-hostile patterns (₹ amounts, LPA, percentages, age hyphens, EMIs) to spoken form.

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| normalize_for_tts | `(text: str) -> str` | Convert all numeric/special patterns to spoken form before TTS | text | normalized text |
| synthesize | `(text, language_code, speaker) -> bytes` | Non-streaming TTS. Returns full WAV. | text, lang_code, speaker | WAV bytes |
| synthesize_stream | `(text, language_code, speaker) -> Iterator[bytes]` | Streaming TTS. Yields raw audio chunks. | text, lang_code, speaker | bytes iterator |
| _truncate_for_tts | `(text: str) -> str` | Trim to MAX_TTS_CHARS at sentence boundary | text | truncated text |
| _rupee_amount | `(m: re.Match) -> str` | Convert ₹ match to spoken "twenty two rupees per day" | regex match | spoken string |
| _int_to_words | `(n: int) -> str` | Integer 0-99 to English words | int | str |

**Key constants:**
- `TTS_MODEL = "bulbul:v3"`
- `SAMPLE_RATE = 22050`
- `MAX_TTS_CHARS = 400`
- `_DEFAULT_SPEAKERS` — all languages default to "anushka"
- `SUPPORTED_LANGUAGES` — list of 10 BCP-47 codes

**TTS normalization patterns include:**
- "EMIs" → "E M I S" (all caps, spaced for clear pronunciation)
- "100%" → "one hundred percent"
- ₹ amounts → spoken form ("₹22/day" → "twenty two rupees per day")
- "X LPA" → spoken form

**Dependencies:** sarvamai, errors

**Called by:** main.py /speak endpoint, pipeline.py synthesize()

---

### backend/stt.py

**Purpose:** Speech-to-Text using Sarvam saaras:v3. Always uses language_code='unknown' for auto-detection. Returns transcript + language_code + language_probability.

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| transcribe | `(audio_bytes: bytes) -> dict` | Transcribe audio with retry. | audio bytes (webm) | {"transcript", "language_code", "language_probability"} |

**Key config:** model="saaras:v3", mode="codemix", language_code="unknown" (always — specific codes break probability)

**Dependencies:** sarvamai, errors

**Called by:** main.py /transcribe endpoint, pipeline.py (indirectly via main)

---

### backend/llm.py

**Purpose:** Thin wrapper over OpenAI chat completions. Exposes complete() (blocking) and stream() (iterator). Uses gpt-4o-mini. Accepts stage parameter for stage-scoped temperature. Retries via errors.retry_call.

**Key classes:**

| Class | Description |
|---|---|
| LLMClient | complete(messages, stage) and stream(messages, stage) methods |

**Key constants:**
- `MODEL = "gpt-4o-mini"`
- `MAX_TOKENS = 600`
- `TEMPERATURE = 0.7` (default; overridden per stage)

**Stage-scoped temperature:** Lower temperature at GREET/DISCOVERY stages (data collection needs precision), higher at VARIANTS/OBJECTIONS (needs creativity). Exact mapping is in llm.py.

**Dependencies:** openai, errors

**Called by:** agent.py (via self._llm), evaluation.py

---

### backend/errors.py

**Purpose:** Shared error types and exponential backoff retry utility. All external API calls use retry_call(). Non-retryable 4xx errors are raised immediately.

**Key classes:**

| Class | Description |
|---|---|
| SarvamAPIError | Base exception with service, message, retryable fields |
| STTError | STT-specific SarvamAPIError |
| LLMError | LLM-specific SarvamAPIError |
| TTSError | TTS-specific SarvamAPIError |

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| is_retryable | `(exc: Exception) -> bool` | Check if error is retryable (4xx = no, 5xx = yes) | Exception | bool |
| retry_call | `(fn, label, max_attempts, base_delay) -> T` | Exponential backoff retry wrapper | callable, label str, int, float | Return value of fn() |

**Key constants:**
- `_NON_RETRYABLE_PATTERNS` — 4xx codes and semantic error patterns
- Default: max_attempts=3, base_delay=1.0s (exponential: 1s, 2s, 4s)

**Dependencies:** None (stdlib only)

**Called by:** tts.py, stt.py, llm.py

---

### backend/rag.py

**Purpose:** Document store. Loads .txt, .meta.json, .brief.txt, .chunks.json, .structure.json at init. Provides get_context() for BM25 retrieval (or keyword fallback). One DocumentStore per session.

**Key classes:**

| Class | Description |
|---|---|
| DocumentStore | Holds all document artifacts. Retrieval via BM25 or keyword scorer. |

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| DocumentStore.__init__ | `(index_dir, name) -> None` | Load all document artifacts | index_dir str, name str | DocumentStore instance |
| DocumentStore.retrieve | `(query, top_k) -> str` | BM25 or keyword retrieval | query str, top_k int | Top-k chunks joined by separator |
| DocumentStore.get_context | `(query, top_k) -> str` | Retrieve with default query fallback | query str, top_k int | Retrieval result |

**Key constants:**
- `CHUNK_SIZE = 600` — chars per chunk (keyword fallback)
- `TOP_K = 4` — default chunks returned

**Dependencies:** ingestion (load functions), bm25_store (optional)

**Called by:** agent.py (self.store.get_context(), self.store.metadata, self.store.sales_brief, self.store.structure)

---

### backend/bm25_store.py

**Purpose:** BM25 (Okapi BM25) document retrieval with section-aware chunking. Builds index at ingestion, saves as chunks.json. Loads and rebuilds at DocumentStore init. Detects insurance section headers to keep semantically coherent chunks.

**Key classes:**

| Class | Description |
|---|---|
| BM25Store | Holds chunks list + BM25Okapi index. Build/save/load/retrieve. |

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| chunk_document | `(text: str) -> list[str]` | Section-aware chunking with fallback to paragraph chunking | document text | list of chunk strings |
| BM25Store.build | `(text: str) -> BM25Store` | Build index from document text | text | BM25Store |
| BM25Store.save | `(path: str) -> None` | Save chunks to JSON | path | writes file |
| BM25Store.load | `(path: str) -> BM25Store` | Load chunks, rebuild BM25 | path | BM25Store |
| BM25Store.retrieve | `(query, top_k) -> str` | BM25 scoring + ranked retrieval | query str, top_k int | Top-k chunks joined |

**Key constants:**
- `_SECTION_KEYWORDS` — 30 insurance section keyword patterns for header detection
- `_MIN_CHUNK_CHARS = 100`
- `_MAX_CHUNK_CHARS = 800`
- `_TARGET_CHUNK_CHARS = 500`

**Dependencies:** rank_bm25

**Called by:** ingestion.py (build + save), rag.py (load)

---

### backend/profile_extractor.py

**Purpose:** Deterministic regex-based extraction of customer facts from user text. Runs before every LLM call. No LLM, no network. Returns only fields that were actually matched.

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| extract_profile_fields | `(text: str) -> dict` | Main entry point. Returns dict of matched fields only. | user text str | dict with any of: age, smoker, income_range, dependents, marital_status, gender, policy_term, payment_frequency, liabilities_lakh, cover_amount_override_lakh, years_of_support, existing_cover_lakh |
| _extract_age | `(t: str) -> Optional[int]` | Regex patterns: "I'm 29", "age is 32", "29-year-old", "turned 35", Hindi word ages | lowercased text | int 18-75 or None |
| _extract_smoker | `(t: str) -> Optional[bool]` | Phrase matching: non-smoker phrases first, then smoker phrases | lowercased text | bool or None |
| _extract_income | `(t: str) -> Optional[str]` | Patterns: LPA, lakhs, monthly, earn/salary. Devanagari normalisation. Excludes loan/cover context. | lowercased text | str or None |
| _extract_dependents | `(t: str) -> Optional[int]` | Digit + word number forms: "2 kids", "no children", "two dependents"; Hindi phrases | lowercased text | int or None |
| _extract_marital | `(t: str) -> Optional[str]` | Phrase matching: married/single/divorced/widowed | lowercased text | str or None |
| _extract_gender | `(t: str) -> Optional[str]` | Phrase matching: "I'm a woman", "I am male" | lowercased text | str or None |
| _extract_policy_term | `(t: str) -> Optional[int]` | Patterns: "20-year term", "policy of 30 years", Hindi "20 साल" | lowercased text | int 5-50 or None |
| _extract_payment_frequency | `(t: str) -> Optional[str]` | Phrase matching: monthly/quarterly/semi_annual/annual | lowercased text | str or None |
| _extract_liabilities | `(t: str) -> Optional[float]` | Patterns: "home loan of 50 lakh", "outstanding 30 lakh" | lowercased text | float (lakh) or None |
| _extract_cover_override | `(t: str) -> Optional[float]` | Patterns: "I want 2 crore cover", "cover of 1 crore" | lowercased text | float (lakh) or None |
| _extract_years_of_support | `(t: str) -> Optional[int]` | NEW. Patterns: "support for 20 years", "next 15 years", "20 साल तक", "around 20 years". Loan context guard. | lowercased text | int 5-45 or None |
| _extract_existing_cover | `(t: str) -> Optional[float]` | NEW. Returns 0.0 for "no insurance" patterns. Returns lakh amount for existing cover amounts with existing-marker words. | lowercased text | float (lakh) or None |

**Note on existing cover gate:** `_extract_existing_cover` returns `0.0` (not None) when customer explicitly says "no insurance", "don't have insurance", "nahi insurance", etc. This 0.0 value is what makes `discovery_sufficient()` fire (since `existing_cover_lakh is not None` is the gate, and `0.0 is not None` is True).

**Dependencies:** None (stdlib re only)

**Called by:** agent.py chat() and record_turn() before LLM call

---

### backend/pipeline.py

**Purpose:** Streaming voice pipeline over WebSocket. LLM tokens → sentence splitter → parallel TTS → merged WAV → WebSocket binary frames. Eliminates inter-sentence audio gaps by merging all WAV blobs before sending.

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| run_voice_pipeline | `(websocket, session, message, stt_latency_ms) -> None` | Full async voice pipeline. Three phases: LLM stream, parallel TTS, done signal. | WebSocket, AgentSession, message str, stt_latency_ms int | Sends WebSocket frames |
| _merge_wav | `(wav_blobs: list[bytes]) -> bytes` | Merge WAV files: strip headers from blobs 2+, write one header | list of WAV bytes | merged WAV bytes or b"" |

**Key constants:**
- `_BOUNDARY = re.compile(r"[.!?।](?:\s|$)|(?<=\w)\n")` — sentence boundary pattern (includes Devanagari danda ।)
- `_MIN_SENTENCE_CHARS = 4`
- `_CHUNK = 8192` — WebSocket binary frame size in bytes

**WebSocket protocol (server → client):**
- `{"type": "sentence", "text": "..."}` — text frame for display
- Binary frame — merged WAV chunks (8192 bytes each)
- `{"type": "audio_end"}` — all audio sent
- `{"type": "done", "language": ..., "stage": ..., "profile": {...}}` — turn complete
- `{"type": "error", "message": "..."}` — LLM failure
- `{"type": "preparing_audio"}` — audio being synthesized

**Dependencies:** agent (TYPE_CHECKING), conversation_analyzer, tts

**Called by:** main.py ws_chat()

---

### backend/metrics.py

**Purpose:** JSONL logging of per-turn and per-session metrics to logs/turns.jsonl and logs/sessions.jsonl. No database — append-only flat files.

**Key classes:**

| Class | Description |
|---|---|
| TurnMetrics | Dataclass: session_id, turn_id, timestamp, latencies, char counts, language, stage, character, error flags |

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| log_turn | `(m: TurnMetrics) -> None` | Append turn metrics as JSONL | TurnMetrics | Writes to logs/turns.jsonl |
| log_session | `(session_id, memory, duration_s) -> None` | Append session summary as JSONL | session_id, SessionMemory, duration float | Writes to logs/sessions.jsonl |

**Dependencies:** memory (TYPE_CHECKING)

**Called by:** agent.py chat(), record_turn(), end_session()

---

### backend/evaluation.py

**Purpose:** Post-conversation coaching report. Formats full turn_log as transcript, calls GPT-4o-mini with EVALUATION_PROMPT, returns structured dict with evaluation text and key metrics.

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| evaluate_session | `(memory, character_name) -> dict` | Generate evaluation report | SessionMemory, character_name str | dict: {evaluation, lead_score, interest_level, close_readiness, buying_intent, stages_visited, objections_raised, objections_resolved, positive_signals, turn_count} |

**Dependencies:** llm, prompts, memory (TYPE_CHECKING)

**Called by:** main.py /evaluate endpoint

---

### backend/table_parser.py

**Purpose:** Deterministic premium table parser. Reads pdfplumber table objects and classifies them as premium tables. Handles Indian term insurance table formats (age×term, term×age, smoker/non-smoker column pairs). No LLM calls.

**Key constants:**
- `_AGE_HEADER_PATTERNS` — regex for age column headers
- `_TERM_HEADER_PATTERNS` — regex for term column headers
- `_PREMIUM_HEADER_PATTERNS` — regex for premium amount headers
- `_SMOKER_PATTERNS` — regex for smoker column labels
- `_PER_CRORE_PATTERNS` — regex for "per crore" basis label

**Dependencies:** None

**Called by:** structure_builder.py build_product_structure()

---

### backend/ingest_worker.py

**Purpose:** ORPHANED. Was an alternative ingestion worker pattern. Not used in the current flow. The active ingestion path is main.py → _run_ingestion() → ingest() via executor.

**Called by:** Nobody (orphaned)

---

## DEPENDENCY MAP (directed graph — A imports/calls B)

```
main.py
  → agent.py
  → evaluation.py
  → ingestion.py
  → pipeline.py
  → rag.py
  → stt.py
  → tts.py
  → characters.py

agent.py
  → characters.py
  → conversation_analyzer.py
  → errors.py
  → gap_engine.py                ← NEW
  → llm.py
  → memory.py
  → metrics.py
  → profile_extractor.py
  → prompts.py
  → recommendation.py
  → rag.py
  → cover_engine.py
  → quote_engine.py

gap_engine.py
  → memory.py (TYPE_CHECKING)

conversation_analyzer.py
  → memory.py (TYPE_CHECKING)

recommendation.py
  → memory.py (TYPE_CHECKING)

quote_engine.py
  → memory.py (TYPE_CHECKING)

cover_engine.py
  → memory.py (TYPE_CHECKING)

evaluation.py
  → llm.py
  → prompts.py
  → memory.py (TYPE_CHECKING)

ingestion.py
  → structure_builder.py
  → bm25_store.py
  → openai (external)
  → pdfplumber (external)

structure_builder.py
  → table_parser.py
  → openai (external)

rag.py
  → ingestion.py (load functions)
  → bm25_store.py (optional)

bm25_store.py
  → rank_bm25 (external)

pipeline.py
  → agent.py (TYPE_CHECKING)
  → conversation_analyzer.py
  → tts.py

tts.py
  → sarvamai (external)
  → errors.py

stt.py
  → sarvamai (external)
  → errors.py

llm.py
  → openai (external)
  → errors.py

metrics.py
  → memory.py (TYPE_CHECKING)

profile_extractor.py
  → (no project imports)

characters.py
  → (no project imports)

prompts.py
  → (no project imports)

errors.py
  → (no project imports)

memory.py
  → (no project imports)
```

---

## COMPONENT MAP (logical groupings)

**Voice I/O Layer**
- `stt.py` — audio → transcript (Sarvam saaras:v3)
- `tts.py` — text → audio (Sarvam bulbul:v3), normalization (EMIs, 100%, ₹ amounts)
- `pipeline.py` — WebSocket voice pipeline: LLM stream → parallel TTS → merged WAV

**Conversation Engine**
- `agent.py` — AgentSession, stage machine, system prompt assembly, rupee guard
- `conversation_analyzer.py` — META tag parsing, stage gate logic (new stage set), memory updates
- `memory.py` — all session state dataclasses (new fields: existing_cover_lakh, years_of_support, gap_lakh)
- `prompts.py` — all prompt templates and behavioral rules (new consultative stage intents)
- `characters.py` — persona registry (Arjun: twenty years experience)

**Profile Intelligence**
- `profile_extractor.py` — deterministic profile field extraction from user text (12 fields)
- `gap_engine.py` — deterministic protection gap calculator (NEW)
- `recommendation.py` — actuarial benchmark cover + premium estimates

**Retrieval**
- `rag.py` — DocumentStore, BM25 + fallback keyword retrieval
- `bm25_store.py` — BM25 index build/save/load

**Quote Engine**
- `cover_engine.py` — income-multiplier cover recommendation
- `quote_engine.py` — document-exact premium lookup + interpolation + GST

**Ingestion Pipeline**
- `ingestion.py` — PDF → text + metadata + brief + structure + chunks (skip-if-exists)
- `structure_builder.py` — premium table extraction + validation
- `table_parser.py` — deterministic PDF table parsing

**Infrastructure**
- `main.py` — FastAPI app, all HTTP/WS endpoints, session/job management
- `llm.py` — OpenAI GPT-4o-mini wrapper (stage-scoped temperature)
- `errors.py` — error types + retry utility
- `metrics.py` — JSONL turn and session logging
- `evaluation.py` — post-conversation coaching report

---

## INTERACTION MAP

### Ingestion Flow (one-time per PDF)

```
POST /upload
  → main._run_ingestion() [asyncio background task]
    → ingestion.ingest(pdf_path, DATA_DIR)
      → if brief + meta already exist: skip LLM regeneration (prevents revert bug)
      → ingestion.extract_text(pdf_path)     # pdfplumber
      → ingestion._extract_metadata(text)     # GPT-4o-mini call 1: 4 metadata fields
        → fallback: _extract_metadata_from_text(text)
      → ingestion._generate_product_profile(text, meta)  # GPT-4o-mini call 2: 9-section brief
        → fallback: _generate_brief_via_keywords(text, meta)
      → structure_builder.build_product_structure(text, pages_data, meta, doc_hash)
        → table_parser.parse_tables(pages_data)    # deterministic table extraction
        → if no tables: _gpt_extract_illustrative_premium(text)  # GPT call 3 (optional)
        → _validate_premium_rows(rows)
        → _extract_eligibility(text)
        → _extract_frequency_rules(text)
        → _assign_capability_level(premium_tables)
      → BM25Store.build(text)                 # rank_bm25 index
      → BM25Store.save(chunks_path)
      → writes: .txt, .meta.json, .brief.txt, .structure.json, .chunks.json
    → rag.DocumentStore(DATA_DIR, index_name)  # loads all artifacts into memory
    → AgentSession(store, character_id)        # creates session
    → _sessions[session_id] = session
    → _jobs[job_id] = {"status": "done", "session_id": ...}
```

### Per-Turn Conversation Flow (WebSocket voice path)

```
WebSocket message: {session_id, message, stt_latency_ms}
  → main.ws_chat()
    → pipeline.run_voice_pipeline(websocket, session, message, stt_latency_ms)

Phase 1 — LLM Stream:
  → session.chat_stream(message)
    → session.detect_language_from_text(message)     # Unicode code-point detection
    → session.memory.customer_profile.apply_updates(
        profile_extractor.extract_profile_fields(message))
    → session._build_messages(message)
      → (GREET/DISCOVERY) strip PREMIUMS from brief
      → (DISCOVERY) compute missing_fields_line (income-gated priority)
      → (GAP_CALC) build_gap_calculation(profile) → gap_to_prompt_block() → gap_block
      → (RECOMMEND/VARIANTS/CLOSE/OBJECTIONS) build_risk_narrative(profile)
      → (RECOMMEND/VARIANTS/EXPLAIN/CLOSE) recommendation.build_recommendation_block()
      → (CLOSE) cover_engine.recommend_cover() + quote_engine.generate_quote()
      → MAIN_SYSTEM_PROMPT.format(...)
      → [last 6 turns from turn_log as history]
    → llm.LLMClient.stream(messages, stage=memory.stage)  # stage-scoped temperature
    → yields tokens → token_queue
  → pipeline reads tokens, detects sentence boundaries
  → for each sentence: websocket.send_text({"type": "sentence", "text": ...})

Phase 2 — record turn + memory update:
  → session.record_turn(llm_ms, stt_ms)
    → parse_meta_tag(raw_response)              # strip META tag
    → if DISCOVERY: _guard_discovery_numbers(clean, profile)  # rupee safety filter
    → profile_extractor.extract_profile_fields(message)  # again for streaming path
    → apply_analysis(memory, analysis, message)  # stage gates + position_skip + scoring
    → _auto_advance_stage(memory, plan_type)     # Python stage control
    → metrics.log_turn(TurnMetrics(...))

Phase 3 — Parallel TTS:
  → asyncio.gather(*[tts.synthesize(sentence) for sentence in clean_sentences])
  → pipeline._merge_wav(wav_blobs)
  → websocket.send_bytes(merged_wav in 8192-byte chunks)
  → websocket.send_text({"type": "audio_end"})
  → websocket.send_text({"type": "done", "language": ..., "stage": ..., "profile": ...})
```

---

## CONSTANTS AND CONFIGURATION INDEX

| Constant | File | Value | Purpose |
|---|---|---|---|
| MODEL | llm.py | "gpt-4o-mini" | OpenAI model for all LLM calls |
| MAX_TOKENS | llm.py | 600 | Max response tokens per LLM call |
| TEMPERATURE | llm.py | 0.7 (default) | LLM temperature; stage-scoped overrides apply |
| TTS_MODEL | tts.py | "bulbul:v3" | Sarvam TTS model |
| SAMPLE_RATE | tts.py | 22050 | TTS audio sample rate |
| MAX_TTS_CHARS | tts.py | 400 | Hard limit before bulbul:v3 rejects input |
| MAX_AUDIO_BYTES | main.py | 10485760 (10MB) | Audio upload size limit |
| MAX_HISTORY_TURNS | agent.py | 6 | Turn pairs kept in LLM context |
| BRIEF_CHAR_LIMIT | agent.py | 3500 | Max brief chars in system prompt |
| DOC_CONTEXT_CHAR_LIMIT | agent.py | 1500 | Max BM25 context chars in system prompt |
| _NARRATIVE_STAGES | agent.py | ("RECOMMEND", "VARIANTS", "EXPLAIN", "CLOSE", "OBJECTIONS") | Stages where risk_narrative is injected |
| _DEFAULT_YEARS | gap_engine.py | 20 | Default years of support if not stated |
| _DEFAULT_EXISTING | gap_engine.py | 0.0 | Default existing cover if not stated |
| _DEFAULT_LIABILITIES | gap_engine.py | 0.0 | Default liabilities if not stated |
| _TERM_BASE_PREMIUM_PER_CRORE | recommendation.py | 8500 | Base ₹/crore/year for 25-yr non-smoker |
| _TERM_BASE_AGE | recommendation.py | 25 | Reference age for premium base |
| _AGE_LOADING_PER_YEAR | recommendation.py | 0.035 | 3.5% compound loading per year over base age |
| _SMOKER_LOADING | recommendation.py | 0.65 | 65% extra premium for smokers |
| _COVER_MULTIPLIER_WITH_DEPENDENTS | recommendation.py | 15 | Income multiplier with dependents |
| _COVER_MULTIPLIER_NO_DEPENDENTS | recommendation.py | 10 | Income multiplier without dependents |
| _COVER_CAP_LAKH | cover_engine.py | 1000 | Max recommended cover (₹10 crore) |
| _COVER_FLOOR_LAKH | cover_engine.py | 25 | Min recommended cover (₹25 lakh) |
| _GST_RATE | quote_engine.py | 0.18 | 18% GST on insurance premiums |
| _TERM_PREMIUM_MIN | structure_builder.py | 2000 | Actuarial validation floor ₹/crore/year |
| _TERM_PREMIUM_MAX | structure_builder.py | 500000 | Actuarial validation ceiling ₹/crore/year |
| CHUNK_SIZE | rag.py | 600 | Chars per chunk (keyword fallback) |
| TOP_K | rag.py | 4 | Default retrieval chunks |
| _MIN_CHUNK_CHARS | bm25_store.py | 100 | Min chunk size for BM25 store |
| _MAX_CHUNK_CHARS | bm25_store.py | 800 | Max chunk size for BM25 store |
| DEFAULT_CHARACTER | characters.py | "arjun" | Default character if none specified |
| DEFAULT_LANGUAGE | characters.py | "en-IN" | Default language code |
| _BOUNDARY | pipeline.py | `[.!?।](?:\s|$)` | Sentence boundary regex (includes Devanagari danda) |
| _MIN_SENTENCE_CHARS | pipeline.py | 4 | Skip too-short sentence fragments |
| Language commit threshold | memory.py | 0.7 | Min STT probability to commit language change |
| DISCOVERY 8-turn escape | agent.py | 8 | Max turns in DISCOVERY before Python forces advance |
| GREET single-turn escape | agent.py | 1 | Max turns in GREET before Python forces DISCOVERY |
| VARIANTS 6-turn escape | agent.py | 6 | Max turns in VARIANTS before Python forces CLOSE |
| PROCEED threshold | agent.py | 2 | Min turn_in_stage before Python forces CLOSED from PROCEED |

---

## DATA STRUCTURE INDEX

### CustomerProfile (memory.py)

| Field | Type | Default | Notes |
|---|---|---|---|
| age | Optional[int] | None | 18-75; gates discovery_sufficient |
| gender | Optional[str] | None | male/female/other |
| marital_status | Optional[str] | None | single/married/divorced/widowed |
| dependents | Optional[int] | None | count of dependents |
| smoker | Optional[bool] | None | None = unknown (premium suppressed) |
| existing_coverage | Optional[str] | None | none/some/adequate (categorical; kept for compat) |
| existing_cover_lakh | Optional[float] | None | 0.0 = "no insurance" answered; None = not asked; gates discovery_sufficient |
| financial_goal | Optional[str] | None | protection/savings/both/retirement/child |
| income_range | Optional[str] | None | free-text, parsed by gap_engine._parse_income_lpa; gates discovery_sufficient |
| health_conditions | Optional[str] | None | none/pre-existing |
| years_of_support | Optional[int] | None | years of income replacement needed; gates discovery_sufficient |
| chosen_variant | Optional[str] | None | selected variant at VARIANTS stage |
| policy_term | Optional[int] | None | years |
| payment_frequency | Optional[str] | None | annual/semi_annual/quarterly/monthly |
| liabilities_lakh | Optional[float] | None | lakh; input to gap_engine |
| cover_amount_override_lakh | Optional[float] | None | overrides all cover calculations |
| fields_collected | list[str] | [] | ordered list of field names added |

### CustomerIntelligence (memory.py)

| Field | Type | Default | Notes |
|---|---|---|---|
| interest_level | int | 50 | 0-100, cumulative |
| buying_intent | str | "unknown" | cold/warm/hot, derived |
| engagement_score | int | 50 | stub, not updated |
| close_readiness | int | 0 | 0-100, cumulative |
| gap_lakh | Optional[float] | None | computed protection gap; set at GAP_CALC stage |
| objections | list[dict] | [] | {text, category, turn, resolved} |
| positive_signals | list[str] | [] | not currently populated |
| hesitation_count | int | 0 | stub |
| deflection_count | int | 0 | stub |

### SessionMemory (memory.py)

| Field | Type | Default | Notes |
|---|---|---|---|
| character_id | str | "arjun" | |
| detected_language | str | "en-IN" | BCP-47 |
| language_confidence | float | 0.0 | last commit confidence |
| _language_candidate | str | "" | below-threshold candidate (unused) |
| stage | str | "GREET" | current stage (was "INTRODUCE" in old design) |
| previous_stage | Optional[str] | None | for QUESTION_ANSWER/OBJECTIONS return |
| return_to_stage | Optional[str] | None | set on QUESTION_ANSWER/OBJECTIONS entry |
| turn_in_stage | int | 0 | turns in current stage |
| close_substage | str | "PURCHASE_INTENT" | current substage (was "SUMMARY" in old design) |
| emotional_state | str | "curious" | from META tag |
| customer_profile | CustomerProfile | default | 15 fields |
| explain_subtopic_index | int | 0 | current topic index |
| explain_topics | list[str] | [] | lazy-init on EXPLAIN entry |
| customer_name | Optional[str] | None | not collected currently |
| position_skipped | bool | False | True if POSITION stage bypassed |
| questions_asked | list[str] | [] | customer "?" utterances |
| features_explained | list[str] | [] | stub |
| intelligence | CustomerIntelligence | default | |
| turn_count | int | 0 | total turns |
| turn_log | list[dict] | [] | {role, text, stage, turn} |

### TurnAnalysis (conversation_analyzer.py)

| Field | Type | Notes |
|---|---|---|
| stage | str | requested next stage (may be blocked) |
| interest_delta | int | -10 to +10 |
| objection_category | Optional[str] | price/trust/timing/need/comparison/family or None |
| objection_resolved | bool | True if LLM signals resolution |
| close_readiness_delta | int | -10 to +10 |
| emotional_state | str | curious/engaged/hesitant/resistant/anxious/satisfied |
| close_substage | str | only when stage=CLOSE |
| position_skip | bool | True when LLM signals POSITION should be bypassed (NEW) |

### TurnMetrics (metrics.py)

| Field | Type | Notes |
|---|---|---|
| session_id | str | UUID |
| turn_id | int | turn number |
| timestamp | float | unix timestamp |
| stt_latency_ms | int | |
| llm_latency_ms | int | |
| tts_latency_ms | int | |
| transcript_chars | int | user input length |
| response_chars | int | agent response length |
| detected_language | str | BCP-47 |
| stage | str | stage at time of turn |
| character | str | character_id |
| llm_error | bool | |
| error_detail | Optional[str] | |

### Gap Dict (gap_engine.py, from build_gap_calculation)

| Field | Type | Notes |
|---|---|---|
| income_lpa | float | parsed annual income in lakh per year |
| years_of_support | int | years used (stated or default 20) |
| income_protection_lakh | float | income_lpa × years_of_support |
| liabilities_lakh | float | outstanding loans used |
| existing_cover_lakh | float | existing cover used |
| gap_lakh | float | income_protection + liabilities − existing, floored at 0 |
| gap_display | str | "₹3.3 crore" or "₹50 lakh" |
| spoken_walkthrough | str | line-by-line calculation for Arjun to read aloud |
| assumptions_made | list[str] | list of defaults applied |

### Quote (quote_engine.py)

| Field | Type | Notes |
|---|---|---|
| cover_lakh | float | |
| policy_term | int | years |
| age | int | |
| smoker | bool | |
| annual_premium_base | int | pre-GST |
| gst_amount | int | 18% of base |
| annual_premium_total | int | post-GST |
| frequencies | dict[str, FrequencyBreakdown] | keyed by frequency string |
| capability_level | int | 0-3 |
| confidence | str | exact/interpolated/inferred |
| basis | str | per_crore_annual/per_lakh_annual |
| trail | list[str] | ordered calculation steps |

### structure.json schema (structure_builder.py)

| Field | Notes |
|---|---|
| schema_version | "1.0" |
| plan_name | from meta |
| plan_type | term/health/savings/ulip/pension/child/other |
| quote_capability_level | 0-3 |
| status | "approved" or "pending_review" |
| auto_approved | bool from env |
| document_hash | SHA-256 of PDF |
| eligibility | {min_entry_age, max_entry_age, min_policy_term, max_policy_term, min_sum_assured_lakh, max_sum_assured_lakh, confidence} |
| premium_tables | list of {variant, basis, smoker, rows, source_page, confidence, row_count} |
| payment_frequency_rules | {annual, semi_annual, quarterly, monthly, source} |
| gst_rate | 0.18 |
| variants | list of variant strings |
| missing_fields | list of missing field names |
| validation_warnings | list of warning strings |
| extraction_notes | pipe-separated log |
