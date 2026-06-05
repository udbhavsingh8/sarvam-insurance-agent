# AGENT DEFINITION, PROMPT ENGINEERING, GUARDRAILS, AND CODE TRACEABILITY

---

## A. AGENT INVENTORY

Every agent-like component in the system:

| Component | File | Lines | Type | Description |
|---|---|---|---|---|
| AgentSession | backend/agent.py | 229-605 | Stateful session object | One per customer session. Owns LLMClient, DocumentStore, SessionMemory, character config. Routes all user turns through the stage machine. |
| _auto_advance_stage | backend/agent.py | 118-202 | Python stage controller | Runs after every LLM turn. Has final say on stage transitions. Prevents LLM from skipping or looping stages. |
| _auto_advance_close_substage | backend/agent.py | 205-237 | Python close controller | Controls SUMMARY→PURCHASE_INTENT→PROCEED/FEEDBACK→CLOSED flow. |
| ConversationAnalyzer | backend/conversation_analyzer.py | 73-206 | META tag parser + memory updater | Parses `[META ...]` tag from LLM response. Applies signals to SessionMemory. |
| apply_analysis | backend/conversation_analyzer.py | 110-206 | Analysis applier | Applies TurnAnalysis to memory: stage transition gates, interest/readiness updates, objection tracking, topic advance. |
| build_recommendation_block | backend/recommendation.py | 40-72 | Deterministic cover + premium estimator | Called at EXPLAIN/RECOMMENDATION/CLOSE. Returns compact text block with cover recommendation and premium estimate (actuarial benchmarks). |
| recommend_cover | backend/cover_engine.py | 42-103 | Cover amount calculator | Deterministic income-multiplier-based cover calculation. Called before CLOSE for quote_engine input. |
| generate_quote | backend/quote_engine.py | 94-197 | Premium lookup and interpolation | Finds best matching premium rows in structure.json, interpolates, applies GST and frequency loading. Returns Quote object. |
| ingest | backend/ingestion.py | 451-499 | Document pipeline | Extracts text, generates metadata + brief + structure.json + chunks.json. One-time per PDF. |
| build_product_structure | backend/structure_builder.py | 260-363 | Structure extractor | Deterministic table extraction + GPT fallback + actuarial validation. Outputs structure.json. |
| evaluate_session | backend/evaluation.py | (called from main.py) | Post-conversation evaluator | Runs EVALUATION_PROMPT against full transcript. Returns coaching report. |
| extract_profile_fields | backend/profile_extractor.py | (called from agent.py) | Profile field extractor | Deterministic regex-based extraction of age, smoker, income, dependents, marital_status from user text. Called before LLM on every turn. |
| DocumentStore | backend/rag.py | (loaded by AgentSession) | Retrieval + document state | Holds sales_brief, metadata, structure.json, BM25 index. Provides get_context() for document retrieval. |
| LLMClient | backend/llm.py | (used by AgentSession) | OpenAI API wrapper | complete() and stream() methods. Wraps gpt-4o-mini calls. |

---

## B. SYSTEM PROMPT INVENTORY

### B.1 MAIN_SYSTEM_PROMPT (prompts.py, lines 310-351)

The master template assembled by `_build_messages()` in agent.py. Injected as the `system` message in every LLM call.

**Template placeholders explained:**

| Placeholder | Source | Stage availability | Purpose |
|---|---|---|---|
| `{name}` | characters.py `character["name"]` | All | Advisor's first name ("Arjun") |
| `{persona}` | characters.py `character["persona"]` | All | 5-sentence character backstory |
| `{style_guide}` | characters.py `character["style_guide"]` | All | Communication style rules |
| `{emotional_guide}` | characters.py `character["emotional_guide"]` | All | Objection handling emotional scripts |
| `{sales_brief}` | DocumentStore.sales_brief (truncated to 3500 chars) | All (PREMIUMS stripped at INTRODUCE/PROFILE/NEED_DEV) | Product knowledge from ingestion |
| `{document_context}` | DocumentStore.get_context() top-3 BM25 chunks (1500 chars) | All | Raw document passages for specific fact questions |
| `{language_name}` | memory.detected_language via language_display_name() | All | Current detected language display name |
| `{customer_profile}` | CustomerProfile.summary() | All | Collected profile fields as bullet list |
| `{missing_fields_line}` | Computed from CustomerProfile at PROFILE stage only | PROFILE only | "STILL NEEDED FROM CUSTOMER: age, smoker status..." |
| `{risk_narrative}` | build_risk_narrative() — deterministic Python | NEED_DEVELOPMENT, EXPLAIN, RECOMMENDATION, CLOSE, HANDLE | "CUSTOMER RISK NARRATIVE" — personalised vulnerability story |
| `{memory_summary}` | SessionMemory.memory_summary() | All | Compact context: questions asked, features explained, active objection, lead score |
| `{recommendation_block}` | build_recommendation_block() or "" | EXPLAIN, RECOMMENDATION, CLOSE | "CALCULATED NUMBERS FOR THIS CUSTOMER" actuarial estimates |
| `{policy_quote}` | quote_to_prompt_block() or "" | RECOMMENDATION, CLOSE (when structure.json has tables) | "QUOTE FOR THIS CUSTOMER" deterministic premium with full calculation trail |
| `{stage}` | memory.stage | All | Current stage name |
| `{explain_subtopic_line}` | Computed from memory.explain_topics and explain_subtopic_index | EXPLAIN only | "EXPLAIN TOPIC NOW: Coverage And Sum Assured (topic 1 of 4 | Next: ...)" |
| `{close_substage_line}` | memory.close_substage | CLOSE only | "CLOSE SUBSTAGE: PURCHASE_INTENT" |
| `{stage_intent}` | STAGE_INTENTS[stage] or CLOSE_SUBSTAGE_INTENTS[substage] | All | Per-stage behavioral instruction |
| `{voice_rules}` | VOICE_RULES constant | All | Formatting and speech style rules |
| `{advisor_rules}` | ADVISOR_RULES constant | All | Behavioral rules for advisor |
| `{deflection_playbook}` | DEFLECTION_PLAYBOOK or "" | EXPLAIN, NEED_DEVELOPMENT, RECOMMENDATION, HANDLE only | Objection response scripts |
| `{meta_tag_instruction}` | META_TAG_INSTRUCTION constant | All | Instructions for appending [META ...] tag |

---

### B.2 OPENER_PROMPT (prompts.py, lines 78-115)

**Status: UNUSED.** The OPENER_PROMPT was the original LLM-generated opener. It is now superseded by the deterministic `generate_opener()` method in agent.py (lines 245-263). The prompt remains in prompts.py as documentation.

