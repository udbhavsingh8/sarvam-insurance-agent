# COMPLETE CODE INDEX

---

## BACKEND FILES

---

### backend/agent.py

**Purpose:** Stateful session object for the insurance sales agent. Wires together LLMClient, DocumentStore, SessionMemory, CharacterRegistry, ConversationAnalyzer, and metrics. One AgentSession per customer session.

**Key classes:**

| Class | Description |
|---|---|
| AgentSession | One session. Owns memory, LLM client, document store, character config. |

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| build_risk_narrative | `(profile: CustomerProfile) -> str` | Deterministic personalised risk story for system prompt injection | CustomerProfile dataclass | Multi-sentence risk narrative string or "" |
| _auto_advance_stage | `(memory: SessionMemory, plan_type: str) -> None` | Python stage transition controller — runs after every LLM turn | SessionMemory, plan_type string | Mutates memory.stage, memory.turn_in_stage |
| _auto_advance_close_substage | `(memory: SessionMemory) -> None` | Python close substage controller | SessionMemory | Mutates memory.close_substage |
| AgentSession.__init__ | `(store, character_id, session_id) -> None` | Initialize session with document store and character | DocumentStore, character_id str, optional session_id | AgentSession instance |
| AgentSession.generate_opener | `() -> str` | Build deterministic opening line — no LLM call | None (uses store.metadata) | Opening sentence string |
| AgentSession.chat | `(user_text: str) -> str` | Process one user turn, return agent response | User text string | Clean response string |
| AgentSession.chat_stream | `(user_text: str) -> Iterator[str]` | Stream agent response tokens | User text string | Token iterator |
| AgentSession.record_turn | `(llm_ms, stt_ms, tts_ms, ...) -> None` | Post-streaming: assemble response, parse META, update memory | Latency ints, error flags | Mutates memory; logs metrics |
| AgentSession.update_language | `(language_code: str, probability: float) -> None` | Propagate STT-detected language into memory | BCP-47 code, float probability | Mutates memory.detected_language |
| AgentSession.detect_language_from_text | `(text: str) -> None` | Unicode code-point language detection for typed text | User text | Mutates memory.detected_language |
| AgentSession.end_session | `() -> None` | Log session metrics | None | Logs to sessions.jsonl |
| AgentSession._build_messages | `(user_text: str) -> list[dict]` | Assemble full system prompt + history message list for LLM | User text | OpenAI messages list |

**Key constants (agent.py):**
- `MAX_HISTORY_TURNS = 6` (line 595) — last 12 log entries in context
- `BRIEF_CHAR_LIMIT = 3500` (line 459) — max sales brief chars in prompt
- `DOC_CONTEXT_CHAR_LIMIT = 1500` (line 460) — max BM25 context chars
- `_NARRATIVE_STAGES = ("NEED_DEVELOPMENT", "EXPLAIN", "RECOMMENDATION", "CLOSE", "HANDLE")` (line 512)
- `_FALLBACK = "I'm having a connection issue..."` (line 27)

**Dependencies:** characters, conversation_analyzer, errors, llm, memory, metrics, profile_extractor, prompts, recommendation, rag, cover_engine, quote_engine

**Called by:** main.py (via AgentSession), pipeline.py (via session.chat_stream, session.record_turn)

---

### backend/main.py

**Purpose:** FastAPI application. Exposes HTTP + WebSocket endpoints. Manages session and job dicts. Wires ingestion, voice pipeline, evaluation, and static frontend serving.

**Key classes:** None (all module-level)

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
- `MAX_AUDIO_BYTES = 10 * 1024 * 1024` (line 65) — 10MB audio limit
- `DATA_DIR` (line 45) — absolute path to data/ directory
- `_sessions: dict[str, AgentSession]` (line 47) — in-memory session store
- `_jobs: dict[str, dict]` (line 48) — in-memory job store
- `_session_locks: dict[str, asyncio.Lock]` (line 49) — per-session concurrency lock

**Dependencies:** agent, evaluation, ingestion, pipeline, rag, stt, tts, characters

**Called by:** Uvicorn ASGI server

---

### backend/prompts.py

**Purpose:** All prompt templates, stage intents, and behavioral rules. Pure data — no logic. Templates are string-formatted in agent.py _build_messages().

**Key classes:** None

