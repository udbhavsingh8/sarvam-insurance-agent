"""
AgentSession — one session of the Insurance Sales Voice Agent.

Wires together: LLMClient, DocumentStore, SessionMemory, CharacterRegistry,
ConversationAnalyzer, and metrics logging.
"""

from __future__ import annotations

import time
import uuid
from typing import Iterator

from characters import CHARACTERS, SUPPORTED_LANGUAGES
from conversation_analyzer import apply_analysis, parse_meta_tag
from errors import LLMError
from llm import LLMClient
from memory import SessionMemory
from metrics import TurnMetrics, log_session, log_turn
from profile_extractor import extract_profile_fields
from prompts import ADVISOR_RULES, DEFLECTION_PLAYBOOK, MAIN_SYSTEM_PROMPT, META_TAG_INSTRUCTION, OPENER_PROMPT, STAGE_INTENTS, VOICE_RULES, language_display_name
from recommendation import build_recommendation_block
from rag import DocumentStore
from cover_engine import recommend_cover
from quote_engine import generate_quote, quote_to_prompt_block, QuoteError

_FALLBACK = "I'm having a connection issue right now. Could you give me a moment and try again?"


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
    Python-controlled stage gating. Runs after every turn.

    The LLM requests stage transitions via its META tag, but this function
    has the final say. It prevents two classes of failure:
      1. LLM stays stuck (never emits a transition tag) → Python advances when
         objective conditions are met.
      2. LLM advances too early → Python blocks premature transitions.

    Rules:
      INTRODUCE → PROFILE: Python escape after 2 turns (I-8: prevents stuck INTRODUCE).
      PROFILE → EXPLAIN: only when profile.is_sufficient(plan_type) is True.
      PERSONALIZE → EXPLAIN: always after one turn (one-turn bridge).
      EXPLAIN → CLOSE: only when close_readiness >= 70 AND at least 3 EXPLAIN turns.
      CLOSE substages: Python auto-advances SUMMARY→PURCHASE_INTENT and terminal substages.
      HANDLE/QA: return to previous stage after 1 turn.
    """
    stage = memory.stage

    # I-8: Escape INTRODUCE if LLM never emits a transition tag after 2 turns.
    if stage == "INTRODUCE" and memory.turn_in_stage >= 2:
        memory.previous_stage = stage
        memory.stage = "PROFILE"
        memory.turn_in_stage = 0
        return

    if stage == "PROFILE" and memory.customer_profile.is_sufficient(plan_type):
        memory.previous_stage = stage
        memory.stage = "NEED_DEVELOPMENT"
        memory.turn_in_stage = 0
        return

    # NEED_DEVELOPMENT: Python escape after 2 turns — prevents LLM from getting stuck
    if stage == "NEED_DEVELOPMENT" and memory.turn_in_stage >= 2:
        memory.previous_stage = stage
        memory.stage = "EXPLAIN"
        memory.turn_in_stage = 0
        return

    if stage == "PERSONALIZE":
        memory.previous_stage = stage
        memory.stage = "NEED_DEVELOPMENT"
        memory.turn_in_stage = 0
        return

    # RECOMMENDATION: Python auto-advance to CLOSE after 1 turn
    if stage == "RECOMMENDATION" and memory.turn_in_stage >= 1:
        memory.previous_stage = stage
        memory.stage = "CLOSE"
        memory.close_substage = "PURCHASE_INTENT"  # skip SUMMARY — recommendation IS the summary
        memory.turn_in_stage = 0
        return

    if stage in ("HANDLE", "QUESTION_ANSWER"):
        # Force return to previous stage after 1 turn — never let QA/HANDLE become a trap.
        if memory.turn_in_stage >= 1:
            return_to = memory.return_to_stage or memory.previous_stage or "EXPLAIN"
            memory.previous_stage = stage
            memory.stage = return_to
            memory.return_to_stage = None
            memory.turn_in_stage = 0
        return

    if stage == "EXPLAIN":
        intel = memory.intelligence
        topics = memory.explain_topics
        on_last_topic = (
            not topics or
            memory.explain_subtopic_index >= len(topics) - 1
        )
        # Advance to RECOMMENDATION when:
        # (a) All topics covered and at least 1 turn on the final topic, OR
        # (b) Customer is very engaged (close_readiness >= 50) and 2+ turns done, OR
        # (c) Hard escape after 6 EXPLAIN turns regardless (prevents infinite loop)
        if (on_last_topic and memory.turn_in_stage >= 1) or \
           (intel.close_readiness >= 50 and memory.turn_in_stage >= 2) or \
           (memory.turn_in_stage >= 6):
            memory.previous_stage = stage
            memory.stage = "RECOMMENDATION"
            memory.turn_in_stage = 0
            return

    if stage == "CLOSE":
        _auto_advance_close_substage(memory)


def _auto_advance_close_substage(memory: SessionMemory) -> None:
    """Python-controlled close substage gating."""
    sub = memory.close_substage

    # SUMMARY: auto-advance to PURCHASE_INTENT after 1 turn (LLM cannot skip)
    if sub == "SUMMARY" and memory.turn_in_stage >= 1:
        memory.close_substage = "PURCHASE_INTENT"
        memory.turn_in_stage = 0
        return

    # PROCEED: auto-advance to CLOSED after 1 turn (onboarding message delivered)
    if sub == "PROCEED" and memory.turn_in_stage >= 1:
        memory.close_substage = "CLOSED"
        memory.turn_in_stage = 0
        return

    # FEEDBACK: LLM signals CLOSED via META after collecting reason.
    # Safety cap: force CLOSED after 3 turns to prevent infinite feedback loop.
    if sub == "FEEDBACK" and memory.turn_in_stage >= 3:
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
            raw = self._llm.complete(messages)
        except LLMError as exc:
            raw = _FALLBACK
            llm_error = True
            error_detail = str(exc)
        llm_ms = int((time.time() - t_llm_start) * 1000)

        clean, analysis = parse_meta_tag(raw)

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

        for token in self._llm.stream(messages):
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
        from memory import choose_explain_topics

        # Lazily initialize the dynamic topic list on first EXPLAIN turn.
        # Uses plan_type from document metadata + current customer profile.
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

        # GPT-4o-mini has a 128k context window. Keep limits generous but reasonable.
        BRIEF_CHAR_LIMIT = 3500
        DOC_CONTEXT_CHAR_LIMIT = 1500

        import re as _re

        brief = self.store.sales_brief or "No product profile available."

        # At INTRODUCE, PROFILE, and NEED_DEVELOPMENT strip the PREMIUMS section
        # from the brief entirely. Marketing figures like "₹22/day" live there and
        # the LLM will quote them as customer-specific premiums if it can see them.
        # Calculated numbers are not yet available at these stages, so any premium
        # figure the LLM could cite would be wrong. Remove the temptation.
        if self.memory.stage in ("INTRODUCE", "PROFILE", "NEED_DEVELOPMENT"):
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

        # Missing fields line — injected only at PROFILE stage so the LLM knows
        # exactly what is still needed and cannot go off-script about premiums.
        missing_fields_line = ""
        if self.memory.stage == "PROFILE":
            p = self.memory.customer_profile
            plan_type_for_profile = self.store.metadata.get("plan_type", "other")
            missing: list[str] = []
            if p.age is None:
                missing.append("age")
            if p.smoker is None and plan_type_for_profile in ("term", "other"):
                missing.append("smoker status (yes/no)")
            if p.income_range is None:
                missing.append("annual income")
            if p.dependents is None and p.marital_status is None:
                missing.append("family situation (married / dependents)")
            if p.existing_coverage is None:
                missing.append("existing insurance coverage")
            if missing:
                missing_fields_line = (
                    f"\nSTILL NEEDED FROM CUSTOMER: {', '.join(missing)}.\n"
                    f"Ask ONLY about these fields this turn — naturally, one or two at a time.\n"
                    f"Do NOT discuss premiums, product features, or benefits until all are collected.\n"
                )

        # Risk narrative: deterministic profile → vulnerability story.
        # Injected at all sales-active stages so the LLM always has
        # the customer's specific situation, not just a field list.
        _NARRATIVE_STAGES = ("NEED_DEVELOPMENT", "EXPLAIN", "RECOMMENDATION", "CLOSE", "HANDLE")
        risk_narrative = (
            build_risk_narrative(self.memory.customer_profile)
            if self.memory.stage in _NARRATIVE_STAGES
            else ""
        )

        # Calculated numbers: inject at EXPLAIN, RECOMMENDATION, and CLOSE.
        policy_quote = ""
        if self.memory.stage in ("EXPLAIN", "RECOMMENDATION", "CLOSE"):
            rec_block = build_recommendation_block(
                self.memory.customer_profile,
                self.store.metadata,
                self.store.sales_brief,
            )
            recommendation_block = (
                f"\nCALCULATED NUMBERS FOR THIS CUSTOMER:\n{rec_block}\n"
                if rec_block else ""
            )

            # Full deterministic quote from document structure at RECOMMENDATION and CLOSE.
            if self.memory.stage in ("RECOMMENDATION", "CLOSE") and self.store.structure:
                try:
                    cover_rec = recommend_cover(self.memory.customer_profile)
                    if cover_rec:
                        freq = (
                            self.memory.customer_profile.payment_frequency or "annual"
                        )
                        quote = generate_quote(
                            self.memory.customer_profile,
                            cover_rec.cover_lakh,
                            self.store.structure,
                        )
                        policy_quote = "\n" + quote_to_prompt_block(quote, freq) + "\n"
                except QuoteError:
                    pass
                except Exception:
                    pass
        else:
            recommendation_block = ""

        # Close substage context — drives the exact behavior within CLOSE
        close_substage_line = ""
        if self.memory.stage == "CLOSE":
            sub = self.memory.close_substage
            close_substage_line = f"CLOSE SUBSTAGE: {sub}\n"

        from prompts import CLOSE_SUBSTAGE_INTENTS
        stage_intent = STAGE_INTENTS.get(self.memory.stage, "")
        if self.memory.stage == "CLOSE":
            stage_intent = CLOSE_SUBSTAGE_INTENTS.get(self.memory.close_substage, stage_intent)

        # Deflection playbook: active whenever objections are likely
        active_deflection = (
            DEFLECTION_PLAYBOOK
            if self.memory.stage in ("EXPLAIN", "NEED_DEVELOPMENT", "RECOMMENDATION", "HANDLE")
            else ""
        )

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