Placeholders: `{name}`, `{persona}`, `{style_guide}`, `{language_name}`, `{plan_name}`, `{company_name}`, `{one_line_pitch}`

Why removed: The LLM would produce `[Name]` placeholders, invent customer details, and produce English openers for Hindi sessions.

---

### B.3 STAGE_INTENTS dict (prompts.py, lines 119-231)

One entry per stage. Each is injected as `{stage_intent}` in the system prompt.

| Stage | Purpose |
|---|---|
| INTRODUCE | Give a 2-sentence plan overview, ask permission to collect profile. Critical: do not invent demographic assumptions. |
| PROFILE | Collect age, smoker, income, family, existing coverage. Never re-ask known fields. Ask smoker last. When complete, immediately ask NEED_DEVELOPMENT question. |
| PERSONALIZE | Vestigial bridge — "Transition naturally into NEED_DEVELOPMENT." |
| NEED_DEVELOPMENT | Help customer feel financial risk before pitching. Pick one question from 4 scenarios (married/no deps, has deps, no coverage, has loans). After answer, transition to EXPLAIN. |
| EXPLAIN | One topic per turn from EXPLAIN TOPIC NOW. Connect every response to CUSTOMER RISK NARRATIVE. Use CALCULATED NUMBERS if available. Never invent premiums. |
| RECOMMENDATION | Name their risk, connect plan to it, state cost from CALCULATED NUMBERS, make the direct ask. Never say "summary". Advance to CLOSE after delivering. |
| HANDLE | Understand what "no" means (permission vs. concern vs. price). Acknowledge → Explore → Respond → Continue. Never say goodbye at HANDLE stage. |
| CLOSE | "Follow the CLOSE SUBSTAGE instruction exactly." Delegates to CLOSE_SUBSTAGE_INTENTS. |
| QUESTION_ANSWER | Answer using actual profile, not generic examples. Use only document facts. Bridge back after answering. |

---

### B.4 CLOSE_SUBSTAGE_INTENTS dict (prompts.py, lines 235-279)

| Substage | Purpose | Auto-advance condition |
|---|---|---|
| SUMMARY | Present personalised policy summary using only collected profile + CALCULATED NUMBERS + document. Open with "Based on the information you shared...". Do NOT ask to proceed. | Python auto-advances to PURCHASE_INTENT after 1 turn |
| PURCHASE_INTENT | Ask one clear question: "Would you like to proceed with purchasing this policy?" | LLM signals PROCEED or FEEDBACK based on customer response |
| PROCEED | Deliver handoff message only: payment/onboarding link will be sent. Do NOT collect personal details, invent steps, or generate URLs. End conversation. | Python auto-advances to CLOSED after 1 turn |
| FEEDBACK | Thank customer, ask what influenced their decision. Listen, reflect, do not re-sell. | LLM signals CLOSED after collecting. Python forces CLOSED after 3 turns. |
| CLOSED | Warm brief closing. Nothing else. Conversation complete. | Terminal state |

---

### B.5 META_TAG_INSTRUCTION (prompts.py, lines 283-306)

Full text instructs the LLM to append a structured tag to every response:
```
[META stage=STAGE interest_delta=N objection=TYPE emotional_state=STATE close_readiness_delta=N close_substage=SUBSTAGE]
```

Field meanings:
- `stage`: Where THIS response should move the conversation. Python validates and may block.
- `interest_delta`: -10 to +10. Added to `intelligence.interest_level` (0-100).
- `close_readiness_delta`: -10 to +10. Added to `intelligence.close_readiness` (0-100).
- `objection`: price|trust|timing|need|comparison|family|none. Logged to `intelligence.objections`.
- `emotional_state`: curious|engaged|hesitant|resistant|anxious|satisfied. Sets `memory.emotional_state`.
- `close_substage`: Only when stage=CLOSE. PURCHASE_INTENT|PROCEED|FEEDBACK|CLOSED.

Also contains the complete stage transition table (allowed transitions) to guide the LLM.

---

### B.6 VOICE_RULES (prompts.py, lines 37-47)

All rules:
1. 2-3 sentences max. No lists, bullets, headers, or markdown.
2. No filler openers: "Certainly!", "Absolutely!", "Great question!", "यह जानकर अच्छा लगा", "धन्यवाद"
3. Never say "death" — say "if something were to happen to you"
4. Never end a sentence with a colon — always complete the thought
5. NEVER repeat back what the customer just said. Do not confirm, rephrase, or summarise. Move to next question directly. (With BAD/GOOD examples)
6. HALLUCINATION IS FORBIDDEN: if a fact/figure is not in the document or CALCULATED NUMBERS block, say exactly: "That specific detail isn't in what I have — I'd recommend checking with the insurer directly."

---

### B.7 ADVISOR_RULES (prompts.py, lines 51-64)

All rules:
1. Can ask 2-3 related questions together naturally. Never explain WHY.
2. Reflect briefly on what the customer said before moving forward.
3. ALWAYS use customer's collected profile in every answer.
4. NEVER re-ask for information already in CUSTOMER PROFILE.
5. NEVER assume customer details not in CUSTOMER PROFILE.
6. If customer asks a question: answer using document facts, then return to stage.
7. Numbers must come from the document or CALCULATED NUMBERS block only.
8. If detail not in document: say exactly "That specific detail isn't in what I have..."
9. No pressure, no urgency. Frame protection positively.
10. Watch for buying signals. When signals appear, shift to recommending and closing.

---

### B.8 DEFLECTION_PLAYBOOK (prompts.py, lines 68-74)

Active only at EXPLAIN, NEED_DEVELOPMENT, RECOMMENDATION, HANDLE stages.

Objection responses:
- "Too expensive" → Ask what they expected, translate to daily cost (annual ÷ 365), mention 80C deduction.
- "Already have a policy" → "Do you know exactly what it covers if you were ill for 3 months?"
- "Claims don't get paid" → Cite document claim settlement facts only. Never invent statistics.
- "Spouse/father decides" → "That makes sense. What would help you explain this to them?"

---

### B.9 EVALUATION_PROMPT (prompts.py, lines 355-397)

Post-conversation coaching report. Injected once per session at /evaluate endpoint.

Placeholders: `{transcript}`, `{character_name}`, `{turn_count}`, `{stages_visited}`, `{interest_level}`, `{close_readiness}`, `{buying_intent}`, `{objections_detail}`, `{lead_score}`

