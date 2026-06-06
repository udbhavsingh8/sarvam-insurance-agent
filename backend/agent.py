"""
AgentSession — one session of the Insurance Sales Voice Agent.

Wires together: LLMClient, DocumentStore, SessionMemory, CharacterRegistry,
ConversationAnalyzer, and metrics logging.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Iterator

from characters import CHARACTERS, SUPPORTED_LANGUAGES
from conversation_analyzer import apply_analysis, parse_meta_tag
from errors import LLMError
from gap_engine import build_gap_calculation, gap_to_prompt_block, _fmt_lakh
from llm import LLMClient
from memory import SessionMemory, choose_explain_topics
from metrics import TurnMetrics, log_session, log_turn
from profile_extractor import extract_profile_fields
from prompts import ADVISOR_RULES, DEFLECTION_PLAYBOOK, MAIN_SYSTEM_PROMPT, META_TAG_INSTRUCTION, OPENER_PROMPT, STAGE_INTENTS, VOICE_RULES, language_display_name
from recommendation import build_recommendation_block
from rag import DocumentStore
from cover_engine import recommend_cover
from quote_engine import generate_quote, quote_to_prompt_block, QuoteError

_FALLBACK = "I'm having a connection issue right now. Could you give me a moment and try again?"

# Rupee-amount patterns that should never appear in a DISCOVERY response.
_RUPEE_RE = re.compile(
    r'(?:₹\s*\d|'           # ₹500, ₹ 1
    r'\d+\s*(?:lakh|crore|cr\b|l\b)|'  # 50 lakh, 2 crore, 3cr
    r'(?:lakh|crore)\s*\d)', # lakh 50 (unusual order)
    re.IGNORECASE,
)

def _guard_discovery_numbers(text: str, profile: object) -> str:
    """
    Hard safety net: block any rupee amount the LLM produces during DISCOVERY.

    The LLM should NEVER mention cover amounts or premiums at this stage —
    it doesn't have enough data yet. When triggered, redirect to the most
    critical missing data point.
    """
    if not _RUPEE_RE.search(text):
        return text

    age_known = getattr(profile, "age", None) is not None
    income_known = getattr(profile, "income_range", None) is not None

    if not age_known:
        return (
            "Before I get to the numbers — can I ask your age quickly? "
            "It's the first thing I need to work out the right cover for you."
        )
    if not income_known:
        return (
            "I'll get to the numbers in a moment — I just need your annual income first. "
            "What does your income look like, roughly?"
        )
    # Both age and income are known. The LLM probably echoed a loan amount the
    # user just mentioned — that is acceptable, let it through.
    return text


def build_risk_narrative(profile: "SessionMemory.customer_profile") -> str:  # type: ignore[name-defined]
    """
    Convert profile fields into a personalised financial risk narrative.
    Pure deterministic Python — no LLM call.
    Injected into the system prompt at NEED_DEVELOPMENT, EXPLAIN, RECOMMENDATION, and CLOSE
    so the agent always has the 'story' context, not just a field list.
    """
    from memory import CustomerProfile
    if not isinstance(profile, CustomerProfile) or not profile.age:
        return ""

    sentences: list[str] = []

    # Age framing — why now matters
    if profile.age <= 30:
        sentences.append(
            f"At {profile.age}, this is the best possible time to lock in cover — "
            "premiums are at their lowest and health conditions that could affect eligibility have not appeared yet."
        )
    elif profile.age <= 40:
        sentences.append(
            f"At {profile.age}, this is still a strong window to secure adequate cover "
            "before premiums rise significantly with age."
        )
    else:
        sentences.append(
            f"At {profile.age}, securing cover now is time-sensitive — "
            "both premium rates and eligibility windows narrow with every passing year."
        )

    # Family vulnerability — the emotional core of the sale
    if profile.dependents and profile.dependents > 0:
        dep_str = f"{profile.dependents} dependent{'s' if profile.dependents > 1 else ''}"
        if profile.marital_status == "married":
            sentences.append(
                f"A spouse and {dep_str} rely on this income entirely. "
                "If that income stopped unexpectedly, their financial stability would be immediately at risk."
            )
        else:
            sentences.append(
                f"{dep_str.capitalize()} rely on this income. "
                "A sudden loss of earnings would directly affect their day-to-day life."
            )
    elif profile.marital_status == "married":
        sentences.append(
            "A spouse depends on this income. "
            "If that income stopped unexpectedly, they would face immediate financial pressure with no backup in place."
        )

    # Coverage gap — the urgency
    if profile.existing_coverage == "none":
        sentences.append(
            "There is currently no insurance coverage in place — "
            "meaning the family has no financial safety net if something goes wrong."
        )
    elif profile.existing_coverage == "some":
        sentences.append(
            "Existing coverage is limited and likely insufficient "
            "to replace income or cover major liabilities in the event of a serious incident."
        )

    # Income — what is actually at stake
    if profile.income_range:
        sentences.append(
            f"An income of {profile.income_range} funds the household, any loans, "
            "and the family's future goals — all of which stop the moment that income stops."
        )

    # Liabilities — the debt risk
    if profile.liabilities_lakh and profile.liabilities_lakh > 0:
        sentences.append(
            f"Outstanding loans of approximately {profile.liabilities_lakh:.0f} lakh "
            "would still need to be serviced even if income stops — adding direct financial pressure on the family."
        )

    # Smoker — elevated risk context
    if profile.smoker:
        sentences.append(
            "As a smoker, health risk is elevated — "
            "which makes securing adequate cover now, before any complications arise, especially important."
        )

    if not sentences:
        return ""

    return "CUSTOMER RISK NARRATIVE (use this to personalise every response):\n" + " ".join(sentences)


def _auto_advance_stage(memory: SessionMemory, plan_type: str = "other") -> None:
    """
    Python-controlled stage gating for the new consultative sales flow.

    Term:    GREET → DISCOVERY → GAP_CALC → POSITION → RECOMMEND → VARIANTS → CLOSE
    Savings: GREET → DISCOVERY → RECOMMEND → EXPLAIN → CLOSE
    Any:     → QUESTION_ANSWER | OBJECTIONS (return after 1 turn)

    Python has final say on all transitions. LLM signals intent via META tag;
    this function enforces the gates.
    """
    stage = memory.stage

    # ── GREET: escape after 1 turn — opener already introduced; GREET turn is just the bridge question ──
    if stage == "GREET" and memory.turn_in_stage >= 1:
        memory.previous_stage = stage
        memory.stage = "DISCOVERY"
        memory.turn_in_stage = 0
        return

    # ── DISCOVERY: advance only when discovery_sufficient() is True ──────
    # Python-only gate — LLM cannot signal out of DISCOVERY.
    if stage == "DISCOVERY":
        if memory.customer_profile.discovery_sufficient(plan_type) or memory.turn_in_stage >= 8:
            memory.previous_stage = stage
            if plan_type == "term":
                memory.stage = "GAP_CALC"
            else:
                memory.stage = "RECOMMEND"
            memory.turn_in_stage = 0
        return  # always return — never fall through

    # ── GAP_CALC: auto-advance to POSITION after 1 turn ─────────────────
    if stage == "GAP_CALC" and memory.turn_in_stage >= 1:
        memory.previous_stage = stage
        memory.stage = "POSITION"
        memory.turn_in_stage = 0
        return

    # ── POSITION: auto-advance to RECOMMEND after 1 turn ────────────────
    if stage == "POSITION" and memory.turn_in_stage >= 1:
        memory.previous_stage = stage
        memory.stage = "RECOMMEND"
        memory.turn_in_stage = 0
        return

    # ── RECOMMEND: auto-advance after 1 turn ────────────────────────────
    if stage == "RECOMMEND" and memory.turn_in_stage >= 1:
        memory.previous_stage = stage
        memory.stage = "VARIANTS" if plan_type == "term" else "EXPLAIN"
        memory.turn_in_stage = 0
        return

    # ── VARIANTS: LLM drives this (signals CLOSE when done).
    #    Hard escape after 6 turns to prevent infinite loop.
    if stage == "VARIANTS" and memory.turn_in_stage >= 6:
        memory.previous_stage = stage
        memory.stage = "CLOSE"
        memory.close_substage = "PURCHASE_INTENT"
        memory.turn_in_stage = 0
        return

    # ── EXPLAIN (savings plans): advance to CLOSE when all topics covered ─
    if stage == "EXPLAIN":
        topics = memory.explain_topics
        on_last_topic = (not topics or
                         memory.explain_subtopic_index >= len(topics) - 1)
        if (on_last_topic and memory.turn_in_stage >= 1) or memory.turn_in_stage >= 6:
            memory.previous_stage = stage
            memory.stage = "CLOSE"
            memory.close_substage = "PURCHASE_INTENT"
            memory.turn_in_stage = 0
        return

    # ── QUESTION_ANSWER / OBJECTIONS: return after 1 turn ───────────────
    if stage in ("QUESTION_ANSWER", "OBJECTIONS"):
        if memory.turn_in_stage >= 1:
            return_to = memory.return_to_stage or memory.previous_stage or "DISCOVERY"
            memory.previous_stage = stage
            memory.stage = return_to
            memory.return_to_stage = None
            memory.turn_in_stage = 0
        return

    # ── CLOSE: substage machine ──────────────────────────────────────────
    if stage == "CLOSE":
        _auto_advance_close_substage(memory)

    # ── Legacy stages (kept for sessions that started on old code) ───────
    if stage == "INTRODUCE" and memory.turn_in_stage >= 2:
        memory.stage = "GREET"
        memory.turn_in_stage = 0


def _auto_advance_close_substage(memory: SessionMemory) -> None:
    """Python-controlled close substage gating.

    New flow starts at PURCHASE_INTENT (assumptive close).
    PROCEED → CLOSED after 1 turn.
    FEEDBACK → CLOSED after 1 turn (LLM can also signal it via META).
    """
    sub = memory.close_substage

    # PURCHASE_INTENT: LLM signals PROCEED via META; Python forces after 2 turns.
    # Prevents the "Great choice! Let's get started!" loop that leads to PII collection.
    if sub == "PURCHASE_INTENT" and memory.turn_in_stage >= 2:
        memory.close_substage = "PROCEED"
        memory.turn_in_stage = 0
        return

    # PROCEED: handoff message delivered — auto close.
    # Threshold is >= 2 because the VARIANTS→CLOSE transition increments turn_in_stage
    # to 1 in the same Python call before the PROCEED LLM has had any turn.
    if sub == "PROCEED" and memory.turn_in_stage >= 2:
        memory.close_substage = "CLOSED"
        memory.turn_in_stage = 0
        return

    # FEEDBACK: collect one response then close
    if sub == "FEEDBACK" and memory.turn_in_stage >= 2:
        memory.close_substage = "CLOSED"
        memory.turn_in_stage = 0
        return


class AgentSession:
    def __init__(
        self,
        store: DocumentStore,
        character_id: str = "arjun",
        session_id: str | None = None,
    ) -> None:
        self.store = store
        self.session_id = session_id or str(uuid.uuid4())
        self.character = CHARACTERS.get(character_id, CHARACTERS["arjun"])
        self.memory = SessionMemory(character_id=self.character["id"])
        self._llm = LLMClient()
        self._start_time = time.time()

    # ── Public interface ───────────────────────────────────────────────

    def generate_opener(self) -> str:
        """
        Build a clean opening line directly from document metadata — no LLM call.
        Eliminates placeholder hallucination and removes one full API round-trip.
        """
        import re as _re

        def _clean(s: str) -> str:
            return _re.sub(r'\[[^\]]{0,40}\]', '', s).strip()

        name = self.character["name"]
        plan_name = _clean(self.store.metadata.get("plan_name", "this policy"))

        return (
            f"Hi, I'm {name} from PolicyAI. "
            f"I've gone through the {plan_name} policy document and can help you understand "
            f"the coverage, benefits, premiums, riders, and important conditions in simple terms. "
            f"To start, have you already looked into this plan before, or would you like a quick overview?"
        )

    def chat(self, user_text: str) -> str:
        """
        Process one user turn. Returns clean agent response text.
        Updates session memory with language, stage, and intelligence signals.
        On LLM failure returns a fallback line and logs the error.
        """
        t0 = time.time()
        llm_error = False
        error_detail: str | None = None

        # Detect language from typed text (voice path uses STT-based update_language).
        self.detect_language_from_text(user_text)

        # Extract profile fields from user text deterministically — before LLM call.
        self.memory.customer_profile.apply_updates(extract_profile_fields(user_text))

        messages = self._build_messages(user_text)
        t_llm_start = time.time()
        try:
            raw = self._llm.complete(messages, stage=self.memory.stage)
        except LLMError as exc:
            raw = _FALLBACK
            llm_error = True
            error_detail = str(exc)
        llm_ms = int((time.time() - t_llm_start) * 1000)

        clean, analysis = parse_meta_tag(raw)

        # Stage-level hallucination guard: if LLM mentioned rupee amounts during
        # DISCOVERY (where numbers are forbidden), replace with a safe redirect.
        if not llm_error and self.memory.stage == "DISCOVERY":
            clean = _guard_discovery_numbers(clean, self.memory.customer_profile)

        # If the model produced only a META tag with no spoken text, use fallback
        if not clean.strip() and not llm_error:
            clean = _FALLBACK
            llm_error = True
            error_detail = "empty response after META tag strip"

        self.memory.turn_count += 1
        self.memory.log_turn("user", user_text)
        self.memory.log_turn("assistant", clean)

        if analysis and not llm_error:
            apply_analysis(self.memory, analysis, user_text)
        else:
            # No META tag or LLM error — still advance the turn counter so
            # Python's stage gates (GREET → DISCOVERY etc.) can fire correctly.
            self.memory.turn_in_stage += 1

        _auto_advance_stage(self.memory, self.store.metadata.get("plan_type", "other"))

        log_turn(TurnMetrics(
            session_id=self.session_id,
            turn_id=self.memory.turn_count,
            timestamp=t0,
            stt_latency_ms=0,
            llm_latency_ms=llm_ms,
            tts_latency_ms=0,
            transcript_chars=len(user_text),
            response_chars=len(clean),
            detected_language=self.memory.detected_language,
            stage=self.memory.stage,
            character=self.character["id"],
            llm_error=llm_error,
            error_detail=error_detail,
        ))

        return clean

    def chat_stream(self, user_text: str) -> Iterator[str]:
        """
        Stream agent response tokens. Caller must collect the full text
        to update history — call record_turn() after streaming is done.
        """
        messages = self._build_messages(user_text)
        self._pending_user_text = user_text
        self._stream_parts: list[str] = []

        for token in self._llm.stream(messages, stage=self.memory.stage):
            self._stream_parts.append(token)
            yield token

    def record_turn(
        self,
        llm_ms: int = 0,
        stt_ms: int = 0,
        tts_ms: int = 0,
        llm_error: bool = False,
        error_detail: str | None = None,
    ) -> None:
        """
        Called after a streaming turn completes.
        Assembles full response, parses META tag, updates memory.
        """
        raw = "".join(self._stream_parts) if self._stream_parts else _FALLBACK
        clean, analysis = parse_meta_tag(raw)

        user_text = getattr(self, "_pending_user_text", "")
        if user_text:
            # Detect language from typed text (streaming path)
            self.detect_language_from_text(user_text)
            # Extract profile fields from user text (covers the streaming path)
            self.memory.customer_profile.apply_updates(extract_profile_fields(user_text))
        self.memory.turn_count += 1
        self.memory.log_turn("user", user_text)
        self.memory.log_turn("assistant", clean)

        if analysis and not llm_error:
            apply_analysis(self.memory, analysis, user_text)
        else:
            self.memory.turn_in_stage += 1

        _auto_advance_stage(self.memory, self.store.metadata.get("plan_type", "other"))

        log_turn(TurnMetrics(
            session_id=self.session_id,
            turn_id=self.memory.turn_count,
            timestamp=time.time(),
            stt_latency_ms=stt_ms,
            llm_latency_ms=llm_ms,
            tts_latency_ms=tts_ms,
            transcript_chars=len(user_text),
            response_chars=len(clean),
            detected_language=self.memory.detected_language,
            stage=self.memory.stage,
            character=self.character["id"],
            llm_error=llm_error,
            error_detail=error_detail,
        ))

        self._stream_parts = []
        self._pending_user_text = ""

    def update_language(self, language_code: str, probability: float) -> None:
        """Called after STT to propagate detected language into memory."""
        self.memory.update_language(language_code, probability)

    def detect_language_from_text(self, text: str) -> None:
        """
        Detect language from typed text by Unicode script ranges.
        Fires only when user types (no STT), so voice-detected language is
        not overwritten — STT probability gating already handles that path.
        """
        _SCRIPT_LANGS = [
            (0x0900, 0x097F, "hi-IN"),   # Devanagari → Hindi
            (0x0980, 0x09FF, "bn-IN"),   # Bengali
            (0x0A00, 0x0A7F, "pa-IN"),   # Gurmukhi → Punjabi
            (0x0A80, 0x0AFF, "gu-IN"),   # Gujarati
            (0x0B00, 0x0B7F, "or-IN"),   # Odia (not in Sarvam list, skip)
            (0x0B80, 0x0BFF, "ta-IN"),   # Tamil
            (0x0C00, 0x0C7F, "te-IN"),   # Telugu
            (0x0C80, 0x0CFF, "kn-IN"),   # Kannada
            (0x0D00, 0x0D7F, "ml-IN"),   # Malayalam
            (0x0900, 0x097F, "mr-IN"),   # Marathi also uses Devanagari — default hi-IN is close enough
        ]
        for ch in text:
            cp = ord(ch)
            for lo, hi, lang in _SCRIPT_LANGS:
                if lo <= cp <= hi:
                    # Commit immediately for typed text — user intent is unambiguous
                    self.memory.update_language(lang, 1.0)
                    return

    def end_session(self) -> None:
        duration = time.time() - self._start_time
        log_session(self.session_id, self.memory, duration)

    @property
    def speaker(self) -> str:
        return self.character["voice"]

    @property
    def language(self) -> str:
        return self.memory.detected_language

    # ── Internal ───────────────────────────────────────────────────────

    def _build_messages(self, user_text: str) -> list[dict]:
        # GPT-4o-mini has a 128k context window. Keep limits generous but reasonable.
        BRIEF_CHAR_LIMIT = 3500
        DOC_CONTEXT_CHAR_LIMIT = 1500

        import re as _re

        brief = self.store.sales_brief or "No product profile available."

        # Strip PREMIUMS from brief during GREET and DISCOVERY — the benchmark
        # ₹22/day figure lives there and would be quoted as personalised without context.
        if self.memory.stage in ("GREET", "DISCOVERY", "INTRODUCE", "PROFILE", "NEED_DEVELOPMENT"):
            brief = _re.sub(
                r'PREMIUMS:.*?(?=\n[A-Z ]+:|$)',
                '',
                brief,
                flags=_re.DOTALL | _re.IGNORECASE,
            ).strip()

        if len(brief) > BRIEF_CHAR_LIMIT:
            brief = brief[:BRIEF_CHAR_LIMIT] + "\n[... product profile truncated for brevity ...]"

        raw_context = self.store.get_context(user_text, top_k=3)
        if len(raw_context) > DOC_CONTEXT_CHAR_LIMIT:
            raw_context = raw_context[:DOC_CONTEXT_CHAR_LIMIT]

        # ── DISCOVERY missing-fields line ───────────────────────────────────
        missing_fields_line = ""
        if self.memory.stage == "DISCOVERY":
            p = self.memory.customer_profile

            if p.age is None:
                # Age is required by discovery_sufficient() — collect it first
                missing_fields_line = (
                    "\n⚠ CRITICAL: Customer age is NOT yet known. "
                    "ASK FOR AGE NOW — it is required before any recommendation or gap calculation.\n"
                    "Say: 'Can I start with your age?' — ask this as the very first question.\n"
                    "DO NOT give any cover amount or recommendation without age.\n"
                )
            elif p.income_range is None:
                # Income is the gating field for GAP_CALC — focus entirely on it until collected
                missing_fields_line = (
                    "\n⚠ CRITICAL: Annual income is NOT yet known. "
                    "ASK FOR INCOME NOW before any other question.\n"
                    "Say: 'And roughly what is your annual income?' — nothing else until you have it.\n"
                    "If they ask 'how much cover do I need?' → "
                    "'That's exactly what I'll calculate for you — I just need your annual income first. "
                    "What does your income look like, roughly?'\n"
                    "DO NOT give any cover amount, ballpark, or recommendation without income.\n"
                )
            else:
                missing: list[str] = []
                if p.dependents is None and p.marital_status is None:
                    missing.append("who at home depends on your income")
                if p.liabilities_lakh is None:
                    missing.append("outstanding loans or EMIs (and amount)")
                if p.existing_coverage is None and p.existing_cover_lakh is None:
                    missing.append("existing life insurance (if any)")
                if p.years_of_support is None:
                    missing.append("how many years the family would need support")
                if missing:
                    missing_fields_line = (
                        f"\nSTILL TO COLLECT IN DISCOVERY: {', '.join(missing)}.\n"
                        f"Ask naturally — max 2 questions per turn. "
                        f"Do NOT ask about smoker status, product features, or cover amounts.\n"
                    )
                else:
                    # All key fields collected — tell the LLM to stop asking and bridge
                    missing_fields_line = (
                        "\nDISCOVERY COMPLETE: All key information has been collected.\n"
                        "DO NOT ask any more questions — not smoker status, not permissions.\n"
                        "Say ONE natural bridge sentence: 'ठीक है, let me work through the numbers' "
                        "or 'Great, let me now calculate what cover you need.' Then stop.\n"
                        "Python will advance the stage automatically.\n"
                    )

        # ── GAP_CALC block — inject at GAP_CALC stage ──────────────────────
        gap_block = ""
        if self.memory.stage == "GAP_CALC":
            from gap_engine import build_gap_calculation, gap_to_prompt_block
            gap = build_gap_calculation(self.memory.customer_profile)
            if gap:
                self.memory.intelligence.gap_lakh = gap["gap_lakh"]
                gap_block = gap_to_prompt_block(gap)

        # ── Risk narrative (injected at RECOMMEND, VARIANTS, CLOSE) ────────
        _NARRATIVE_STAGES = ("RECOMMEND", "VARIANTS", "EXPLAIN", "CLOSE", "OBJECTIONS")
        risk_narrative = (
            build_risk_narrative(self.memory.customer_profile)
            if self.memory.stage in _NARRATIVE_STAGES
            else ""
        )

        # ── Calculated numbers (VARIANTS and CLOSE) ─────────────────────────
        policy_quote = ""
        recommendation_block = ""
        if self.memory.stage in ("VARIANTS", "CLOSE", "EXPLAIN", "RECOMMEND"):
            rec_block = build_recommendation_block(
                self.memory.customer_profile,
                self.store.metadata,
                self.store.sales_brief,
            )
            if rec_block and "cannot be estimated" in rec_block:
                recommendation_block = (
                    f"\nCALCULATED NUMBERS FOR THIS CUSTOMER:\n{rec_block}\n"
                    f"\n⚠ PREMIUM FIGURES UNAVAILABLE: No rate tables in this document.\n"
                    f"Do NOT invent a premium. If asked, say: 'The exact figure for your age requires "
                    f"a quote directly from {self.store.metadata.get('company_name', 'the insurer')}.'\n"
                )
            elif rec_block:
                recommendation_block = f"\nCALCULATED NUMBERS FOR THIS CUSTOMER:\n{rec_block}\n"

            # Also inject the stored gap as a reminder at VARIANTS/CLOSE
            if self.memory.intelligence.gap_lakh:
                from gap_engine import _fmt_lakh
                recommendation_block += (
                    f"\nCUSTOMER PROTECTION GAP (computed at GAP_CALC): "
                    f"{_fmt_lakh(self.memory.intelligence.gap_lakh)}\n"
                    f"Use this as the basis for your cover recommendation and assumptive close.\n"
                )

            # Full deterministic quote at CLOSE if document structure available
            if self.memory.stage == "CLOSE" and self.store.structure:
                try:
                    cover_rec = recommend_cover(self.memory.customer_profile)
                    if cover_rec:
                        freq = self.memory.customer_profile.payment_frequency or "annual"
                        quote = generate_quote(
                            self.memory.customer_profile,
                            cover_rec.cover_lakh,
                            self.store.structure,
                        )
                        policy_quote = "\n" + quote_to_prompt_block(quote, freq) + "\n"
                except (QuoteError, Exception):
                    pass

        # ── EXPLAIN: savings plans topic tracker ────────────────────────────
        if self.memory.stage == "EXPLAIN" and not self.memory.explain_topics:
            plan_type = self.store.metadata.get("plan_type", "other")
            self.memory.explain_topics = choose_explain_topics(
                plan_type, self.memory.customer_profile
            )

        explain_subtopic_line = ""
        if self.memory.stage == "EXPLAIN" and self.memory.explain_topics:
            idx = min(self.memory.explain_subtopic_index, len(self.memory.explain_topics) - 1)
            topic = self.memory.explain_topics[idx].replace("_", " ").title()
            remaining = self.memory.explain_topics[idx + 1:]
            remaining_str = (
                " | Next: " + ", ".join(t.replace("_", " ") for t in remaining)
                if remaining else " | Final topic"
            )
            explain_subtopic_line = (
                f"EXPLAIN TOPIC NOW: {topic} "
                f"(topic {idx + 1} of {len(self.memory.explain_topics)}{remaining_str})\n"
            )

        # ── Close substage ──────────────────────────────────────────────────
        close_substage_line = ""
        if self.memory.stage == "CLOSE":
            sub = self.memory.close_substage
            close_substage_line = f"CLOSE SUBSTAGE: {sub}\n"

        from prompts import CLOSE_SUBSTAGE_INTENTS
        stage_intent = STAGE_INTENTS.get(self.memory.stage, "")
        if self.memory.stage == "CLOSE":
            stage_intent = CLOSE_SUBSTAGE_INTENTS.get(self.memory.close_substage, stage_intent)

        # ── Deflection playbook ─────────────────────────────────────────────
        active_deflection = (
            DEFLECTION_PLAYBOOK
            if self.memory.stage in ("VARIANTS", "EXPLAIN", "RECOMMEND", "OBJECTIONS", "CLOSE")
            else ""
        )

        # ── Combined context blocks ─────────────────────────────────────────
        # Merge gap_block into recommendation_block area for prompt clarity
        if gap_block:
            recommendation_block = gap_block + recommendation_block

        system = MAIN_SYSTEM_PROMPT.format(
            name=self.character["name"],
            persona=self.character["persona"],
            style_guide=self.character["style_guide"],
            emotional_guide=self.character["emotional_guide"],
            sales_brief=brief,
            language_name=language_display_name(self.memory.detected_language),
            document_context=raw_context,
            customer_profile=self.memory.customer_profile.summary(),
            missing_fields_line=missing_fields_line,
            memory_summary=self.memory.memory_summary(),
            risk_narrative=risk_narrative,
            recommendation_block=recommendation_block,
            stage=self.memory.stage,
            explain_subtopic_line=explain_subtopic_line,
            close_substage_line=close_substage_line,
            stage_intent=stage_intent,
            voice_rules=VOICE_RULES,
            advisor_rules=ADVISOR_RULES,
            deflection_playbook=active_deflection,
            meta_tag_instruction=META_TAG_INSTRUCTION,
            policy_quote=policy_quote,
        )

        MAX_HISTORY_TURNS = 6
        relevant_log = self.memory.turn_log[-(MAX_HISTORY_TURNS * 2):]
        history: list[dict] = []
        for entry in relevant_log:
            if entry["role"] in ("user", "assistant"):
                history.append({"role": entry["role"], "content": entry["text"]})

        # Current user turn
        history.append({"role": "user", "content": user_text})

        return [{"role": "system", "content": system}] + history