**Key functions:**
| Function | Signature | Purpose |
|---|---|---|
| language_display_name | `(code: str) -> str` | BCP-47 code → display name ("hi-IN" → "Hindi") |

**Key constants:**
- `LANGUAGE_NAMES` (line 17) — BCP-47 → display name dict, 10 languages
- `VOICE_RULES` (line 37) — 6 formatting and hallucination rules
- `ADVISOR_RULES` (line 51) — 10 behavioral advisor rules
- `DEFLECTION_PLAYBOOK` (line 68) — 4 objection handling scripts
- `OPENER_PROMPT` (line 78) — UNUSED LLM opener template
- `STAGE_INTENTS` (line 119) — dict of 9 per-stage behavioral instructions
- `CLOSE_SUBSTAGE_INTENTS` (line 235) — dict of 5 substage instructions
- `META_TAG_INSTRUCTION` (line 283) — structured output tag format
- `MAIN_SYSTEM_PROMPT` (line 310) — master template with 21 placeholders
- `EVALUATION_PROMPT` (line 355) — post-conversation coaching report template

**Dependencies:** None

**Called by:** agent.py (all constants), evaluation.py (EVALUATION_PROMPT)

---

### backend/memory.py

**Purpose:** All session state dataclasses. CustomerProfile (collected facts), CustomerIntelligence (lead scoring), SessionMemory (full session state). No LLM calls.

**Key classes:**

| Class | Description |
|---|---|
| CustomerProfile | Progressively collected customer facts. 14 fields. |
| CustomerIntelligence | Live lead scoring: interest, close_readiness, objections, buying_intent. |
| SessionMemory | All session state: stage, substage, profile, intelligence, turn_log, language. |

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| choose_explain_topics | `(plan_type: str, profile: CustomerProfile) -> list[str]` | Return 3-4 relevant EXPLAIN topics for this plan type and profile | plan_type str, CustomerProfile | List of topic name strings |
| CustomerProfile.is_sufficient | `(plan_type: str) -> bool` | True when minimum profile fields for recommendation are present | plan_type str | bool |
| CustomerProfile.apply_updates | `(updates: dict) -> None` | Apply profile_extractor output to fields | dict of field:value | Mutates self |
| CustomerProfile.summary | `() -> str` | Format collected fields as readable bullet list | None | Multi-line string |
| CustomerIntelligence.lead_score | `() -> int` | Weighted score: 40% interest + 30% close_readiness + 15% objection resolution + 15% signals | None | int 0-100 |
| CustomerIntelligence.update_intent | `() -> None` | Derive buying_intent from interest_level and close_readiness | None | Mutates self.buying_intent |
| SessionMemory.update_language | `(language_code: str, confidence: float) -> None` | Commit language if confidence >= 0.70 | BCP-47 code, float | Mutates detected_language |
| SessionMemory.log_turn | `(role: str, text: str) -> None` | Append turn to turn_log | role str, text str | Mutates turn_log |
| SessionMemory.memory_summary | `() -> str` | Compact context block (~200 tokens) for system prompt injection | None | Multi-line summary string |
| SessionMemory.stages_visited | `() -> list[str]` | Ordered unique stages visited | None | list of stage strings |

**Key constants:**
- `EXPLAIN_SUBTOPICS` (line 7) — 8 default topic names (not used directly; choose_explain_topics generates plan-specific lists)

**Dependencies:** None (pure Python dataclasses)

**Called by:** agent.py (all), conversation_analyzer.py (apply_analysis), evaluation.py, metrics.py

---

### backend/conversation_analyzer.py

**Purpose:** Parses [META ...] tags from LLM responses and applies the resulting TurnAnalysis to SessionMemory. Contains all stage transition gate logic. Designed to be swappable (interface is parse_meta_tag + apply_analysis).

**Key classes:**

| Class | Description |
|---|---|
| TurnAnalysis | Dataclass: stage, interest_delta, objection_category, objection_resolved, close_readiness_delta, emotional_state, close_substage |

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| parse_meta_tag | `(text: str) -> tuple[str, Optional[TurnAnalysis]]` | Strip META tag, return clean text + analysis | Raw LLM response | (clean_text, TurnAnalysis or None) |
| apply_analysis | `(memory, analysis, user_text) -> None` | Apply TurnAnalysis to memory: stage gates, topic advance, scoring | SessionMemory, TurnAnalysis, user text | Mutates memory |
| _apply_close_substage | `(memory, requested) -> None` | Validate and apply close substage transition | SessionMemory, requested substage | Mutates memory.close_substage |