Evaluation sections produced:
1. CONVERSATION NATURALNESS (score 1-10)
2. LISTENING QUALITY (score 1-10)
3. OBJECTIONS RAISED (list)
4. OBJECTIONS HANDLED (which handled well, which missed)
5. FACTUAL ACCURACY (hallucinations, invented numbers)
6. LEAD SCORE: N/100 with explanation
7. MISSED OPPORTUNITIES (buying signals ignored, stages too fast)
8. RECOMMENDED NEXT ACTION (one specific action for next interaction)

---

### B.10 Ingestion Brief Prompt (ingestion.py, lines 281-311)

Located in `_generate_brief_via_llm()`. Sends document sections to GPT-4o-mini.

Critical instruction (lines 301-310):
```
PREMIUMS: describe the premium payment structure only — frequency options, any loading factors,
and minimum premium if stated. Do NOT include illustrative rupee amounts, per-day costs,
sample calculations, or "starting from" figures.
```

Output section labels: COVERAGE | PREMIUMS | ELIGIBILITY | DEATH BENEFIT | MATURITY BENEFIT | RIDERS | TAX BENEFITS | EXCLUSIONS | PITCH

Max output: 1800 characters (enforced by prompt instruction).

---

### B.11 Ingestion Metadata Prompt (ingestion.py, lines 49-60)

Located in `_extract_metadata()`. First 1500 chars of document → 4 fields.

```
plan_name: <exact plan name>
company_name: <insurance company or bank name>
plan_type: <one of: term, health, savings, ulip, pension, child, other>
one_line_pitch: <one spoken sentence, max 18 words>
```

Temperature 0.1. Falls back to `_extract_metadata_from_text()` on any failure.

---

### B.12 Structure Builder GPT Fallback Prompt (structure_builder.py, lines 163-190)

Located in `_gpt_extract_illustrative_premium()`. Used when deterministic table parser finds no premium tables.

Sends premium-related text lines to GPT-4o-mini. Returns JSON array:
```json
[{"age": 30, "term": 20, "annual_premium": 8500}, ...]
```

Temperature 0.0. Maximum 400 tokens. Validates each entry: age 15-75, term 5-55, premium 1000-1,000,000. Returns empty list on failure.

---

## C. PERSONA ENGINEERING ANALYSIS

### Arjun (characters.py, lines 19-56)

**persona (lines 20-26):**
> "a high-performing insurance advisor in his early 30s with eight years of field experience. He is energetic, confident, and genuinely consultative — he listens carefully, then connects the product directly to the customer's situation. He moves conversations forward with purpose. He is warm and engaging without being pushy. His goal is always to help the customer make the right decision — and he is skilled at recognising when a customer is ready to move forward."

**style_guide (lines 28-41):**
> "Be confident, energetic, and direct — like a top-performing advisor on a live call. Always personalise: use the customer's actual age, income, and family situation in every answer. Never give a generic example when you already know the customer's profile. Translate numbers into real life: monthly cost, daily cost, what it buys the family. Keep responses tight — every sentence must carry weight, no filler, no meta-commentary. Never explain why you are asking something — just ask it naturally. Never start a sentence that ends with a colon — complete your thought in the same sentence. When you do not know a specific number: say so, never guess. Never say: 'Absolutely!', 'Certainly!', 'Great question!', 'As per the policy', 'This helps determine', 'This allows me to'. Never use the word 'death' — always 'if something were to happen to you'."

**emotional_guide (lines 43-53):**
> "Price shock: Do not defend the premium immediately. Ask 'What were you expecting?' Then reframe: translate annual premium to monthly or daily cost, mention 80C tax benefit. Hesitation: Ask 'What's the one thing you'd want to be sure about before deciding?' 'My spouse decides': Say 'Makes sense — what would help you explain this to them?' 'I already have cover': Ask 'Do you know what it covers if something serious happened?' Claims distrust: Use claim settlement facts from the document. If not available, say so honestly. Anxious customer: Slow down, be more concrete — give them a specific number or fact to hold onto. Rude or dismissive: Stay calm. Say 'No problem — happy to answer any questions you have.' Never guilt-trip. Never create urgency. Never pressure."

**voice:** "dev" (Sarvam bulbul:v3 speaker)

### Lalita (characters.py, lines 58-95) — defined but inactive in UI

**persona:** Female advisor, early 40s, twelve years experience. Patient, empathetic, thorough. "A quiet closer: she earns the sale through trust, not pressure."

**voice:** "ritu" (Sarvam bulbul:v3 speaker)

**Note:** The `opener` field on both characters is `""` — generate_opener() builds the opener dynamically from document metadata. The opener field is vestigial.

---

## D. GUARDRAILS ANALYSIS

### D.1 Premium Hallucination — Structural

**Layer 1 — Brief generation (ingestion.py, lines 301-310):**
The ingestion prompt explicitly forbids rupee amounts in the PREMIUMS brief section. The brief never contains "₹22/day" or "starting from ₹8,060/year".

**Layer 2 — Brief stripping at early stages (agent.py, lines 469-476):**
```python
if self.memory.stage in ("INTRODUCE", "PROFILE", "NEED_DEVELOPMENT"):
    brief = re.sub(r'PREMIUMS:.*?(?=\n[A-Z ]+:|$)', '', brief, flags=re.DOTALL | re.IGNORECASE).strip()
```
Even if the brief contains premium text, it is stripped before the system prompt is built.

**Layer 3 — VOICE_RULES hallucination prohibition (prompts.py, line 46):**
"HALLUCINATION IS FORBIDDEN: if a fact, figure, or process step is not in the product document or the CALCULATED NUMBERS block, say exactly: 'That specific detail isn't in what I have — I'd recommend checking with the insurer directly.'"

**Layer 4 — ADVISOR_RULES (prompts.py, lines 59-60):**
"Numbers must come from the document or the CALCULATED NUMBERS block only. Never invent or approximate."

**Layer 5 — smoker=None premium suppression (recommendation.py, lines 124-133):**
```python
if profile.smoker is None:
    return {"premium_display": None, ...}  # cannot estimate without smoker status
```
The recommendation block explicitly returns `premium_display: None` if smoker status is unknown, preventing the recommendation block from showing a premium figure.

---

### D.2 Stage Transition Gates (conversation_analyzer.py, apply_analysis)

| Gate | Location | Rule |
|---|---|---|
| I-9: Block PROFILE → EXPLAIN/CLOSE/RECOMMENDATION | conversation_analyzer.py lines 120-121 | LLM cannot force these transitions from PROFILE. Python's `_auto_advance_stage` is the only allowed path. |
| Gate PROFILE → PERSONALIZE with minimum fields | conversation_analyzer.py lines 124-134 | Requires age + (smoker OR income_range) before allowing PERSONALIZE. |
| Block NEED_DEVELOPMENT → anything except EXPLAIN/QA/HANDLE | conversation_analyzer.py lines 138-139 | Prevents LLM from jumping from need development to CLOSE. |
| Block EXPLAIN → CLOSE directly | conversation_analyzer.py lines 142-145 | Redirects to RECOMMENDATION instead: "Treat as RECOMMENDATION intent". |
| QUESTION_ANSWER return logic | conversation_analyzer.py lines 147-151 | Returns to `return_to_stage` (where QA was interrupted from) rather than wherever LLM wants to go. |

