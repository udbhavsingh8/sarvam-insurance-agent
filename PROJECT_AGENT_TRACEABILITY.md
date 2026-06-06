# AGENT DEFINITION, PROMPT ENGINEERING, GUARDRAILS, AND CODE TRACEABILITY

---

## A. AGENT INVENTORY

Every agent-like component in the system:

| Component | File | Type | Description |
|---|---|---|---|
| AgentSession | backend/agent.py | Stateful session object | One per customer session. Owns LLMClient, DocumentStore, SessionMemory, character config. Routes all user turns through the stage machine. |
| _auto_advance_stage | backend/agent.py | Python stage controller | Runs after every LLM turn. Has final say on stage transitions. Prevents LLM from skipping or looping stages. |
| _auto_advance_close_substage | backend/agent.py | Python close controller | Controls PURCHASE_INTENT→PROCEED/FEEDBACK→CLOSED flow. PROCEED threshold >= 2 prevents same-turn skip. |
| _guard_discovery_numbers | backend/agent.py | Python safety filter | Hard post-processor: replaces any ₹ amount in DISCOVERY response with a redirect to the next missing field. |
| ConversationAnalyzer | backend/conversation_analyzer.py | META tag parser + memory updater | Parses `[META ...]` tag from LLM response. Applies signals to SessionMemory. |
| apply_analysis | backend/conversation_analyzer.py | Analysis applier | Applies TurnAnalysis to memory: stage transition gates, position_skip, VARIANTS→CLOSE shortcut, interest/readiness updates, objection tracking. |
| build_gap_calculation | backend/gap_engine.py | Deterministic gap calculator | Called at GAP_CALC stage. Returns gap dict with spoken walkthrough. Returns None if income unknown. |
| gap_to_prompt_block | backend/gap_engine.py | Prompt block builder | Formats gap dict for injection into system prompt at GAP_CALC. |
| build_recommendation_block | backend/recommendation.py | Deterministic cover + premium estimator | Called at RECOMMEND/VARIANTS/EXPLAIN/CLOSE. Returns compact text block with cover recommendation and premium estimate (actuarial benchmarks). |
| recommend_cover | backend/cover_engine.py | Cover amount calculator | Deterministic income-multiplier-based cover calculation. Called before CLOSE for quote_engine input. |
| generate_quote | backend/quote_engine.py | Premium lookup and interpolation | Finds best matching premium rows in structure.json, interpolates, applies GST and frequency loading. Returns Quote object. |
| ingest | backend/ingestion.py | Document pipeline | Extracts text, generates metadata + brief + structure.json + chunks.json. One-time per PDF. Skip-if-exists. |
| build_product_structure | backend/structure_builder.py | Structure extractor | Deterministic table extraction + GPT fallback + actuarial validation. Outputs structure.json. |
| evaluate_session | backend/evaluation.py | Post-conversation evaluator | Runs EVALUATION_PROMPT against full transcript. Returns coaching report. |
| extract_profile_fields | backend/profile_extractor.py | Profile field extractor | Deterministic regex-based extraction of 12 fields from user text. Called before LLM on every turn. |
| DocumentStore | backend/rag.py | Retrieval + document state | Holds sales_brief, metadata, structure.json, BM25 index. Provides get_context() for document retrieval. |
| LLMClient | backend/llm.py | OpenAI API wrapper | complete() and stream() methods. Accepts stage parameter for temperature scoping. Wraps gpt-4o-mini calls. |

---

## B. SYSTEM PROMPT INVENTORY

### B.1 MAIN_SYSTEM_PROMPT (prompts.py)

The master template assembled by `_build_messages()` in agent.py. Injected as the `system` message in every LLM call.

**Template placeholders explained:**

| Placeholder | Source | Stage availability | Purpose |
|---|---|---|---|
| `{name}` | characters.py `character["name"]` | All | Advisor's first name ("Arjun") |
| `{persona}` | characters.py `character["persona"]` | All | 5-sentence character backstory |
| `{style_guide}` | characters.py `character["style_guide"]` | All | Communication style rules |
| `{emotional_guide}` | characters.py `character["emotional_guide"]` | All | Objection handling emotional scripts |
| `{sales_brief}` | DocumentStore.sales_brief (truncated to 3500 chars) | All (PREMIUMS stripped at GREET/DISCOVERY) | Product knowledge from ingestion |
| `{document_context}` | DocumentStore.get_context() top-3 BM25 chunks (1500 chars) | All | Raw document passages for specific fact questions |
| `{language_name}` | memory.detected_language via language_display_name() | All | Current detected language display name |
| `{customer_profile}` | CustomerProfile.summary() | All | Collected profile fields as bullet list |
| `{missing_fields_line}` | Computed from CustomerProfile at DISCOVERY stage only; income-gated priority | DISCOVERY only | Age-first, then income-first, then remaining fields |
| `{risk_narrative}` | build_risk_narrative() — deterministic Python | RECOMMEND, VARIANTS, EXPLAIN, CLOSE, OBJECTIONS | "CUSTOMER RISK NARRATIVE" — personalised vulnerability story |
| `{memory_summary}` | SessionMemory.memory_summary() | All | Compact context: questions asked, features explained, active objection, lead score, gap_lakh |
| `{recommendation_block}` | build_recommendation_block() + gap reminder or "" | RECOMMEND, VARIANTS, EXPLAIN, CLOSE | "CALCULATED NUMBERS FOR THIS CUSTOMER" actuarial estimates + gap reminder |
| `{policy_quote}` | quote_to_prompt_block() or "" | CLOSE (when structure.json has tables) | "QUOTE FOR THIS CUSTOMER" deterministic premium with full calculation trail |
| `{stage}` | memory.stage | All | Current stage name |
| `{explain_subtopic_line}` | Computed from memory.explain_topics and explain_subtopic_index | EXPLAIN only | "EXPLAIN TOPIC NOW: Coverage And Sum Assured (topic 1 of 4 | Next: ...)" |
| `{close_substage_line}` | memory.close_substage | CLOSE only | "CLOSE SUBSTAGE: PURCHASE_INTENT" |
| `{stage_intent}` | STAGE_INTENTS[stage] or CLOSE_SUBSTAGE_INTENTS[substage] | All | Per-stage behavioral instruction |
| `{voice_rules}` | VOICE_RULES constant | All | Formatting and speech style rules |
| `{advisor_rules}` | ADVISOR_RULES constant | All | Behavioral rules for advisor |
| `{deflection_playbook}` | DEFLECTION_PLAYBOOK or "" | VARIANTS, EXPLAIN, RECOMMEND, OBJECTIONS, CLOSE | Objection response scripts |
| `{meta_tag_instruction}` | META_TAG_INSTRUCTION constant | All | Instructions for appending [META ...] tag including position_skip field |
| Final line | Hardcoded in template | All | ⚠️ LANGUAGE THIS TURN: reply must be in {language_name} |

---

### B.2 OPENER_PROMPT (prompts.py)

**Status: UNUSED.** The OPENER_PROMPT was the original LLM-generated opener. It is now superseded by the deterministic `generate_opener()` method in agent.py. The prompt remains in prompts.py as documentation.

Placeholders: `{name}`, `{persona}`, `{style_guide}`, `{language_name}`, `{plan_name}`, `{company_name}`, `{one_line_pitch}`

Why removed: The LLM would produce `[Name]` placeholders, invent customer details, and produce English openers for Hindi sessions.

---

### B.3 STAGE_INTENTS dict (prompts.py)

One entry per stage. Each is injected as `{stage_intent}` in the system prompt.