**Key constants:**
- `VALID_STAGES` (line 32) — set of 9 valid stage names
- `VALID_CLOSE_SUBSTAGES` (line 39) — set of 5 valid substage names
- `VALID_EMOTIONAL_STATES` (line 41) — set of 6 valid emotional state names
- `_META_PATTERN` (line 57) — compiled regex for `[META...]` tag
- `_CLOSE_SUBSTAGE_ORDER` (line 209) — ordered list of substages

**Dependencies:** memory (TYPE_CHECKING only)

**Called by:** agent.py (parse_meta_tag, apply_analysis), pipeline.py (parse_meta_tag)

---

### backend/recommendation.py

**Purpose:** Deterministic actuarial-benchmark-based cover and premium estimates. Injected into system prompt at EXPLAIN/RECOMMENDATION/CLOSE stages. Uses industry benchmarks when document rates are unavailable. Never calls LLM.

**Key classes:** None

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| build_recommendation_block | `(profile, plan_meta, brief_text) -> str` | Build compact text block for system prompt injection | CustomerProfile, plan metadata dict, brief text | Multi-line string or "" |
| _compute | `(profile, plan_type, brief_text) -> Optional[dict]` | Route to term/health/non-term rec | CustomerProfile, plan_type, brief | Result dict or None |
| _term_rec | `(profile, brief_text) -> Optional[dict]` | Term plan cover + premium calculation | CustomerProfile, brief text | Result dict with cover_display, premium_display |
| _health_rec | `(profile) -> Optional[dict]` | Health plan cover + premium calculation | CustomerProfile | Result dict |
| _non_term_guidance | `(profile, plan_type, brief_text) -> Optional[dict]` | Savings/ULIP/pension/child — cover guidance only, no premium | CustomerProfile, plan_type, brief | Result dict with premium_display=None |
| _parse_income_lpa | `(income_range: str) -> Optional[float]` | Parse income string to LPA float | income_range string | float or None |
| _extract_reference_premium | `(brief_text: str) -> Optional[int]` | Extract base annual premium per crore from brief PREMIUMS section | brief text | int or None |
| _format_cover | `(cover_lakh: float) -> str` | Format lakh amount to "₹X crore" or "₹X lakh" | float | str |

**Key constants:**
- `_TERM_BASE_PREMIUM_PER_CRORE = 8500` (line 28)
- `_TERM_BASE_AGE = 25` (line 29)
- `_AGE_LOADING_PER_YEAR = 0.035` (line 30)
- `_SMOKER_LOADING = 0.65` (line 31)
- `_COVER_MULTIPLIER_WITH_DEPENDENTS = 15` (line 32)
- `_COVER_MULTIPLIER_NO_DEPENDENTS = 10` (line 33)
- `_HEALTH_BASE_PREMIUM = 8000` (line 36)
- `_HEALTH_BASE_COVER_LAKH = 5` (line 37)

**Dependencies:** memory (TYPE_CHECKING)

**Called by:** agent.py _build_messages()

---

### backend/quote_engine.py

**Purpose:** Deterministic premium calculation from structure.json premium tables. Lookup → interpolation → GST → frequency loading → Quote object. Called at RECOMMENDATION/CLOSE when structure.json has tables. QuoteError raised (not swallowed) on missing data.

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
- `_DEFAULT_FREQ_RULES` (line 75) — annual/semi_annual/quarterly/monthly factors and counts
- `_GST_RATE = 0.18` (line 82)
- `_FREQ_LABELS` (line 84) — frequency → spoken label dict

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
- `_COVER_CAP_LAKH = 1000` (line 38) — ₹10 crore cap
- `_COVER_FLOOR_LAKH = 25` (line 39) — ₹25 lakh floor
- Multipliers: 20 (dependents + income < 10 LPA), 15 (dependents), 10 (no dependents) — lines 70-75

**Dependencies:** memory (TYPE_CHECKING)

**Called by:** agent.py _build_messages()

---

### backend/characters.py