---

### D.3 Python Escape Hatches (_auto_advance_stage)

| Stage | Escape condition | Action |
|---|---|---|
| INTRODUCE | turn_in_stage >= 2 | Force advance to PROFILE |
| PROFILE | profile.is_sufficient(plan_type) | Force advance to NEED_DEVELOPMENT |
| NEED_DEVELOPMENT | turn_in_stage >= 2 | Force advance to EXPLAIN |
| PERSONALIZE | Always (unconditional) | Force advance to NEED_DEVELOPMENT |
| RECOMMENDATION | turn_in_stage >= 1 | Force advance to CLOSE (skip SUMMARY, set PURCHASE_INTENT) |
| EXPLAIN | All topics done + 1 turn on last topic, OR close_readiness >= 50 + 2 turns, OR 6 turns total | Force advance to RECOMMENDATION |
| HANDLE/QUESTION_ANSWER | turn_in_stage >= 1 | Return to `return_to_stage` or `previous_stage` or EXPLAIN |

---

### D.4 Forbidden Behaviors in CLOSE/PROCEED (prompts.py, lines 257-266)

At PROCEED substage, the LLM is explicitly prohibited from:
- Collecting any personal details (name, address, contact, health, nominee, income)
- Asking the customer to fill a form "here" or "online"
- Inventing or describing application steps
- Generating payment links, URLs, or policy numbers
- Asking any further questions

---

### D.5 CLOSE Substage Ordering (_apply_close_substage, conversation_analyzer.py lines 212-236)

The `allowed_next` dict prevents substage skipping:
```
SUMMARY         → {PURCHASE_INTENT}
PURCHASE_INTENT → {PROCEED, FEEDBACK}
PROCEED         → {CLOSED}
FEEDBACK        → {CLOSED}
CLOSED          → {} (terminal, no transitions)
```

---

### D.6 Audio Size Limit (main.py, line 65)

```python
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB
```

Enforced at the `/transcribe` endpoint. Requests exceeding 10MB return HTTP 413.

---

### D.7 Language Commit Threshold (memory.py, line 274)

```python
if not language_code or confidence < 0.7:
    return
```

Language commits only when Sarvam STT returns `language_probability >= 0.70`. Below this threshold, the current language is preserved. This prevents a single ambiguous utterance from switching the response language.

---

## E. TOOL CALLING ANALYSIS

There are no OpenAI function/tool calls in this system. All "tools" are deterministic Python functions called directly by the agent code before or after the LLM call.

| "Tool" | Type | Location | Called when |
|---|---|---|---|
| extract_profile_fields | Pre-LLM Python | profile_extractor.py, called in agent.py line 279 | Every turn, before LLM call |
| build_recommendation_block | Pre-LLM Python | recommendation.py, called in agent.py line 525 | EXPLAIN/RECOMMENDATION/CLOSE stages |
| recommend_cover | Pre-LLM Python | cover_engine.py, called in agent.py line 534 | RECOMMENDATION/CLOSE when structure exists |
| generate_quote | Pre-LLM Python | quote_engine.py, called in agent.py line 540 | RECOMMENDATION/CLOSE when structure exists |
| build_risk_narrative | Pre-LLM Python | agent.py line 30, called in agent.py line 514 | NEED_DEVELOPMENT/EXPLAIN/RECOMMENDATION/CLOSE/HANDLE |
| choose_explain_topics | Pre-LLM Python | memory.py line 14, called in agent.py line 438 | First turn of EXPLAIN (lazy init) |
| parse_meta_tag | Post-LLM Python | conversation_analyzer.py line 73, called in agent.py lines 291, 351 | After every LLM response |
| apply_analysis | Post-LLM Python | conversation_analyzer.py line 110, called in agent.py lines 304, 364 | After every LLM response with valid META tag |
| _auto_advance_stage | Post-LLM Python | agent.py line 118, called in agent.py lines 306, 367 | After every turn |

---

## F. MEMORY ANALYSIS

### CustomerProfile (memory.py, lines 49-171)

| Field | Type | Purpose | How populated |
|---|---|---|---|
| age | Optional[int] | Customer's age. Drives premium calculation and cover multiplier. | profile_extractor regex on user text |
| gender | Optional[str] | male/female/other. Informational only — not used in premium calculation. | profile_extractor |
| marital_status | Optional[str] | single/married/divorced/widowed. Used in `is_sufficient()` as family context and in risk narrative. | profile_extractor |
| dependents | Optional[int] | Number of dependents. Drives cover multiplier (10x → 15x → 20x). | profile_extractor |
| smoker | Optional[bool] | Smoker status. Applied as 65% loading in recommendation.py. If None, premium suppressed. | profile_extractor |
| existing_coverage | Optional[str] | none/some/adequate. Used in risk narrative and cover calculation (subtracts existing coverage). | profile_extractor |
| financial_goal | Optional[str] | protection/savings/both/retirement/child. Not used in current business logic. | profile_extractor |
| income_range | Optional[str] | Free-text income string. Parsed to LPA by `_parse_income_lpa()`. Drives cover amount. | profile_extractor |
| health_conditions | Optional[str] | none/pre-existing. Informational for health plans. | profile_extractor |
| policy_term | Optional[int] | Requested term in years. Used by quote_engine (falls back to `_default_term(age) = 65 - age`). | profile_extractor |
| payment_frequency | Optional[str] | annual/semi_annual/quarterly/monthly. Used by quote_engine for frequency breakdown. | profile_extractor |
| liabilities_lakh | Optional[float] | Outstanding loans. Added to cover calculation in cover_engine. | profile_extractor |
| cover_amount_override_lakh | Optional[float] | Customer-stated explicit cover amount. Overrides all cover calculations. | profile_extractor |
| fields_collected | list[str] | List of field names collected so far. Used by summary() and is_sufficient(). | apply_updates() appends |

**is_sufficient() logic (memory.py, lines 68-96):**
- All plan types: requires `age`
- term: also requires `smoker`, `income_range`, and (dependents OR marital_status)
- health: requires (dependents OR marital_status) and `income_range`
- other/savings/ulip/pension/child: requires `income_range`

### CustomerIntelligence (memory.py, lines 174-208)