**Active stages (current consultative model):**

| Stage | Purpose |
|---|---|
| GREET | Acknowledge opener response and bridge to DISCOVERY. DO NOT re-introduce. Single-turn only. Set stage=DISCOVERY. |
| DISCOVERY | Collect 4 gating fields in order: age first → income second (income-gated) → then loans/existing cover/years. Max 2 questions/turn. No product mentions. Python gates advance. |
| GAP_CALC | Walk through deterministic gap from GAP CALCULATION block conversationally. State income × years, add loans, subtract existing. State gap. End with "Does that number surprise you?" Set stage=POSITION. |
| POSITION | Car insurance analogy reframe. Skip if customer already knows term insurance (set position_skip=true, stage=RECOMMEND). Otherwise set stage=RECOMMEND after one exchange. |
| RECOMMEND | Name specific plan (Click2Protect Life from HDFC). 3-4 sentences. One reason for this customer. Set stage=VARIANTS (term) or EXPLAIN (savings). |
| VARIANTS | Recommend one variant (default: Life Option). Ask ADB rider question. Ask CI Rebalance only if family history. ROP only if customer asks "what if I survive?". Assumptive close: "Shall we go with X for Y cover?" On agreement: "Perfect, let's get that set up for you." Set stage=CLOSE close_substage=PROCEED. |
| EXPLAIN | SAVINGS/NON-TERM only. One topic per turn from EXPLAIN TOPIC NOW. Connect to customer situation. Use CALCULATED NUMBERS. Set stage=CLOSE after final topic. |
| OBJECTIONS | Acknowledge → Explore root concern → Respond with one fact/reframe → Return to previous stage. Never accept "no" passively. |
| QUESTION_ANSWER | Answer using actual profile. Use only document facts. Bridge back: "Coming back to what I was telling you..." |
| CLOSE | Follow the CLOSE SUBSTAGE instruction exactly. Each substage has one job. |

**Legacy stage stubs (kept for backward compatibility, never reached by current stage machine):**

| Stage | Status |
|---|---|
| INTRODUCE | Kept as backward compatibility alias for GREET behavior |
| PROFILE | Kept for old sessions |
| PERSONALIZE | Vestigial one-turn bridge |
| NEED_DEVELOPMENT | Merged into DISCOVERY in new design |
| RECOMMENDATION | Superseded by RECOMMEND |
| HANDLE | Superseded by OBJECTIONS |

---

### B.4 CLOSE_SUBSTAGE_INTENTS dict (prompts.py)

| Substage | Purpose | Auto-advance condition |
|---|---|---|
| PURCHASE_INTENT | Assumptive close. "Based on your gap of X, would you prefer Y or Z cover?" or "Would you prefer annual or monthly?" Commitment questions, not permission. On yes → PROCEED. On reluctance → try once more → FEEDBACK. | Python forces to PROCEED after 2 turns |
| PROCEED | Deliver EXACTLY: "Thank you. I'll have the onboarding link sent to you on SMS and email. The rest of the process is handled online — it takes just a few minutes. Our support team is available if you need any help along the way." STOP. Do NOT collect PII or describe application. Set close_substage=CLOSED. | Python forces to CLOSED after 2 turns (threshold >= 2) |
| FEEDBACK | "That is completely fine." Then: "Before we close, is there anything about the plan that did not feel right, or something I could have explained better?" Listen. Reflect. Do not re-sell. Set close_substage=CLOSED. | Python forces to CLOSED after 2 turns |
| CLOSED | EXACTLY: "Thank you for your time. If you have any questions later, our support team is always there. Have a great day." No product questions. No further discussion. Terminal. | Terminal state — QUESTION_ANSWER interrupts blocked |

Note: SUMMARY substage still defined in dict but never reached — close_substage initialises to PURCHASE_INTENT.

---

### B.5 META_TAG_INSTRUCTION (prompts.py)

Full text instructs the LLM to append a structured tag to every response:
```
[META stage=STAGE interest_delta=N objection=TYPE emotional_state=STATE close_readiness_delta=N close_substage=SUBSTAGE position_skip=false]
```

Field meanings:
- `stage`: Where THIS response should move the conversation. Python validates and may block.
- `interest_delta`: -10 to +10. Added to `intelligence.interest_level` (0-100).
- `close_readiness_delta`: -10 to +10. Added to `intelligence.close_readiness` (0-100).
- `objection`: price|trust|timing|need|comparison|family|none. Logged to `intelligence.objections`.
- `emotional_state`: curious|engaged|hesitant|resistant|anxious|satisfied. Sets `memory.emotional_state`.
- `close_substage`: Only when stage=CLOSE. PURCHASE_INTENT|PROCEED|FEEDBACK|CLOSED.
- `position_skip`: Set to true ONLY when skipping POSITION because customer already understands term insurance.

Stage transition rules permitted in META (from META_TAG_INSTRUCTION):
```
GREET       → DISCOVERY          (after bridging to discovery)
GAP_CALC    → POSITION           (after walking through gap calculation)
POSITION    → RECOMMEND          (after reframe; or set position_skip=true to skip)
RECOMMEND   → VARIANTS           (term plans) or EXPLAIN (savings plans)
VARIANTS    → CLOSE              (variant chosen, assumptive close made)
EXPLAIN     → CLOSE              (all topics covered, savings plans)
any         → QUESTION_ANSWER    (customer asks a specific factual question)
any         → OBJECTIONS         (customer raises a concern or hesitation)

DO NOT signal a transition out of DISCOVERY — Python controls that gate.
DO NOT signal CLOSE from anywhere except VARIANTS or EXPLAIN.
```

---

### B.6 VOICE_RULES (prompts.py)

All rules:
1. 2-3 sentences max. No lists, bullets, headers, or markdown. **This limit is MANDATORY in ALL languages — Hindi responses must be exactly as short as English ones.**
2. No filler openers: "Certainly!", "Absolutely!", "Great question!", "यह जानकर अच्छा लगा", "धन्यवाद"
3. Never say "death" — say "if something were to happen to you"
4. Never end a sentence with a colon — always complete the thought
5. NEVER repeat back what the customer just said verbatim. Acknowledge in one natural phrase, then move forward.
6. NEVER compute or mention rupee amounts, cover ranges, or premiums in GREET or DISCOVERY stages. Rule is absolute.
7. NEVER mention application forms, KYC, document submission, or application process.
8. NEVER say "please hold on", "please wait", "let me check" — responses are immediate.
9. NEVER do a summary recap of what the customer told you.
10. HALLUCINATION IS FORBIDDEN: if a fact or figure is not in PRODUCT KNOWLEDGE or the GAP CALCULATION block, say exactly: "That specific detail isn't in what I have — I'd recommend checking with the insurer directly."

**RULE 0 — GROUNDEDNESS** (prepended to MAIN_SYSTEM_PROMPT):
Every rupee amount, cover figure, loan number, or premium you speak must exist verbatim in PRODUCT KNOWLEDGE, CALCULATED NUMBERS, or the GAP CALCULATION block below. If you cannot point to the exact source, do not say the number.

---

### B.7 ADVISOR_RULES (prompts.py)