**Purpose:** Character registry. Each entry defines identity, communication style, emotional handling scripts, and TTS voice speaker name. Product knowledge is separate (from DocumentStore). Two characters: arjun (active), lalita (inactive in UI).

**Key classes:** None

**Key constants:**
- `CHARACTERS: dict[str, dict]` (line 13) — character registry with "arjun" and "lalita"
- `SUPPORTED_LANGUAGES: dict[str, str]` (line 98) — BCP-47 → display name, 10 languages
- `DEFAULT_LANGUAGE = "en-IN"` (line 111)
- `DEFAULT_CHARACTER = "arjun"` (line 112)

**Character fields:** id, name, gender, persona, style_guide, emotional_guide, opener (unused ""), voice (Sarvam speaker name)

**Voice assignments:**
- arjun → "dev"
- lalita → "ritu"

**Dependencies:** None

**Called by:** agent.py (CHARACTERS.get()), main.py (CHARACTERS validation), tts.py (SUPPORTED_LANGUAGES)

---

### backend/ingestion.py

**Purpose:** Full document ingestion pipeline. Takes a PDF, produces .txt, .meta.json, .brief.txt, .structure.json, .chunks.json in data/. Two LLM calls (metadata + brief). Falls back to keyword extraction on LLM failure.

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| ingest | `(pdf_path: str, index_dir: str) -> tuple[int, str]` | Main entry point. Extracts, saves all artifacts. | pdf_path, index_dir | (page_count, name) |
| extract_text | `(pdf_path: str) -> str` | pdfplumber page-by-page text extraction | pdf_path | Full document text |
| _extract_pages_data | `(pdf_path: str) -> list[dict]` | Per-page text + tables for structure builder | pdf_path | [{page_num, text, tables}] |
| _extract_metadata | `(text: str) -> dict` | GPT-4o-mini → 4 metadata fields. Falls back to keyword extraction. | document text | {plan_name, company_name, plan_type, one_line_pitch} |
| _extract_metadata_from_text | `(text: str) -> dict` | Keyword-based metadata fallback | text | same dict |
| _generate_product_profile | `(text, meta) -> str` | LLM brief generation with keyword fallback | text, meta dict | Brief string |
| _generate_brief_via_llm | `(text, meta) -> str` | GPT-4o-mini brief generation. Returns "" on failure. | text, meta | Brief string or "" |
| _generate_brief_via_keywords | `(text, meta) -> str` | Keyword extraction fallback brief | text, meta | Brief string |
| _detect_plan_type | `(text, meta_type) -> str` | Keyword-based plan type detection. Text wins over meta hint. | text, meta_type | plan_type string |
| _extract_section | `(text, keywords, max_chars) -> str` | Extract relevant lines for given keywords (used for brief sections) | text, keywords, max_chars | Section text |
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
- `_TERM_PREMIUM_MIN = 2000` (line 30)
- `_TERM_PREMIUM_MAX = 500000` (line 31)
- `_DEFAULT_FREQUENCY_RULES` (line 119) — industry standard frequency factors

**Dependencies:** table_parser, openai

**Called by:** ingestion.py ingest()

---

### backend/tts.py

**Purpose:** Text-to-Speech using Sarvam bulbul:v3. Includes normalize_for_tts() which converts TTS-hostile patterns (₹ amounts, LPA, percentages, age hyphens) to spoken form.

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
- `TTS_MODEL = "bulbul:v3"` (line 146)
- `SAMPLE_RATE = 22050` (line 147)
- `MAX_TTS_CHARS = 400` (line 150)
- `_DEFAULT_SPEAKERS` (line 155) — all languages default to "anushka"
- `SUPPORTED_LANGUAGES` (line 168) — list of 10 BCP-47 codes

**Dependencies:** sarvamai, errors

**Called by:** main.py /speak endpoint, pipeline.py synthesize()

---

### backend/stt.py

**Purpose:** Speech-to-Text using Sarvam saaras:v3. Always uses language_code='unknown' for auto-detection. Returns transcript + language_code + language_probability.

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| transcribe | `(audio_bytes: bytes) -> dict` | Transcribe audio with retry. | audio bytes (webm) | {"transcript", "language_code", "language_probability"} |

**Key config:** model="saaras:v3", mode="codemix", language_code="unknown" (always)