| Field | Type | Initial | Purpose |
|---|---|---|---|
| interest_level | int | 50 | 0-100. Cumulative sum of interest_delta from META tags. |
| buying_intent | str | "unknown" | cold/warm/hot. Derived by update_intent(): hot if interest>=75 AND close_readiness>=60. |
| engagement_score | int | 50 | 0-100. Not currently updated (stub). |
| close_readiness | int | 0 | 0-100. Cumulative sum of close_readiness_delta from META tags. |
| objections | list[dict] | [] | Each entry: {text, category, turn, resolved}. Categories: price/trust/timing/need/comparison/family. |
| positive_signals | list[str] | [] | Logged buying signals. Updated by agent when signals detected. |
| hesitation_count | int | 0 | Not currently incremented (stub). |
| deflection_count | int | 0 | Not currently incremented (stub). |

**lead_score() formula (memory.py, lines 191-200):**
```
score = interest_level × 0.40
      + close_readiness × 0.30
      + (resolved_objections / total_objections) × 100 × 0.15
      + min(positive_signals × 10, 100) × 0.15
```

### SessionMemory (memory.py, lines 211-348)

| Field | Type | Initial | Purpose |
|---|---|---|---|
| character_id | str | "arjun" | Which character is being used. |
| detected_language | str | "en-IN" | BCP-47 language code. Updated by update_language() on STT or text detection. |
| language_confidence | float | 0.0 | Confidence of last language commit. |
| _language_candidate | str | "" | Candidate language below threshold (not currently used — single-detection commit). |
| stage | str | "INTRODUCE" | Current sales stage. |
| previous_stage | Optional[str] | None | Stage before current. Used by HANDLE/QA return logic. |
| return_to_stage | Optional[str] | None | Set when entering QUESTION_ANSWER. Used for return after QA. |
| turn_in_stage | int | 0 | Turns spent in current stage. Reset to 0 on stage transition. Used by escape hatches. |
| close_substage | str | "SUMMARY" | Current close substage. Only meaningful when stage == "CLOSE". |
| emotional_state | str | "curious" | Customer's emotional state from last META tag. Shown in memory_summary. |
| customer_profile | CustomerProfile | default | Progressive profile collection. |
| explain_subtopic_index | int | 0 | Index into explain_topics list. Advances after each EXPLAIN turn. |
| explain_topics | list[str] | [] | Dynamic topic list. Initialized on first EXPLAIN turn from plan_type + profile. |
| customer_name | Optional[str] | None | Not collected in current flow (no name collection step). |
| primary_need | Optional[str] | None | Not currently populated. |
| family_context | Optional[str] | None | Not currently populated. |
| existing_coverage | Optional[bool] | None | Redundant with CustomerProfile.existing_coverage. |
| questions_asked | list[str] | [] | Customer questions (text with "?"). Last 3 shown in memory_summary. |
| features_explained | list[str] | [] | Not currently populated (stub). |
| intelligence | CustomerIntelligence | default | Live lead scoring. |
| turn_count | int | 0 | Total turns in session. |
| turn_log | list[dict] | [] | Full conversation log. Each entry: {role, text, stage, turn}. |

---

## G. WORKFLOW ANALYSIS

### Stage Machine — Complete Transition Rules

```
Initial state: stage="INTRODUCE", turn_in_stage=0

INTRODUCE
  → PROFILE: LLM requests in META tag (Python allows; also forced after 2 turns by escape hatch)

PROFILE
  → NEED_DEVELOPMENT: Python only, when CustomerProfile.is_sufficient(plan_type) is True
  → PERSONALIZE: LLM requests AND (age is not None AND (smoker is not None OR income_range is not None))
  [EXPLAIN, CLOSE, RECOMMENDATION blocked from PROFILE by apply_analysis gate]

PERSONALIZE
  → NEED_DEVELOPMENT: Python unconditional after any turn

NEED_DEVELOPMENT
  → EXPLAIN: LLM requests (allowed) OR Python forces after 2 turns
  → QUESTION_ANSWER: LLM requests (allowed)
  → HANDLE: LLM requests (allowed)
  [All other targets blocked]

EXPLAIN
  → RECOMMENDATION: Python advances when (last topic + 1 turn) OR (close_readiness >= 50 + 2 turns) OR (6 turns)
  → QUESTION_ANSWER: LLM requests (allowed)
  → HANDLE: LLM requests (allowed)
  [CLOSE blocked from EXPLAIN — redirected to RECOMMENDATION]

RECOMMENDATION
  → CLOSE (PURCHASE_INTENT): Python forces after 1 turn
  → QUESTION_ANSWER: LLM requests (allowed)
  → HANDLE: LLM requests (allowed)

HANDLE
  → previous stage: Python forces after 1 turn (returns to return_to_stage or previous_stage or EXPLAIN)

QUESTION_ANSWER
  → return_to_stage: Python forces after 1 turn

CLOSE (PURCHASE_INTENT)
  → PROCEED: LLM requests in META close_substage (customer said yes)
  → FEEDBACK: LLM requests in META close_substage (customer said no)

CLOSE (PROCEED)
  → CLOSED: Python forces after 1 turn

CLOSE (FEEDBACK)
  → CLOSED: LLM requests OR Python forces after 3 turns

CLOSE (CLOSED)
  → Terminal state
```

---

## H. BUSINESS RULE ANALYSIS

### Cover Multipliers (cover_engine.py, lines 70-75)

```python
if has_dependents and income_lpa < 10:
    multiplier = 20   # high vulnerability: low income + dependents
elif has_dependents:
    multiplier = 15   # dependents but income >= 10 LPA
else:
    multiplier = 10   # no dependents
```

Cover = income_lpa × multiplier + liabilities_lakh - existing_coverage_lakh
Clamped: floor ₹25 lakh (`_COVER_FLOOR_LAKH`), cap ₹10 crore (`_COVER_CAP_LAKH = 1000 lakh`)
Rounded to nearest ₹25 lakh.

### Premium Actuarial Constants (recommendation.py, lines 28-36)

```python
_TERM_BASE_PREMIUM_PER_CRORE = 8500   # ₹/year for 25-yr non-smoker, 30-yr term, ₹1 crore
_TERM_BASE_AGE = 25
_AGE_LOADING_PER_YEAR = 0.035         # 3.5% compound per year above base age
_SMOKER_LOADING = 0.65                # 65% extra for smokers
_COVER_MULTIPLIER_WITH_DEPENDENTS = 15
_COVER_MULTIPLIER_NO_DEPENDENTS = 10
_HEALTH_BASE_PREMIUM = 8000           # ₹/year for ₹5 lakh family floater, age ~35
_HEALTH_BASE_COVER_LAKH = 5
```