All rules:
1. Can ask 2-3 related questions together naturally. Never explain WHY.
2. Reflect briefly on what the customer said before moving forward.
3. ALWAYS use customer's collected profile in every answer. If age=30, say "at 30" not "for a typical customer".
4. NEVER re-ask for information already in CUSTOMER PROFILE.
5. NEVER assume customer details not in CUSTOMER PROFILE.
6. If customer asks a question: answer using document facts, then return to stage.
7. Numbers must come from the document or CALCULATED NUMBERS/GAP CALCULATION block only.
8. If detail not in document: say exactly "That specific detail isn't in what I have..."
9. No pressure, no urgency. Frame protection positively.
10. Watch for buying signals. When signals appear, shift to recommending and closing.
11. DIRECT RECOMMENDATION RULE: If customer says "you tell me" / "aap bataao" / "recommend karo" at RECOMMEND, VARIANTS, or CLOSE → give ONE direct recommendation immediately. At DISCOVERY/GAP_CALC/POSITION → collect next missing field instead.
12. CRITICAL: Never confuse years_of_support with age in "at X" framing (age guard).

---

### B.8 DEFLECTION_PLAYBOOK (prompts.py)

Active only at VARIANTS, EXPLAIN, RECOMMEND, OBJECTIONS, CLOSE stages.