**Dependencies:** sarvamai, errors

**Called by:** main.py /transcribe endpoint, pipeline.py (indirectly via main)

---

### backend/llm.py

**Purpose:** Thin wrapper over OpenAI chat completions. Exposes complete() (blocking) and stream() (iterator). Uses gpt-4o-mini. Retries via errors.retry_call.

**Key classes:**

| Class | Description |
|---|---|
| LLMClient | complete() and stream() methods |

**Key constants:**
- `MODEL = "gpt-4o-mini"` (line 16)
- `MAX_TOKENS = 600` (line 17)
- `TEMPERATURE = 0.7` (line 18)

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
- `_NON_RETRYABLE_PATTERNS` (line 44) — 4xx codes and semantic error patterns
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
- `CHUNK_SIZE = 600` (line 5) — chars per chunk (keyword fallback)
- `TOP_K = 4` (line 6) — default chunks returned

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
- `_SECTION_KEYWORDS` (line 29) — 30 insurance section keyword patterns for header detection
- `_MIN_CHUNK_CHARS = 100` (line 43)
- `_MAX_CHUNK_CHARS = 800` (line 44)
- `_TARGET_CHUNK_CHARS = 500` (line 45)

**Dependencies:** rank_bm25

**Called by:** ingestion.py (build + save), rag.py (load)

---

### backend/profile_extractor.py

**Purpose:** Deterministic regex-based extraction of customer facts from user text. Runs before every LLM call. No LLM, no network. Returns only fields that were actually matched.

**Key functions:**

| Function | Signature | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| extract_profile_fields | `(text: str) -> dict` | Main entry point. Returns dict of matched fields only. | user text str | dict with any of: age, smoker, income_range, dependents, marital_status, gender, policy_term, payment_frequency, liabilities_lakh, cover_amount_override_lakh |
| _extract_age | `(t: str) -> Optional[int]` | Regex patterns: "I'm 29", "age is 32", "29-year-old", "turned 35" | lowercased text | int 18-75 or None |
| _extract_smoker | `(t: str) -> Optional[bool]` | Phrase matching: non-smoker phrases first, then smoker phrases | lowercased text | bool or None |
| _extract_income | `(t: str) -> Optional[str]` | Patterns: LPA, lakhs, monthly, earn/salary. Returns human-readable string. | lowercased text | str or None |
| _extract_dependents | `(t: str) -> Optional[int]` | Digit + word number forms: "2 kids", "no children", "two dependents" | lowercased text | int or None |
| _extract_marital | `(t: str) -> Optional[str]` | Phrase matching: married/single/divorced/widowed | lowercased text | str or None |
| _extract_gender | `(t: str) -> Optional[str]` | Phrase matching: "I'm a woman", "I am male" | lowercased text | str or None |
| _extract_policy_term | `(t: str) -> Optional[int]` | Patterns: "20-year term", "policy of 30 years" | lowercased text | int 5-50 or None |
| _extract_payment_frequency | `(t: str) -> Optional[str]` | Phrase matching: monthly/quarterly/semi_annual/annual | lowercased text | str or None |
| _extract_liabilities | `(t: str) -> Optional[float]` | Patterns: "home loan of 50 lakh", "outstanding 30 lakh" | lowercased text | float (lakh) or None |
| _extract_cover_override | `(t: str) -> Optional[float]` | Patterns: "I want 2 crore cover", "cover of 1 crore" | lowercased text | float (lakh) or None |

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
- `_BOUNDARY = re.compile(r"[.!?।](?:\s|$)|(?<=\w)\n")` (line 33) — sentence boundary pattern (includes Devanagari danda ।)
- `_MIN_SENTENCE_CHARS = 4` (line 34)
- `_CHUNK = 8192` (line 190) — WebSocket binary frame size in bytes

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
- `_AGE_HEADER_PATTERNS` (line 23) — regex for age column headers
- `_TERM_HEADER_PATTERNS` (line 28) — regex for term column headers
- `_PREMIUM_HEADER_PATTERNS` (line 34) — regex for premium amount headers
- `_SMOKER_PATTERNS` (line 39) — regex for smoker column labels
- `_PER_CRORE_PATTERNS` (line 46) — regex for "per crore" basis label

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
  → llm.py
  → memory.py
  → metrics.py
  → profile_extractor.py
  → prompts.py
  → recommendation.py
  → rag.py
  → cover_engine.py
  → quote_engine.py

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
- `tts.py` — text → audio (Sarvam bulbul:v3), normalization
- `pipeline.py` — WebSocket voice pipeline: LLM stream → parallel TTS → merged WAV