Premium formula:
```
age_factor = (1 + 0.035)^max(0, age - 25)
smoker_factor = 1.65 (smoker) or 1.0 (non-smoker)
annual_per_crore = base_per_crore × age_factor × smoker_factor
annual_premium = annual_per_crore × cover_lakh / 100
```

### GST Rate (quote_engine.py, line 82)

```python
_GST_RATE = 0.18  # 18% GST on all insurance premiums
```

### Payment Frequency Factors (quote_engine.py, lines 75-80)

```python
_DEFAULT_FREQ_RULES = {
    "annual":      {"factor": 1.0000, "count": 1},
    "semi_annual": {"factor": 0.5100, "count": 2},
    "quarterly":   {"factor": 0.2600, "count": 4},
    "monthly":     {"factor": 0.0883, "count": 12},
}
```

### is_sufficient() Rules per plan_type (memory.py, lines 68-96)

```
term:    age + smoker + income_range + (dependents OR marital_status)
health:  age + income_range + (dependents OR marital_status)
other:   age + income_range
savings: age + income_range
ulip:    age + income_range
pension: age + income_range
child:   age + income_range
```

### choose_explain_topics() per plan_type (memory.py, lines 14-46)

```
term:    coverage_and_sum_assured, premium_and_daily_cost, death_benefit_and_payout, key_exclusions
         (smoker override: premium_and_daily_cost first)
health:  coverage_and_sum_insured, hospitalisation_and_claims, exclusions_and_waiting_period, tax_benefits
ulip:    coverage_amount, fund_options_and_risk, charges_and_liquidity, tax_benefits
savings: coverage_amount, maturity_benefit_and_corpus, premium_and_payment_term, tax_benefits
pension: corpus_building_and_growth, annuity_payout_options, vesting_age_and_term, tax_benefits
child:   corpus_at_maturity, premium_waiver_on_death, policy_term_and_flexibility, tax_benefits
other:   coverage_amount, key_benefits, premium_structure, exclusions
```

### Language Commit Threshold (memory.py, line 274)

```python
if confidence < 0.7:
    return  # do not commit
```

Single detection at ≥ 0.70 commits immediately. No multi-detection requirement.

### MAX_HISTORY_TURNS (agent.py, line 595)

```python
MAX_HISTORY_TURNS = 6
relevant_log = self.memory.turn_log[-(MAX_HISTORY_TURNS * 2):]
```

Last 12 log entries (6 user + 6 assistant turns) are included as history messages.

### TTS Character Limit (tts.py, lines 149-150)

```python
MAX_TTS_CHARS = 400
# bulbul:v3 rejects inputs over ~500 chars; stay well under that.
```

Truncation at last sentence boundary (`. `, `? `, `! `) within 400 chars. Hard cut to 400 if no sentence boundary found.

### TTS Model and Sample Rate (tts.py, lines 146-147)

```python
TTS_MODEL = "bulbul:v3"
SAMPLE_RATE = 22050
```

### Actuarial Validation Bounds (structure_builder.py, lines 30-31)

```python
_TERM_PREMIUM_MIN = 2000    # ₹/crore/year floor
_TERM_PREMIUM_MAX = 500000  # ₹/crore/year ceiling
```

Age range check: 15-75 years. Monotonicity check: within same term, premiums must increase with age.

### Quote Capability Levels (structure_builder.py, lines 223-255)

```
0 = no data (QuoteError raised)
1 = illustrative (1-2 rows, confidence=inferred)
2 = table-based (3+ rows, exact or scaled)
3 = full (6+ exact rows, multiple terms)
```

---

## I. COMPLETE PROMPT INVENTORY TABLE

| Prompt Name | File | Lines | Purpose | Used By |
|---|---|---|---|---|
| MAIN_SYSTEM_PROMPT | prompts.py | 310-351 | Master system prompt template for all LLM agent calls | agent.py _build_messages() |
| OPENER_PROMPT | prompts.py | 78-115 | UNUSED. Was LLM opener. Superseded by deterministic generate_opener() | Not called |
| VOICE_RULES | prompts.py | 37-47 | Speech formatting and hallucination prohibition | MAIN_SYSTEM_PROMPT {voice_rules} |
| ADVISOR_RULES | prompts.py | 51-64 | Advisor behavioral rules | MAIN_SYSTEM_PROMPT {advisor_rules} |
| DEFLECTION_PLAYBOOK | prompts.py | 68-74 | Objection handling scripts | MAIN_SYSTEM_PROMPT {deflection_playbook} (EXPLAIN/ND/REC/HANDLE only) |
| META_TAG_INSTRUCTION | prompts.py | 283-306 | Structured output tag format and stage transition table | MAIN_SYSTEM_PROMPT {meta_tag_instruction} |
| STAGE_INTENTS["INTRODUCE"] | prompts.py | 121-132 | Introduce stage behavioral instruction | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["PROFILE"] | prompts.py | 133-151 | Profile stage — fields to collect, order, completion trigger | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["PERSONALIZE"] | prompts.py | 152-155 | Vestigial bridge stage | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["NEED_DEVELOPMENT"] | prompts.py | 156-172 | Risk development stage — 4 scenario questions | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["EXPLAIN"] | prompts.py | 173-183 | Topic-by-topic explanation structure | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["RECOMMENDATION"] | prompts.py | 185-201 | Direct personal recommendation structure | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["HANDLE"] | prompts.py | 202-219 | Objection handling sequence | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["CLOSE"] | prompts.py | 220-222 | Delegates to CLOSE_SUBSTAGE_INTENTS | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["QUESTION_ANSWER"] | prompts.py | 223-230 | Document fact answering with profile personalization | MAIN_SYSTEM_PROMPT {stage_intent} |
| CLOSE_SUBSTAGE_INTENTS["SUMMARY"] | prompts.py | 237-247 | Policy summary substage (vestigial — skipped) | MAIN_SYSTEM_PROMPT {stage_intent} when substage=SUMMARY |
| CLOSE_SUBSTAGE_INTENTS["PURCHASE_INTENT"] | prompts.py | 248-253 | Ask one purchase question | MAIN_SYSTEM_PROMPT {stage_intent} when substage=PURCHASE_INTENT |
| CLOSE_SUBSTAGE_INTENTS["PROCEED"] | prompts.py | 254-266 | Handoff message delivery | MAIN_SYSTEM_PROMPT {stage_intent} when substage=PROCEED |
| CLOSE_SUBSTAGE_INTENTS["FEEDBACK"] | prompts.py | 267-273 | Collect decline reason | MAIN_SYSTEM_PROMPT {stage_intent} when substage=FEEDBACK |
| CLOSE_SUBSTAGE_INTENTS["CLOSED"] | prompts.py | 274-278 | Warm closing message | MAIN_SYSTEM_PROMPT {stage_intent} when substage=CLOSED |
| EVALUATION_PROMPT | prompts.py | 355-397 | Post-conversation coaching report | evaluation.py evaluate_session() |
| Ingestion Metadata Prompt | ingestion.py | 49-60 | Extract plan_name, company_name, plan_type, one_line_pitch | ingestion._extract_metadata() |
| Ingestion Brief Prompt | ingestion.py | 281-311 | Rewrite document sections as advisor cheat-sheet | ingestion._generate_brief_via_llm() |
| Structure Builder GPT Prompt | structure_builder.py | 163-190 | Extract illustrative premiums as JSON when no table found | structure_builder._gpt_extract_illustrative_premium() |