Objection responses:
- "Too expensive" → Translate to daily cost (annual ÷ 365), mention 80C deduction. "For ₹X a day, your family has ₹Y crore protection."
- "I get nothing if I survive" / "kuch nahi milega" / "premium waste ho jayega":
  - Step 1: Car insurance reframe ("If your car doesn't get stolen, do you call the insurance a waste?")
  - Step 2 (if reframe doesn't land): Mention ROP — costs 2.5x more, I'd take standard and invest the difference. "But if the psychology matters to you, the option exists."
  - **Do NOT mention ROP unless this specific objection is explicitly raised.**
- "Already have a policy" → "Do you know exactly what it covers if you were ill for 3 months and couldn't work?"
- "Claims don't get paid" → Cite document claim settlement facts only. Never invent statistics.
- "Spouse/father decides" → "That makes sense. What would help you explain this to them?"

---

### B.9 EVALUATION_PROMPT (prompts.py)

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

### B.10 Ingestion Brief Prompt (ingestion.py)

Located in `_generate_brief_via_llm()`. Sends document sections to GPT-4o-mini.

Critical instruction:
```
PREMIUMS: describe the premium payment structure only — frequency options, any loading factors,
and minimum premium if stated. Do NOT include illustrative rupee amounts, per-day costs,
sample calculations, or "starting from" figures.
```

Output section labels: COVERAGE | PREMIUMS | ELIGIBILITY | DEATH BENEFIT | MATURITY BENEFIT | RIDERS | TAX BENEFITS | EXCLUSIONS | PITCH

Max output: 1800 characters (enforced by prompt instruction).

---

### B.11 Ingestion Metadata Prompt (ingestion.py)

Located in `_extract_metadata()`. First 1500 chars of document → 4 fields.

```
plan_name: <exact plan name>
company_name: <insurance company or bank name>
plan_type: <one of: term, health, savings, ulip, pension, child, other>
one_line_pitch: <one spoken sentence, max 18 words>
```

Temperature 0.1. Falls back to `_extract_metadata_from_text()` on any failure.

---

### B.12 Structure Builder GPT Fallback Prompt (structure_builder.py)

Located in `_gpt_extract_illustrative_premium()`. Used when deterministic table parser finds no premium tables.

Sends premium-related text lines to GPT-4o-mini. Returns JSON array:
```json
[{"age": 30, "term": 20, "annual_premium": 8500}, ...]
```

Temperature 0.0. Maximum 400 tokens. Validates each entry: age 15-75, term 5-55, premium 1000-1,000,000.

---

## C. PERSONA ENGINEERING ANALYSIS

### Arjun (characters.py)

**persona:**
> "a high-performing insurance advisor in his early 30s with twenty years of field experience. He is energetic, confident, and genuinely consultative — he listens carefully, then connects the product directly to the customer's situation. He moves conversations forward with purpose. He is warm and engaging without being pushy. His goal is always to help the customer make the right decision — and he is skilled at recognising when a customer is ready to move forward."

Note: "twenty years" + "early 30s" is a deliberate creative exaggeration for persona. The field experience figure was updated from "eight years" to convey a more authoritative advisor.

**style_guide:**
Confident, energetic, direct — top-performing advisor on a live call. Always personalise with actual age, income, family. Translate numbers into real life. Keep responses tight. Never explain why you're asking. Never start a sentence ending with a colon. When unknown detail: say so, never guess. Never use: 'Absolutely!', 'Certainly!', 'Great question!', 'As per the policy'. Never say "death".

**emotional_guide:**
Price shock: Don't defend immediately — ask "What were you expecting?" then reframe to daily cost + 80C.
Hesitation: "What's the one thing you'd want to be sure about before deciding?"
"My spouse decides": "Makes sense — what would help you explain this to them?"
"I already have cover": "Do you know what it covers if something serious happened?"
Claims distrust: Use document facts. If unavailable, say so honestly.
Anxious: Slow down, give a specific number or fact to hold.
Rude/dismissive: Stay calm.
Never guilt-trip. Never create urgency. Never pressure.

**voice:** "dev" (Sarvam bulbul:v3 speaker)

### Lalita (characters.py) — defined but inactive in UI

**persona:** Female advisor, early 40s, twelve years experience. Patient, empathetic, thorough. "A quiet closer: she earns the sale through trust, not pressure."

**voice:** "ritu" (Sarvam bulbul:v3 speaker)

**Note:** The `opener` field on both characters is `""` — generate_opener() builds the opener dynamically from document metadata. The opener field is vestigial.

---

## D. GUARDRAILS ANALYSIS

### D.1 Premium Hallucination — Structural

**Layer 1 — Brief generation (ingestion.py):**
The ingestion prompt explicitly forbids rupee amounts in the PREMIUMS brief section. The brief never contains "₹22/day" or "starting from ₹8,060/year".

**Layer 2 — Brief stripping at early stages (agent.py, _build_messages):**
```python
if self.memory.stage in ("GREET", "DISCOVERY", "INTRODUCE", "PROFILE", "NEED_DEVELOPMENT"):
    brief = re.sub(r'PREMIUMS:.*?(?=\n[A-Z ]+:|$)', '', brief, flags=re.DOTALL | re.IGNORECASE).strip()
```
Even if the brief contains premium text, it is stripped before the system prompt is built.

**Layer 3 — RULE 0 GROUNDEDNESS (prompts.py, MAIN_SYSTEM_PROMPT preamble):**
"Every rupee amount, cover figure, loan number, or premium you speak must exist verbatim in PRODUCT KNOWLEDGE, CALCULATED NUMBERS, or the GAP CALCULATION block below. If you cannot point to the exact source, do not say the number."

**Layer 4 — VOICE_RULES hallucination prohibition (prompts.py):**
"HALLUCINATION IS FORBIDDEN: if a fact, figure, or process step is not in the product document or the CALCULATED NUMBERS/GAP CALCULATION block, say exactly: 'That specific detail isn't in what I have — I'd recommend checking with the insurer directly.'"

**Layer 5 — ADVISOR_RULES (prompts.py):**
"Numbers must come from the document or the CALCULATED NUMBERS/GAP CALCULATION block only. Never invent or approximate."

**Layer 6 — smoker=None premium suppression (recommendation.py):**
The recommendation block explicitly returns `premium_display: None` if smoker status is unknown, preventing the recommendation block from showing a premium figure.

**Layer 7 — Python rupee guard at DISCOVERY (_guard_discovery_numbers in agent.py):**
```python
_RUPEE_RE = re.compile(
    r'(?:₹\s*\d|'
    r'\d+\s*(?:lakh|crore|cr\b|l\b)|'
    r'(?:lakh|crore)\s*\d)',
    re.IGNORECASE,
)
```
After LLM response at DISCOVERY stage, if any ₹ amount is found, the entire response is replaced with a redirect: "Before I get to the numbers — can I ask your age quickly?" or "I'll get to the numbers in a moment — I just need your annual income first."

---

### D.2 Stage Transition Gates (conversation_analyzer.py, apply_analysis)

| Gate | Location | Rule |
|---|---|---|
| DISCOVERY → next: LLM cannot signal | apply_analysis lines 150-155 | If current == DISCOVERY and LLM requests any non-interrupt stage: block it, increment turn_in_stage only. Python-only gate via discovery_sufficient(). |
| VARIANTS → CLOSE: sets PROCEED directly | apply_analysis lines 169-172 | When current=VARIANTS and requested=CLOSE: memory.close_substage = "PROCEED" (skips PURCHASE_INTENT). |
| Interrupt stages blocked from CLOSED | apply_analysis lines 142-149 | QUESTION_ANSWER and OBJECTIONS not allowed when stage=CLOSE and close_substage=CLOSED. |
| POSITION skip | apply_analysis lines 156-161 | If current=POSITION and analysis.position_skip=True and requested=RECOMMEND: set memory.position_skipped=True and allow. |
| LLM-allowed transitions enforced | apply_analysis lines 163-176 | Only transitions in _LLM_ALLOWED_TRANSITIONS[current] are allowed from LLM signals. |

**_LLM_ALLOWED_TRANSITIONS:**
```python
{
    "GREET":            {"DISCOVERY", "QUESTION_ANSWER"},
    "DISCOVERY":        {"QUESTION_ANSWER", "OBJECTIONS"},   # Python gates → GAP_CALC or RECOMMEND
    "GAP_CALC":         {"POSITION", "QUESTION_ANSWER", "OBJECTIONS"},
    "POSITION":         {"RECOMMEND", "QUESTION_ANSWER", "OBJECTIONS"},
    "RECOMMEND":        {"VARIANTS", "EXPLAIN", "QUESTION_ANSWER", "OBJECTIONS"},
    "VARIANTS":         {"CLOSE", "QUESTION_ANSWER", "OBJECTIONS"},
    "EXPLAIN":          {"CLOSE", "QUESTION_ANSWER", "OBJECTIONS"},
    "OBJECTIONS":       set(),    # Python always returns after 1 turn
    "QUESTION_ANSWER":  set(),    # Python always returns after 1 turn
    "CLOSE":            {"CLOSE", "QUESTION_ANSWER"},
}
```

---

### D.3 Python Escape Hatches (_auto_advance_stage)

| Stage | Escape condition | Action |
|---|---|---|
| GREET | turn_in_stage >= 1 | Force advance to DISCOVERY (single-turn bridge) |
| DISCOVERY | discovery_sufficient(plan_type) == True | Advance to GAP_CALC (term) or RECOMMEND (savings) |
| DISCOVERY | turn_in_stage >= 8 | Force advance regardless (8-turn fallback escape) |
| GAP_CALC | turn_in_stage >= 1 | Force advance to POSITION |
| POSITION | turn_in_stage >= 1 | Force advance to RECOMMEND |
| RECOMMEND | turn_in_stage >= 1 | Force advance to VARIANTS (term) or EXPLAIN (savings) |
| VARIANTS | turn_in_stage >= 6 | Force to CLOSE (PURCHASE_INTENT) — hard 6-turn escape |
| EXPLAIN | (last topic + 1 turn) OR (6 turns) | Force advance to CLOSE |
| QUESTION_ANSWER / OBJECTIONS | turn_in_stage >= 1 | Return to return_to_stage or previous_stage |
| CLOSE/PURCHASE_INTENT | turn_in_stage >= 2 | Force to PROCEED |
| CLOSE/PROCEED | turn_in_stage >= 2 | Force to CLOSED |
| CLOSE/FEEDBACK | turn_in_stage >= 2 | Force to CLOSED |

---

### D.4 Forbidden Behaviors in CLOSE/PROCEED (prompts.py)

At PROCEED substage, the LLM is explicitly prohibited from:
- Collecting any personal details (name, address, contact, health, nominee, income)
- Asking the customer to fill a form "here" or "online"
- Inventing or describing application steps
- Generating payment links, URLs, or policy numbers
- Asking any further questions

The only permitted output is the exact handoff message: "Thank you. I'll have the onboarding link sent to you on SMS and email. The rest of the process is handled online — it takes just a few minutes. Our support team is available if you need any help along the way."

---

### D.5 CLOSE Substage Ordering (_apply_close_substage, conversation_analyzer.py)

The `allowed_next` dict prevents substage skipping:
```
PURCHASE_INTENT → {PROCEED, FEEDBACK}
PROCEED         → {CLOSED}
FEEDBACK        → {CLOSED}
CLOSED          → {} (terminal, no transitions)
```

Note: SUMMARY → PURCHASE_INTENT was in the old design but SUMMARY is no longer reachable (close_substage initialises to PURCHASE_INTENT). The VARIANTS→CLOSE path sets close_substage=PROCEED directly, also bypassing PURCHASE_INTENT.

---

### D.6 Audio Size Limit (main.py)

```python
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB
```

Enforced at the `/transcribe` endpoint. Requests exceeding 10MB return HTTP 413.

---

### D.7 Language Commit Threshold (memory.py)

```python
if not language_code or confidence < 0.7:
    return
```

Language commits only when Sarvam STT returns `language_probability >= 0.70`. Below this threshold, the current language is preserved.

---

### D.8 Discovery Number Guard (agent.py)

Applied after every LLM response when stage == DISCOVERY:

```python
_RUPEE_RE = re.compile(
    r'(?:₹\s*\d|'
    r'\d+\s*(?:lakh|crore|cr\b|l\b)|'
    r'(?:lakh|crore)\s*\d)',
    re.IGNORECASE,
)

def _guard_discovery_numbers(text: str, profile: object) -> str:
    if not _RUPEE_RE.search(text):
        return text
    age_known = getattr(profile, "age", None) is not None
    income_known = getattr(profile, "income_range", None) is not None
    if not age_known:
        return "Before I get to the numbers — can I ask your age quickly? ..."
    if not income_known:
        return "I'll get to the numbers in a moment — I just need your annual income first. ..."
    return text  # both known; user mentioned a loan amount — acceptable
```

If the LLM produces a ₹ amount during DISCOVERY, this function replaces the entire response with the appropriate redirect. The only exception: when both age and income are already known, a loan amount echoed from the customer's own statement is allowed through.

---

## E. TOOL CALLING ANALYSIS

There are no OpenAI function/tool calls in this system. All "tools" are deterministic Python functions called directly by the agent code before or after the LLM call.

| "Tool" | Type | Location | Called when |
|---|---|---|---|
| extract_profile_fields | Pre-LLM Python | profile_extractor.py, called in agent.py | Every turn, before LLM call |
| build_gap_calculation | Pre-LLM Python | gap_engine.py, called in agent.py _build_messages | GAP_CALC stage; result stored in memory.intelligence.gap_lakh |
| gap_to_prompt_block | Pre-LLM Python | gap_engine.py, called in agent.py _build_messages | GAP_CALC stage, after build_gap_calculation succeeds |
| build_recommendation_block | Pre-LLM Python | recommendation.py, called in agent.py _build_messages | RECOMMEND/VARIANTS/EXPLAIN/CLOSE stages |
| recommend_cover | Pre-LLM Python | cover_engine.py, called in agent.py | CLOSE when structure exists |
| generate_quote | Pre-LLM Python | quote_engine.py, called in agent.py | CLOSE when structure exists |
| build_risk_narrative | Pre-LLM Python | agent.py, called in agent.py _build_messages | RECOMMEND/VARIANTS/EXPLAIN/CLOSE/OBJECTIONS stages |
| choose_explain_topics | Pre-LLM Python | memory.py, called in agent.py | First turn of EXPLAIN (lazy init) |
| _guard_discovery_numbers | Post-LLM Python | agent.py, called after LLM response | DISCOVERY stage only |
| parse_meta_tag | Post-LLM Python | conversation_analyzer.py, called in agent.py | After every LLM response |
| apply_analysis | Post-LLM Python | conversation_analyzer.py, called in agent.py | After every LLM response with valid META tag |
| _auto_advance_stage | Post-LLM Python | agent.py, called after every turn | After every turn |

---

## F. MEMORY ANALYSIS

### CustomerProfile (memory.py)

| Field | Type | Purpose | How populated |
|---|---|---|---|
| age | Optional[int] | Customer's age. Drives premium calculation and cover multiplier. | profile_extractor regex on user text |
| gender | Optional[str] | male/female/other. Informational only. | profile_extractor |
| marital_status | Optional[str] | single/married/divorced/widowed. Used in risk narrative. | profile_extractor |
| dependents | Optional[int] | Number of dependents. Drives cover multiplier (10x → 15x → 20x). | profile_extractor |
| smoker | Optional[bool] | Smoker status. Applied as 65% loading in recommendation.py. If None, premium suppressed. | profile_extractor |
| existing_coverage | Optional[str] | none/some/adequate. Categorical. Used in risk narrative. | profile_extractor |
| existing_cover_lakh | Optional[float] | Numeric existing life cover. **Gates discovery_sufficient.** 0.0 = "no insurance" explicitly stated. None = not asked yet. | profile_extractor _extract_existing_cover() |
| financial_goal | Optional[str] | protection/savings/both/retirement/child. Not used in current business logic. | profile_extractor |
| income_range | Optional[str] | Free-text income string. Parsed to LPA by gap_engine._parse_income_lpa(). Drives gap calculation. **Gates discovery_sufficient.** | profile_extractor |
| health_conditions | Optional[str] | none/pre-existing. Informational for health plans. | profile_extractor |
| years_of_support | Optional[int] | Years of income replacement needed. Input to gap_engine. **Gates discovery_sufficient.** None = not asked yet. | profile_extractor _extract_years_of_support() |
| chosen_variant | Optional[str] | Plan variant selected at VARIANTS stage (e.g., "life_protect", "ci_rebalance"). | profile_extractor |
| policy_term | Optional[int] | Requested term in years. Used by quote_engine. | profile_extractor |
| payment_frequency | Optional[str] | annual/semi_annual/quarterly/monthly. Used by quote_engine. | profile_extractor |
| liabilities_lakh | Optional[float] | Outstanding loans in lakh. Input to gap_engine. | profile_extractor |
| cover_amount_override_lakh | Optional[float] | Customer-stated explicit cover amount. Overrides all cover calculations. | profile_extractor |
| fields_collected | list[str] | List of field names collected so far. | apply_updates() appends |

**discovery_sufficient() logic (memory.py):**
```python
def discovery_sufficient(self, plan_type: str = "other") -> bool:
    return (
        self.age is not None
        and self.income_range is not None
        and self.existing_cover_lakh is not None   # 0.0 = "no insurance"; None = not asked
        and self.years_of_support is not None
    )
```

All plan types use the same 4 hard gates. Family context (dependents/marital) is NOT gated — too brittle to extract reliably from natural conversation. The 8-turn fallback in _auto_advance_stage advances regardless if extraction keeps failing.

### CustomerIntelligence (memory.py)

| Field | Type | Initial | Purpose |
|---|---|---|---|
| interest_level | int | 50 | 0-100. Cumulative sum of interest_delta from META tags. |
| buying_intent | str | "unknown" | cold/warm/hot. Derived by update_intent(): hot if interest>=75 AND close_readiness>=60. |
| engagement_score | int | 50 | 0-100. Not currently updated (stub). |
| close_readiness | int | 0 | 0-100. Cumulative sum of close_readiness_delta from META tags. |
| gap_lakh | Optional[float] | None | Computed protection gap in lakh. Set by gap_engine at GAP_CALC. Used in later stages as reminder. |
| objections | list[dict] | [] | Each entry: {text, category, turn, resolved}. Categories: price/trust/timing/need/comparison/family. |
| positive_signals | list[str] | [] | Logged buying signals. Not currently auto-populated. |
| hesitation_count | int | 0 | Stub — not currently incremented. |
| deflection_count | int | 0 | Stub — not currently incremented. |

**lead_score() formula (memory.py):**
```
score = interest_level × 0.40
      + close_readiness × 0.30
      + (resolved_objections / total_objections) × 100 × 0.15
      + min(positive_signals × 10, 100) × 0.15
```

### SessionMemory (memory.py)

| Field | Type | Initial | Purpose |
|---|---|---|---|
| character_id | str | "arjun" | Which character is being used. |
| detected_language | str | "en-IN" | BCP-47 language code. |
| language_confidence | float | 0.0 | Confidence of last language commit. |
| stage | str | "GREET" | Current sales stage. (Was "INTRODUCE" in old design.) |
| previous_stage | Optional[str] | None | Stage before current. Used by QUESTION_ANSWER/OBJECTIONS return logic. |
| return_to_stage | Optional[str] | None | Set when entering QUESTION_ANSWER/OBJECTIONS. Used for return. |
| turn_in_stage | int | 0 | Turns spent in current stage. Reset to 0 on stage transition. Used by escape hatches. |
| close_substage | str | "PURCHASE_INTENT" | Current close substage. Only meaningful when stage == "CLOSE". (Was "SUMMARY" in old design.) |
| emotional_state | str | "curious" | Customer's emotional state from last META tag. |
| customer_profile | CustomerProfile | default | Progressive profile collection (15 fields). |
| explain_subtopic_index | int | 0 | Index into explain_topics list. Advances after each EXPLAIN turn. |
| explain_topics | list[str] | [] | Dynamic topic list. Initialized on first EXPLAIN turn from plan_type + profile. |
| customer_name | Optional[str] | None | Not collected in current flow. |
| position_skipped | bool | False | True if POSITION stage was bypassed via position_skip=true. |
| questions_asked | list[str] | [] | Customer questions (text with "?"). Last 3 shown in memory_summary. |
| features_explained | list[str] | [] | Stub — not currently populated. |
| intelligence | CustomerIntelligence | default | Live lead scoring. |
| turn_count | int | 0 | Total turns in session. |
| turn_log | list[dict] | [] | Full conversation log. Each entry: {role, text, stage, turn}. |

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
| position_skip | bool | True when LLM signals POSITION should be bypassed |

---

## G. WORKFLOW ANALYSIS

### Stage Machine — Complete Transition Rules

```
Initial state: stage="GREET", close_substage="PURCHASE_INTENT", turn_in_stage=0

GREET
  → DISCOVERY: Python unconditional after 1 turn (single-turn bridge)
             LLM may also request DISCOVERY in META (both agree)

DISCOVERY
  → GAP_CALC (term) or RECOMMEND (savings): Python only, when discovery_sufficient() == True
  → GAP_CALC or RECOMMEND: Python forces after 8 turns (fallback escape)
  → QUESTION_ANSWER / OBJECTIONS: LLM may request (interrupt, return after 1 turn)
  [LLM cannot force advance out of DISCOVERY to any other stage]

GAP_CALC
  → POSITION: Python forces after 1 turn
  → QUESTION_ANSWER / OBJECTIONS: LLM allowed

POSITION
  → RECOMMEND: Python forces after 1 turn
  [OR: LLM signals position_skip=true + stage=RECOMMEND → Python honours (sets position_skipped=True)]
  → QUESTION_ANSWER / OBJECTIONS: LLM allowed

RECOMMEND
  → VARIANTS (term) or EXPLAIN (savings): Python forces after 1 turn
  → QUESTION_ANSWER / OBJECTIONS: LLM allowed

VARIANTS
  → CLOSE (close_substage=PROCEED): LLM requests in META (customer agreed)
  → CLOSE (close_substage=PURCHASE_INTENT): Python forces after 6 turns (hard escape)
  → QUESTION_ANSWER / OBJECTIONS: LLM allowed

EXPLAIN
  → CLOSE (close_substage=PURCHASE_INTENT): LLM requests or Python forces (last topic + 1 turn, or 6 turns)
  → QUESTION_ANSWER / OBJECTIONS: LLM allowed

QUESTION_ANSWER / OBJECTIONS
  → return_to_stage or previous_stage: Python forces after 1 turn

CLOSE (PURCHASE_INTENT)
  → PROCEED: LLM requests in META close_substage (customer yes)
  → FEEDBACK: LLM requests in META close_substage (customer no)
  → PROCEED: Python forces after 2 turns

CLOSE (PROCEED)
  → CLOSED: Python forces after 2 turns

CLOSE (FEEDBACK)
  → CLOSED: LLM requests OR Python forces after 2 turns

CLOSE (CLOSED)
  → Terminal state. QUESTION_ANSWER/OBJECTIONS interrupts BLOCKED.
```

---

## H. BUSINESS RULE ANALYSIS

### Cover Multipliers (cover_engine.py)

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

### Gap Calculation Formula (gap_engine.py)

```python
income_protection_lakh = income_lpa * years_of_support
gap_lakh = income_protection_lakh + liabilities_lakh - existing_cover_lakh
gap_lakh = max(0.0, gap_lakh)
```

Defaults: years_of_support = 20 if not stated, liabilities = 0, existing = 0.
Assumptions are listed in the spoken walkthrough injected into GAP_CALC prompt.

### discovery_sufficient() Gates (memory.py)

```python
def discovery_sufficient(self, plan_type: str = "other") -> bool:
    return (
        self.age is not None
        and self.income_range is not None
        and self.existing_cover_lakh is not None   # 0.0 = explicitly "no insurance"
        and self.years_of_support is not None
    )
```

Applies to all plan types (simplified from old design which had per-type requirements).

### Premium Actuarial Constants (recommendation.py)

```python
_TERM_BASE_PREMIUM_PER_CRORE = 8500   # ₹/year for 25-yr non-smoker, 30-yr term, ₹1 crore
_TERM_BASE_AGE = 25
_AGE_LOADING_PER_YEAR = 0.035         # 3.5% compound per year above base age
_SMOKER_LOADING = 0.65                # 65% extra for smokers
```

Premium formula:
```
age_factor = (1 + 0.035)^max(0, age - 25)
smoker_factor = 1.65 (smoker) or 1.0 (non-smoker)
annual_per_crore = base_per_crore × age_factor × smoker_factor
annual_premium = annual_per_crore × cover_lakh / 100
```

### GST Rate (quote_engine.py)

```python
_GST_RATE = 0.18  # 18% GST on all insurance premiums
```

### Payment Frequency Factors (quote_engine.py)

```python
_DEFAULT_FREQ_RULES = {
    "annual":      {"factor": 1.0000, "count": 1},
    "semi_annual": {"factor": 0.5100, "count": 2},
    "quarterly":   {"factor": 0.2600, "count": 4},
    "monthly":     {"factor": 0.0883, "count": 12},
}
```

### choose_explain_topics() per plan_type (memory.py)

```
health:  coverage_and_sum_insured, hospitalisation_and_claims, exclusions_and_waiting_period, tax_benefits
ulip:    coverage_amount, fund_options_and_risk, charges_and_liquidity, tax_benefits
savings: how_the_plan_works, death_benefit_and_nominee_payout, maturity_benefit_and_bonuses, tax_benefits
pension: corpus_building_and_growth, annuity_payout_options, vesting_age_and_term, tax_benefits
child:   corpus_at_maturity, premium_waiver_on_death, policy_term_and_flexibility, tax_benefits
other:   how_the_plan_works, key_benefits, premium_structure, exclusions
```

Note: Term plans use VARIANTS stage, not EXPLAIN. choose_explain_topics() is only called for savings/health/non-term plans.

### Language Commit Threshold (memory.py)

```python
if confidence < 0.7:
    return  # do not commit
```

Single detection at ≥ 0.70 commits immediately.

### MAX_HISTORY_TURNS (agent.py)

```python
MAX_HISTORY_TURNS = 6
relevant_log = self.memory.turn_log[-(MAX_HISTORY_TURNS * 2):]
```

Last 12 log entries (6 user + 6 assistant turns) are included as history messages.

### TTS Character Limit (tts.py)

```python
MAX_TTS_CHARS = 400
```

Truncation at last sentence boundary within 400 chars. Hard cut to 400 if no boundary found.

### Actuarial Validation Bounds (structure_builder.py)

```python
_TERM_PREMIUM_MIN = 2000    # ₹/crore/year floor
_TERM_PREMIUM_MAX = 500000  # ₹/crore/year ceiling
```

Age range check: 15-75 years. Monotonicity check: within same term, premiums must increase with age.

### Quote Capability Levels (structure_builder.py)

```
0 = no data (QuoteError raised)
1 = illustrative (1-2 rows, confidence=inferred)
2 = table-based (3+ rows, exact or scaled)
3 = full (6+ exact rows, multiple terms)
```

---

## I. COMPLETE PROMPT INVENTORY TABLE

| Prompt Name | File | Purpose | Used By |
|---|---|---|---|
| MAIN_SYSTEM_PROMPT | prompts.py | Master system prompt template for all LLM agent calls | agent.py _build_messages() |
| OPENER_PROMPT | prompts.py | UNUSED. Was LLM opener. Superseded by deterministic generate_opener() | Not called |
| VOICE_RULES | prompts.py | Speech formatting, hallucination prohibition, language rules | MAIN_SYSTEM_PROMPT {voice_rules} |
| ADVISOR_RULES | prompts.py | Advisor behavioral rules including direct recommendation rule and age guard | MAIN_SYSTEM_PROMPT {advisor_rules} |
| DEFLECTION_PLAYBOOK | prompts.py | Objection handling scripts; ROP only on explicit "what if I survive?" objection | MAIN_SYSTEM_PROMPT {deflection_playbook} (VARIANTS/EXPLAIN/RECOMMEND/OBJECTIONS/CLOSE) |
| META_TAG_INSTRUCTION | prompts.py | Structured output tag format, stage transition table, position_skip field | MAIN_SYSTEM_PROMPT {meta_tag_instruction} |
| STAGE_INTENTS["GREET"] | prompts.py | Bridge to DISCOVERY, no re-intro | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["DISCOVERY"] | prompts.py | Collect 4 gating fields, income-gated, no product mentions | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["GAP_CALC"] | prompts.py | Walk through deterministic gap from GAP CALCULATION block | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["POSITION"] | prompts.py | Car insurance reframe; skippable with position_skip | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["RECOMMEND"] | prompts.py | Name plan directly, 3-4 sentences, one reason | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["VARIANTS"] | prompts.py | One variant default, rider questions, assumptive close, ROP on objection only | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["EXPLAIN"] | prompts.py | Savings/non-term plan topic explanation | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["OBJECTIONS"] | prompts.py | Acknowledge, explore, respond, return | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["QUESTION_ANSWER"] | prompts.py | Document fact answering with profile personalization | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS["CLOSE"] | prompts.py | Delegates to CLOSE_SUBSTAGE_INTENTS | MAIN_SYSTEM_PROMPT {stage_intent} |
| STAGE_INTENTS legacy stubs | prompts.py | INTRODUCE, PROFILE, PERSONALIZE, NEED_DEVELOPMENT, RECOMMENDATION, HANDLE — kept for backward compat | Never reached by current stage machine |
| CLOSE_SUBSTAGE_INTENTS["PURCHASE_INTENT"] | prompts.py | Assumptive close with commitment questions | MAIN_SYSTEM_PROMPT when substage=PURCHASE_INTENT |
| CLOSE_SUBSTAGE_INTENTS["PROCEED"] | prompts.py | Exact handoff message only; forbidden PII collection | MAIN_SYSTEM_PROMPT when substage=PROCEED |
| CLOSE_SUBSTAGE_INTENTS["FEEDBACK"] | prompts.py | Collect decline reason, no re-selling | MAIN_SYSTEM_PROMPT when substage=FEEDBACK |
| CLOSE_SUBSTAGE_INTENTS["CLOSED"] | prompts.py | Terminal closing line, blocks all further engagement | MAIN_SYSTEM_PROMPT when substage=CLOSED |
| CLOSE_SUBSTAGE_INTENTS["SUMMARY"] | prompts.py | VESTIGIAL — never reached; close_substage starts at PURCHASE_INTENT | Not reached |
| EVALUATION_PROMPT | prompts.py | Post-conversation coaching report | evaluation.py evaluate_session() |
| Ingestion Metadata Prompt | ingestion.py | Extract plan_name, company_name, plan_type, one_line_pitch | ingestion._extract_metadata() |
| Ingestion Brief Prompt | ingestion.py | Rewrite document sections as advisor cheat-sheet (no rupee amounts in PREMIUMS) | ingestion._generate_brief_via_llm() |
| Structure Builder GPT Prompt | structure_builder.py | Extract illustrative premiums as JSON when no table found | structure_builder._gpt_extract_illustrative_premium() |

---

## J. COMPLETE MODEL INVENTORY TABLE

| Component | Provider | Model | File | Config |
|---|---|---|---|---|
| Main LLM agent | OpenAI | gpt-4o-mini | llm.py (via LLMClient) | Stage-scoped temperature; max_tokens default 600 |
| Ingestion metadata | OpenAI | gpt-4o-mini | ingestion.py _extract_metadata() | temperature=0.1, max_tokens=200 |
| Ingestion brief | OpenAI | gpt-4o-mini | ingestion.py _generate_brief_via_llm() | temperature=0.3, max_tokens=900 |
| Structure builder GPT fallback | OpenAI | gpt-4o-mini | structure_builder.py _gpt_extract_illustrative_premium() | temperature=0.0, max_tokens=400 |
| Evaluation | OpenAI | gpt-4o-mini | evaluation.py evaluate_session() | via main LLM client |
| STT | Sarvam | saaras:v3 | stt.py | mode=codemix, language_code=unknown always |
| TTS (non-streaming) | Sarvam | bulbul:v3 | tts.py synthesize() | pace=1.1, sample_rate=22050, output_audio_codec=wav |
| TTS (streaming) | Sarvam | bulbul:v3 | tts.py synthesize_stream() | pace=1.3, sample_rate=22050, output_audio_codec=wav |

---

## K. COMPLETE API INVENTORY TABLE

| API | Purpose | File | Endpoint/Method |
|---|---|---|---|
| OpenAI Chat Completions | Main LLM, ingestion, evaluation | llm.py, ingestion.py, structure_builder.py, evaluation.py | POST /v1/chat/completions |
| Sarvam STT | Transcribe audio | stt.py | client.speech_to_text.transcribe() |
| Sarvam TTS | Synthesize speech | tts.py | client.text_to_speech.convert() / .convert_stream() |

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

**Requirement:** Know the customer's age before progressing past DISCOVERY.

**Trace:**

1. **Prompt:** STAGE_INTENTS["DISCOVERY"] (prompts.py) instructs LLM to "Ask age first — it is required before any recommendation or gap calculation."

2. **Prompt:** `{missing_fields_line}` (agent.py _build_messages) is computed at DISCOVERY stage. If age is None: "⚠ CRITICAL: Customer age is NOT yet known. ASK FOR AGE NOW."

3. **Pre-LLM tool:** `extract_profile_fields(user_text)` in profile_extractor.py is called BEFORE the LLM call. If the user says "I'm 29 years old", this extracts `{"age": 29}`.

4. **Profile update:** `memory.customer_profile.apply_updates({"age": 29})` sets `self.age = 29` and appends "age" to `fields_collected`.

5. **Stage gate:** After LLM response, `_auto_advance_stage()` calls `memory.customer_profile.discovery_sufficient(plan_type)`. Gate requires age + income_range + existing_cover_lakh + years_of_support.

6. **8-turn fallback:** If discovery_sufficient() never fires, Python forces advance after 8 turns regardless.

---

### Example 2: "Compute protection gap" requirement

**Requirement:** Show the customer their exact protection gap in numbers before introducing the product.

**Trace:**

1. **Trigger:** _auto_advance_stage() fires after DISCOVERY when discovery_sufficient() == True (or 8-turn escape). For term plans, stage advances to GAP_CALC.

2. **Python computation:** In `_build_messages()` at GAP_CALC stage:
   ```python
   gap = build_gap_calculation(self.memory.customer_profile)
   if gap:
       self.memory.intelligence.gap_lakh = gap["gap_lakh"]
       gap_block = gap_to_prompt_block(gap)
   ```

3. **Prompt injection:** `gap_block` is prepended to `recommendation_block` area in MAIN_SYSTEM_PROMPT. The block includes the full spoken walkthrough.

4. **Stage intent:** STAGE_INTENTS["GAP_CALC"] instructs LLM to walk through the calculation exactly as shown. "Use ONLY the numbers from the GAP CALCULATION block. Do not compute differently."

5. **LLM response:** Agent speaks the gap in conversational language: "So your income of ₹15 lakh a year, over 20 years, gives us ₹3 crore just to replace your income. Plus your home loan of ₹30 lakh — the protection your family actually needs is around ₹3.3 crore."

6. **Stored for later stages:** `memory.intelligence.gap_lakh = 330` is injected into VARIANTS and CLOSE stages as a reminder: "CUSTOMER PROTECTION GAP (computed at GAP_CALC): ₹3.3 crore."

---

### Example 3: "Never hallucinate premiums" requirement

**Requirement:** The agent must never state a specific premium amount it cannot verify from the document or deterministic calculation.

**Trace:**

1. **Ingestion prompt:** `_generate_brief_via_llm()` instructs GPT to exclude rupee amounts from the PREMIUMS brief section.

2. **Brief stripping:** In `agent.py` `_build_messages()` at GREET/DISCOVERY stages, the PREMIUMS section is regex-stripped from `brief`.

3. **RULE 0 GROUNDEDNESS:** prompts.py preamble — "Every rupee amount must exist verbatim in PRODUCT KNOWLEDGE, CALCULATED NUMBERS, or the GAP CALCULATION block."

4. **VOICE_RULES:** "NEVER compute or mention rupee amounts, cover ranges, or premiums in GREET or DISCOVERY stages."

5. **Python rupee guard:** `_guard_discovery_numbers(clean, profile)` replaces any ₹ amount in DISCOVERY response with a redirect.

6. **smoker=None suppression:** recommendation.py returns `premium_display: None` if smoker status unknown.

7. **Deterministic quote:** At CLOSE, `generate_quote()` computes premium from structure.json with full calculation trail. `quote_to_prompt_block()` appends: "IMPORTANT: Present these numbers exactly as shown."

8. **Fallback:** If QuoteError is raised, `policy_quote = ""` and the LLM sees only the actuarial estimate with "source: industry benchmark estimate" — prompting it to hedge.

---

### Example 4: "Handle price objection" requirement

**Requirement:** When a customer says "it's too expensive," the agent should reframe rather than defend or abandon.

**Trace:**

1. **META tag parsing:** LLM appends `[META stage=OBJECTIONS objection=price ...]` to its response. `parse_meta_tag()` extracts `objection_category="price"`.

2. **Memory update:** `apply_analysis()` appends `{text, category:"price", turn:N, resolved:False}` to `intelligence.objections`. Stage transitions to OBJECTIONS; `return_to_stage` set to current stage.

3. **Stage intent:** STAGE_INTENTS["OBJECTIONS"] instructs: "Acknowledge → Explore root concern → Respond with one concrete fact or reframe → Return naturally."

4. **Deflection playbook:** DEFLECTION_PLAYBOOK: "'Too expensive' → Translate to daily cost (annual ÷ 365), mention 80C deduction."

5. **Emotional guide:** Arjun's `{emotional_guide}`: "Price shock: Do not defend the premium immediately. Ask 'What were you expecting?' Then reframe."

6. **Python escape:** After 1 turn in OBJECTIONS, `_auto_advance_stage()` returns to `return_to_stage` — the conversation continues from where it was interrupted.

7. **Objection resolution:** On next successful turn, LLM can emit `[META objection=price objection_resolved=true ...]`. apply_analysis marks the objection as resolved.

---

### Example 5: "Close the sale" requirement

**Requirement:** At the end of the sales flow, the agent should make an assumptive close and guide the customer through the handoff process.

**Trace:**

1. **VARIANTS assumptive close:** STAGE_INTENTS["VARIANTS"] instructs: "STEP 3 — ASSUMPTIVE CLOSE: once variant + riders are clear, end with: 'So shall we go with [variant] for [gap amount] cover?'"

2. **Customer agrees:** LLM emits `[META stage=CLOSE close_substage=PROCEED ...]`. Agent says "Perfect, let's get that set up for you."

3. **apply_analysis VARIANTS→CLOSE shortcut:** In apply_analysis, when current=VARIANTS and requested=CLOSE: `memory.close_substage = "PROCEED"` (skips PURCHASE_INTENT).

4. **PROCEED intent:** CLOSE_SUBSTAGE_INTENTS["PROCEED"]: Deliver EXACT handoff message. ABSOLUTELY FORBIDDEN: collect PII, describe application steps, generate links.

5. **Auto-advance to CLOSED:** `_auto_advance_close_substage()` sets `close_substage = "CLOSED"` after 2 turns in PROCEED (threshold >= 2 prevents same-turn skip).

6. **Terminal state:** CLOSE_SUBSTAGE_INTENTS["CLOSED"]: Warm closing message. QUESTION_ANSWER/OBJECTIONS blocked.

---

## M. DEMO PREPARATION REFERENCE TABLE

| Behaviour to demonstrate | File | Function | Key Detail |
|---|---|---|---|
| Opener generated without LLM | agent.py | generate_opener() | Deterministic from plan_name + character name |
| Language switches to Hindi automatically | memory.py | update_language() | Threshold: confidence >= 0.70 |
| Profile fields extracted from speech | profile_extractor.py | extract_profile_fields() | 12 fields via regex |
| Stage advances from DISCOVERY to GAP_CALC | agent.py | _auto_advance_stage() | discovery_sufficient(): age + income + existing_cover_lakh + years_of_support |
| Gap calculated deterministically | gap_engine.py | build_gap_calculation() | income_lpa × years + liabilities − existing |
| Gap injected into system prompt | agent.py | _build_messages() | gap_to_prompt_block() at GAP_CALC stage |
| Position reframe with skip option | prompts.py | STAGE_INTENTS["POSITION"] | position_skip=true in META bypasses POSITION |
| Named product recommendation | prompts.py | STAGE_INTENTS["RECOMMEND"] | "I'm recommending Click2Protect Life from HDFC" |
| Variant selection + assumptive close | prompts.py | STAGE_INTENTS["VARIANTS"] | Life Option default; ADB rider; no ROP unless objection |
| Discovery rupee hallucination blocked | agent.py | _guard_discovery_numbers() | Python replaces ₹ amounts with redirect |
| Risk narrative personalised to customer | agent.py | build_risk_narrative() | Deterministic 5-6 sentence vulnerability story |
| Premium hallucination blocked at early stages | agent.py | _build_messages() PREMIUMS strip | Regex strips PREMIUMS at GREET/DISCOVERY |
| Deterministic cover recommendation | cover_engine.py | recommend_cover() | Income × multiplier + liabilities − existing |
| Premium quote from document tables | quote_engine.py | generate_quote() | structure.json lookup + interpolation + GST |
| Price objection handled | conversation_analyzer.py + prompts.py | apply_analysis() + DEFLECTION_PLAYBOOK | Reframe, not defend |
| Stage machine prevents premature CLOSE | conversation_analyzer.py | apply_analysis() _LLM_ALLOWED_TRANSITIONS | DISCOVERY LLM-signal blocked; only Python advances |
| VARIANTS → CLOSE skips PURCHASE_INTENT | conversation_analyzer.py | apply_analysis() | close_substage set to PROCEED directly on VARIANTS→CLOSE |
| Close substage PROCEED threshold >= 2 | agent.py | _auto_advance_close_substage() | Prevents same-turn skip to CLOSED |
| CLOSED blocks question answering | conversation_analyzer.py | apply_analysis() | Interrupt blocked when close_substage == CLOSED |
| Post-conversation evaluation | evaluation.py | evaluate_session() | 8-section coaching report via LLM |
| 10MB audio upload limit | main.py | transcribe_audio() | MAX_AUDIO_BYTES = 10MB |
| Session isolation with asyncio.Lock | main.py | _session_locks | Per-session concurrency control |
| TTS character limit prevents API error | tts.py | _truncate_for_tts() | Hard cap 400 chars |
| BM25 document retrieval | rag.py | DocumentStore.get_context() | Top-3 chunks, 1500 char limit |
| META tag parsing | conversation_analyzer.py | parse_meta_tag() | Strips tag, returns TurnAnalysis |
| Interest and close_readiness scoring | memory.py | CustomerIntelligence.update_intent() + lead_score() | Weighted: 40% interest + 30% close_readiness |
| Language commit threshold | memory.py | update_language() | Confidence < 0.7 → no commit |
| Per-turn language reminder | prompts.py | MAIN_SYSTEM_PROMPT | ⚠️ LANGUAGE THIS TURN appended at end |