**Conversation Engine**
- `agent.py` — AgentSession, stage machine, system prompt assembly
- `conversation_analyzer.py` — META tag parsing, stage gate logic, memory updates
- `memory.py` — all session state dataclasses
- `prompts.py` — all prompt templates and behavioral rules
- `characters.py` — persona registry

**Profile Intelligence**
- `profile_extractor.py` — deterministic profile field extraction from user text
- `recommendation.py` — actuarial benchmark cover + premium estimates

**Retrieval**
- `rag.py` — DocumentStore, BM25 + fallback keyword retrieval
- `bm25_store.py` — BM25 index build/save/load

**Quote Engine**
- `cover_engine.py` — income-multiplier cover recommendation
- `quote_engine.py` — document-exact premium lookup + interpolation + GST

**Ingestion Pipeline**
- `ingestion.py` — PDF → text + metadata + brief + structure + chunks
- `structure_builder.py` — premium table extraction + validation
- `table_parser.py` — deterministic PDF table parsing

**Infrastructure**
- `main.py` — FastAPI app, all HTTP/WS endpoints, session/job management
- `llm.py` — OpenAI GPT-4o-mini wrapper
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

GET /status/{job_id}
  → returns _jobs[job_id] until status="done"
```

### Per-Turn Conversation Flow (WebSocket voice path)

```
WebSocket message: {session_id, message, stt_latency_ms}
  → main.ws_chat()
    → pipeline.run_voice_pipeline(websocket, session, message, stt_latency_ms)

Phase 1 — LLM Stream:
  → session.chat_stream(message)                     # [executor]
    → session.detect_language_from_text(message)     # Unicode code-point detection
    → session.memory.customer_profile.apply_updates(  # pre-LLM profile extraction
        profile_extractor.extract_profile_fields(message))
    → session._build_messages(message)
      → choose_explain_topics(plan_type, profile)    # lazy init at EXPLAIN
      → recommendation.build_recommendation_block()  # at EXPLAIN/REC/CLOSE
      → cover_engine.recommend_cover(profile)        # at REC/CLOSE
      → quote_engine.generate_quote(profile, cover)  # at REC/CLOSE if structure exists
      → quote_engine.quote_to_prompt_block(quote)
      → agent.build_risk_narrative(profile)          # at ND/EXPLAIN/REC/CLOSE/HANDLE
      → MAIN_SYSTEM_PROMPT.format(...)
      → [last 6 turns from turn_log as history]
    → llm.LLMClient.stream(messages)                 # OpenAI streaming
    → yields tokens → token_queue
  → pipeline reads tokens, detects sentence boundaries
  → for each sentence: websocket.send_text({"type": "sentence", "text": ...})

Phase 2 — record turn + memory update:
  → session.record_turn(llm_ms, stt_ms)
    → parse_meta_tag(raw_response)                   # strip META tag
    → profile_extractor.extract_profile_fields(message)  # again for streaming path
    → apply_analysis(memory, analysis, message)      # stage gates + scoring
    → _auto_advance_stage(memory, plan_type)          # Python stage control
    → metrics.log_turn(TurnMetrics(...))

Phase 3 — Parallel TTS:
  → asyncio.gather(*[tts.synthesize(sentence) for sentence in clean_sentences])
  → pipeline._merge_wav(wav_blobs)
  → websocket.send_bytes(merged_wav in 8192-byte chunks)
  → websocket.send_text({"type": "audio_end"})
  → websocket.send_text({"type": "done", "language": ..., "stage": ..., "profile": ...})
```

### HTTP Voice Path (/chat without WebSocket)

```
POST /chat (stream=True → SSE)
  → token_generator() async generator
    → session.chat_stream(message) [executor]
    → yields "data: {token}\n\n"
    → session.record_turn() after streaming complete
    → yields "data: [DONE]\n\n"