---

## J. COMPLETE MODEL INVENTORY TABLE

| Component | Provider | Model | File | Config |
|---|---|---|---|---|
| Main LLM agent | OpenAI | gpt-4o-mini | llm.py (via LLMClient) | max_tokens context-dependent; temperature default |
| Ingestion metadata | OpenAI | gpt-4o-mini | ingestion.py _extract_metadata() | temperature=0.1, max_tokens=200 |
| Ingestion brief | OpenAI | gpt-4o-mini | ingestion.py _generate_brief_via_llm() | temperature=0.3, max_tokens=900 |
| Structure builder GPT fallback | OpenAI | gpt-4o-mini | structure_builder.py _gpt_extract_illustrative_premium() | temperature=0.0, max_tokens=400 |
| Evaluation | OpenAI | gpt-4o-mini | evaluation.py evaluate_session() | via main LLM client |
| STT | Sarvam | saaras:v3 | stt.py | Returns transcript + language_code + language_probability |
| TTS (non-streaming) | Sarvam | bulbul:v3 | tts.py synthesize() | pace=1.1, sample_rate=22050, output_audio_codec=wav |
| TTS (streaming) | Sarvam | bulbul:v3 | tts.py synthesize_stream() | pace=1.3, sample_rate=22050, output_audio_codec=wav |

---

## K. COMPLETE API INVENTORY TABLE

| API | Purpose | File | Endpoint/Method | Used By |
|---|---|---|---|---|
| OpenAI Chat Completions | Main LLM, ingestion, evaluation | llm.py, ingestion.py, structure_builder.py, evaluation.py | POST /v1/chat/completions | AgentSession, ingest(), build_product_structure(), evaluate_session() |
| Sarvam STT | Transcribe audio | stt.py | client.speech_to_text.transcribe() | main.py /transcribe, pipeline.py |
| Sarvam TTS | Synthesize speech | tts.py | client.text_to_speech.convert() / .convert_stream() | main.py /speak, pipeline.py |

FastAPI endpoints exposed:

| Endpoint | Method | Purpose | Auth |
|---|---|---|---|
| /upload | POST | Ingest PDF, create session | None |
| /status/{job_id} | GET | Poll ingestion status | None |
| /chat | POST | LLM turn (SSE streaming or JSON) | None |
| /transcribe | POST | Audio → transcript | None |
| /speak | GET | Text → WAV audio stream | None |
| /evaluate | POST | Post-conversation evaluation | None |
| /transcript/{session_id} | GET | Get full turn log | None |
| /session/{session_id} | DELETE | End and clean up session | None |
| /ws/chat | WebSocket | Voice pipeline (STT + LLM + TTS in one connection) | None |
| /health | GET | Liveness probe | None |

---

## L. CODE TRACEABILITY MAP

### Example 1: "Collect customer age" requirement

**Requirement:** Know the customer's age before progressing to NEED_DEVELOPMENT.

**Trace:**

1. **Prompt:** STAGE_INTENTS["PROFILE"] (prompts.py lines 133-151) instructs LLM to "Ask maximum 2 questions per turn. Natural order: age → family situation → ..."

2. **Prompt:** `{missing_fields_line}` (agent.py lines 487-507) is computed only at PROFILE stage: "STILL NEEDED FROM CUSTOMER: age, smoker status (yes/no), annual income, family situation..." — tells LLM exactly what remains.

3. **LLM call:** LLMClient.complete() in llm.py with the system prompt and 6-turn history.

4. **Pre-LLM tool:** `extract_profile_fields(user_text)` in profile_extractor.py is called in agent.py line 279 BEFORE the LLM call. If the user says "I'm 29 years old", this extracts `{"age": 29}`.

5. **Profile update:** `memory.customer_profile.apply_updates({"age": 29})` in memory.py lines 100-103 sets `self.age = 29` and appends "age" to `fields_collected`.

6. **Stage gate:** After LLM response, `_auto_advance_stage()` in agent.py line 306 calls `memory.customer_profile.is_sufficient(plan_type)`. If age is now collected and the other required fields are present, Python advances stage from PROFILE to NEED_DEVELOPMENT.

7. **Response:** LLM response (which has already asked about age or acknowledged it) is returned to the frontend.

---

### Example 2: "Never hallucinate premiums" requirement

**Requirement:** The agent must never state a specific premium amount it cannot verify from the document or deterministic calculation.

**Trace:**

1. **Ingestion prompt:** `_generate_brief_via_llm()` in ingestion.py lines 301-310 instructs GPT to exclude rupee amounts from the PREMIUMS brief section. The brief never contains "₹22/day".

2. **Brief stripping:** In `agent.py` `_build_messages()` lines 469-476, at INTRODUCE/PROFILE/NEED_DEVELOPMENT stages, the PREMIUMS section is regex-stripped from `brief` before it enters the system prompt.

3. **VOICE_RULES:** prompts.py line 46 — "HALLUCINATION IS FORBIDDEN: ... say exactly 'That specific detail isn't in what I have...'"

4. **smoker=None suppression:** recommendation.py lines 124-133 — if smoker is unknown, `premium_display` is set to `None` and the recommendation block shows "Premium: cannot be estimated without document rate data."

5. **Deterministic quote:** At EXPLAIN/RECOMMENDATION/CLOSE, `generate_quote()` in quote_engine.py computes the premium from structure.json with a full calculation trail. `quote_to_prompt_block()` appends: "IMPORTANT: Present these numbers exactly as shown. Do not recalculate."

6. **Fallback:** If QuoteError is raised (no tables in structure.json), `policy_quote = ""` and the LLM sees only the actuarial estimate with "source: industry benchmark estimate" — prompting it to hedge with "approximately".

---

### Example 3: "Personalise explanation to customer risk" requirement

**Requirement:** Every EXPLAIN response should reference the customer's specific situation, not a generic example.