POST /chat (stream=False → JSON)
  → session.chat(message) [executor]
    → full sequence: extract profile → build messages → LLMClient.complete() → parse_meta_tag → apply_analysis → _auto_advance_stage → log_turn
  → returns {"reply": ..., "language": ..., "stage": ..., "profile": {...}}
```

---

## CONSTANTS AND CONFIGURATION INDEX

| Constant | File | Line | Value | Purpose |
|---|---|---|---|---|
| MODEL | llm.py | 16 | "gpt-4o-mini" | OpenAI model for all LLM calls |
| MAX_TOKENS | llm.py | 17 | 600 | Max response tokens per LLM call |
| TEMPERATURE | llm.py | 18 | 0.7 | LLM temperature |
| TTS_MODEL | tts.py | 146 | "bulbul:v3" | Sarvam TTS model |
| SAMPLE_RATE | tts.py | 147 | 22050 | TTS audio sample rate |
| MAX_TTS_CHARS | tts.py | 150 | 400 | Hard limit before bulbul:v3 rejects input |
| MAX_AUDIO_BYTES | main.py | 65 | 10485760 (10MB) | Audio upload size limit |
| MAX_HISTORY_TURNS | agent.py | 595 | 6 | Turn pairs kept in LLM context |
| BRIEF_CHAR_LIMIT | agent.py | 459 | 3500 | Max brief chars in system prompt |
| DOC_CONTEXT_CHAR_LIMIT | agent.py | 460 | 1500 | Max BM25 context chars in system prompt |
| _TERM_BASE_PREMIUM_PER_CRORE | recommendation.py | 28 | 8500 | Base ₹/crore/year for 25-yr non-smoker |
| _TERM_BASE_AGE | recommendation.py | 29 | 25 | Reference age for premium base |
| _AGE_LOADING_PER_YEAR | recommendation.py | 30 | 0.035 | 3.5% compound loading per year over base age |
| _SMOKER_LOADING | recommendation.py | 31 | 0.65 | 65% extra premium for smokers |
| _COVER_MULTIPLIER_WITH_DEPENDENTS | recommendation.py | 32 | 15 | Income multiplier with dependents |
| _COVER_MULTIPLIER_NO_DEPENDENTS | recommendation.py | 33 | 10 | Income multiplier without dependents |
| _HEALTH_BASE_PREMIUM | recommendation.py | 36 | 8000 | ₹/year for ₹5 lakh family floater at age ~35 |
| _COVER_CAP_LAKH | cover_engine.py | 38 | 1000 | Max recommended cover (₹10 crore) |
| _COVER_FLOOR_LAKH | cover_engine.py | 39 | 25 | Min recommended cover (₹25 lakh) |
| _GST_RATE | quote_engine.py | 82 | 0.18 | 18% GST on insurance premiums |
| _TERM_PREMIUM_MIN | structure_builder.py | 30 | 2000 | Actuarial validation floor ₹/crore/year |
| _TERM_PREMIUM_MAX | structure_builder.py | 31 | 500000 | Actuarial validation ceiling ₹/crore/year |
| CHUNK_SIZE | rag.py | 5 | 600 | Chars per chunk (keyword fallback) |
| TOP_K | rag.py | 6 | 4 | Default retrieval chunks |
| _MIN_CHUNK_CHARS | bm25_store.py | 43 | 100 | Min chunk size for BM25 store |
| _MAX_CHUNK_CHARS | bm25_store.py | 44 | 800 | Max chunk size for BM25 store |
| DEFAULT_CHARACTER | characters.py | 112 | "arjun" | Default character if none specified |
| DEFAULT_LANGUAGE | characters.py | 111 | "en-IN" | Default language code |
| _BOUNDARY | pipeline.py | 33 | `[.!?।](?:\s|$)` | Sentence boundary regex (includes Devanagari danda) |
| _MIN_SENTENCE_CHARS | pipeline.py | 34 | 4 | Skip too-short sentence fragments |
| Language commit threshold | memory.py | 274 | 0.7 | Min STT probability to commit language change |

---

## DATA STRUCTURE INDEX

### CustomerProfile (memory.py, lines 49-171)

| Field | Type | Default | Notes |
|---|---|---|---|
| age | Optional[int] | None | 18-75 |
| gender | Optional[str] | None | male/female/other |
| marital_status | Optional[str] | None | single/married/divorced/widowed |
| dependents | Optional[int] | None | count of dependents |
| smoker | Optional[bool] | None | None = unknown (premium suppressed) |
| existing_coverage | Optional[str] | None | none/some/adequate or numeric |
| financial_goal | Optional[str] | None | protection/savings/both/retirement/child |
| income_range | Optional[str] | None | free-text, parsed by _parse_income_lpa |
| health_conditions | Optional[str] | None | none/pre-existing |
| policy_term | Optional[int] | None | years |
| payment_frequency | Optional[str] | None | annual/semi_annual/quarterly/monthly |
| liabilities_lakh | Optional[float] | None | lakh |
| cover_amount_override_lakh | Optional[float] | None | overrides all cover calculations |
| fields_collected | list[str] | [] | ordered list of field names added |

### CustomerIntelligence (memory.py, lines 174-208)

| Field | Type | Default | Notes |
|---|---|---|---|
| interest_level | int | 50 | 0-100, cumulative |
| buying_intent | str | "unknown" | cold/warm/hot, derived |
| engagement_score | int | 50 | stub, not updated |
| close_readiness | int | 0 | 0-100, cumulative |
| objections | list[dict] | [] | {text, category, turn, resolved} |
| positive_signals | list[str] | [] | not currently populated |
| hesitation_count | int | 0 | stub |
| deflection_count | int | 0 | stub |

### SessionMemory (memory.py, lines 211-348)

| Field | Type | Default | Notes |
|---|---|---|---|
| character_id | str | "arjun" | |
| detected_language | str | "en-IN" | BCP-47 |
| language_confidence | float | 0.0 | last commit confidence |
| _language_candidate | str | "" | below-threshold candidate (unused) |
| stage | str | "INTRODUCE" | current stage |
| previous_stage | Optional[str] | None | for HANDLE/QA return |
| return_to_stage | Optional[str] | None | set on QUESTION_ANSWER entry |
| turn_in_stage | int | 0 | turns in current stage |
| close_substage | str | "SUMMARY" | current substage (CLOSE only) |
| emotional_state | str | "curious" | from META tag |
| customer_profile | CustomerProfile | default | |
| explain_subtopic_index | int | 0 | current topic index |
| explain_topics | list[str] | [] | lazy-init on EXPLAIN entry |
| customer_name | Optional[str] | None | not collected currently |
| primary_need | Optional[str] | None | stub |
| family_context | Optional[str] | None | stub |
| existing_coverage | Optional[bool] | None | redundant with CustomerProfile |
| questions_asked | list[str] | [] | customer "?" utterances |
| features_explained | list[str] | [] | stub |
| intelligence | CustomerIntelligence | default | |
| turn_count | int | 0 | total turns |
| turn_log | list[dict] | [] | {role, text, stage, turn} |

### TurnAnalysis (conversation_analyzer.py, lines 46-54)

| Field | Type | Notes |
|---|---|---|
| stage | str | requested next stage (may be blocked) |
| interest_delta | int | -10 to +10 |
| objection_category | Optional[str] | price/trust/timing/need/comparison/family or None |
| objection_resolved | bool | True if LLM signals resolution |
| close_readiness_delta | int | -10 to +10 |
| emotional_state | str | curious/engaged/hesitant/resistant/anxious/satisfied |
| close_substage | str | only when stage=CLOSE |

### TurnMetrics (metrics.py, lines 17-33)

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
| stt_error | bool | |
| llm_error | bool | |
| tts_error | bool | |
| error_detail | Optional[str] | |

### Quote (quote_engine.py, lines 46-68)

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

### FrequencyBreakdown (quote_engine.py, lines 36-43)

| Field | Type | Notes |
|---|---|---|
| frequency | str | annual/semi_annual/quarterly/monthly |
| installment_amount | int | per installment after GST |
| installments_per_year | int | 1/2/4/12 |
| total_annual | int | installment × count |
| display | str | "₹5,200/month" |

### CoverRecommendation (cover_engine.py, lines 31-35)

| Field | Type | Notes |
|---|---|---|
| cover_lakh | float | recommended cover |
| cover_display | str | "₹1.5 crore" |
| rationale_steps | list[str] | ordered explanation steps |
| is_override | bool | True if customer explicitly stated a cover |

### structure.json schema (structure_builder.py, lines 345-361)

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