**Trace:**

1. **Prompt:** `build_risk_narrative(profile)` in agent.py lines 30-115 (called in _build_messages lines 509-516) generates a deterministic paragraph like: "At 29, this is the best possible time to lock in cover... A spouse depends on this income. There is currently no insurance coverage in place... An income of 8 LPA funds the household..."

2. **Prompt injection:** `{risk_narrative}` is injected into MAIN_SYSTEM_PROMPT as "CUSTOMER RISK NARRATIVE (use this to personalise every response)" at NEED_DEVELOPMENT, EXPLAIN, RECOMMENDATION, CLOSE, HANDLE stages.

3. **Stage intent:** STAGE_INTENTS["EXPLAIN"] (prompts.py lines 173-183) instructs: "CONNECT TO THEIR RISK: Start with the customer's specific situation from CUSTOMER RISK NARRATIVE."

4. **ADVISOR_RULES:** prompts.py lines 54-55 — "ALWAYS use the customer's collected profile in every answer. If age=30, say 'at 30' not 'for a typical customer'."

5. **Topic guide:** `{explain_subtopic_line}` tells the LLM exactly which topic to explain this turn, so it doesn't cover all topics at once.

6. **LLM response:** GPT-4o-mini connects the current topic to the customer's specific risk narrative, using calculated numbers from `{recommendation_block}` or `{policy_quote}`.

---

### Example 4: "Handle price objection" requirement

**Requirement:** When a customer says "it's too expensive," the agent should reframe rather than defend or abandon.

**Trace:**

1. **META tag parsing:** LLM appends `[META stage=HANDLE objection=price ...]` to its response. `parse_meta_tag()` in conversation_analyzer.py extracts `objection_category="price"`.

2. **Memory update:** `apply_analysis()` in conversation_analyzer.py lines 177-193 appends `{text, category:"price", turn:N, resolved:False}` to `intelligence.objections`. Stage transitions from EXPLAIN/RECOMMENDATION to HANDLE.

3. **Stage intent:** STAGE_INTENTS["HANDLE"] (prompts.py lines 202-219) instructs: "First — understand what the 'no' actually means... Follow this sequence: ACKNOWLEDGE → EXPLORE → RESPOND → CONTINUE."

4. **Deflection playbook:** DEFLECTION_PLAYBOOK (prompts.py lines 68-74) is active at HANDLE stage: "'Too expensive' → Ask what they expected, then translate to daily cost (annual ÷ 365), mention 80C deduction."

5. **Emotional guide:** `{emotional_guide}` (characters.py Arjun lines 42-53): "Price shock: Do not defend the premium immediately. Ask 'What were you expecting?' Then reframe: translate annual premium to monthly or daily cost, mention 80C tax benefit."

6. **Python escape:** After 1 turn in HANDLE, `_auto_advance_stage()` returns to `return_to_stage` or `previous_stage` — the conversation continues from where it was interrupted.

7. **Objection resolution:** On next successful turn, LLM can emit `[META objection=price close_readiness_delta=+5 ...]` with `objection_resolved=true`. apply_analysis marks the objection as resolved.

---

### Example 5: "Close the sale" requirement

**Requirement:** At the end of the sales flow, the agent should make a direct ask and guide the customer through the purchase process.

**Trace:**

1. **Stage advance:** After RECOMMENDATION turn, `_auto_advance_stage()` sets `stage="CLOSE"` and `close_substage="PURCHASE_INTENT"` (skipping SUMMARY — recommendation IS the summary).

2. **Stage intent:** CLOSE_SUBSTAGE_INTENTS["PURCHASE_INTENT"] (prompts.py lines 248-253): "Ask one clear question: 'Would you like to proceed with purchasing this policy?' Wait for the customer's response. Do not add qualifiers or pressure."

3. **Quote injection:** At CLOSE stage, `policy_quote` is injected if available — the LLM can reference the exact quote during the close.

4. **Customer says yes:** LLM emits `[META stage=CLOSE close_substage=PROCEED ...]`. `_apply_close_substage()` validates PURCHASE_INTENT → PROCEED is an allowed transition and sets `memory.close_substage = "PROCEED"`.

5. **PROCEED intent:** CLOSE_SUBSTAGE_INTENTS["PROCEED"] (prompts.py lines 254-266): Deliver handoff message ONLY. Forbidden from collecting details, inventing steps, generating links.

6. **Auto-advance to CLOSED:** `_auto_advance_close_substage()` in agent.py lines 215-218 sets `close_substage = "CLOSED"` after 1 turn in PROCEED.

7. **Terminal state:** CLOSE_SUBSTAGE_INTENTS["CLOSED"] (prompts.py lines 274-278): Warm closing message. Conversation complete.

---

## M. DEMO PREPARATION REFERENCE TABLE

| Behaviour to demonstrate | File | Function | Key Lines |
|---|---|---|---|
| Opener generated without LLM | agent.py | generate_opener() | 245-263 |
| Language switches to Hindi automatically | memory.py | update_language() | 266-280 |
| Profile fields extracted from speech | profile_extractor.py | extract_profile_fields() | entire file |
| Stage advances from PROFILE to NEED_DEVELOPMENT | agent.py | _auto_advance_stage() | 145-149 |
| Risk narrative personalised to customer | agent.py | build_risk_narrative() | 30-115 |
| Premium hallucination blocked at early stages | agent.py | _build_messages() PREMIUMS strip | 469-476 |
| Deterministic cover recommendation | cover_engine.py | recommend_cover() | 42-103 |
| Premium quote from document tables | quote_engine.py | generate_quote() | 94-197 |
| Price objection handled | conversation_analyzer.py + prompts.py | apply_analysis() + DEFLECTION_PLAYBOOK | 177-193 + 68-74 |
| Stage machine prevents premature CLOSE | conversation_analyzer.py | apply_analysis() gate lines | 120-145 |
| Close substage sequence | conversation_analyzer.py | _apply_close_substage() | 212-236 |
| Post-conversation evaluation | evaluation.py | evaluate_session() | entire file |
| 10MB audio upload limit | main.py | transcribe_audio() | 65, 247 |
| Session isolation with asyncio.Lock | main.py | _session_locks | 49, 117, 195, 223 |
| TTS character limit prevents API error | tts.py | _truncate_for_tts() | 178-186 |
| BM25 document retrieval | rag.py | DocumentStore.get_context() | entire file |
| META tag parsing | conversation_analyzer.py | parse_meta_tag() | 73-107 |
| Interest and close_readiness scoring | memory.py | CustomerIntelligence.update_intent() + lead_score() | 191-208 |
| Language commit threshold | memory.py | update_language() | 273-274 |
