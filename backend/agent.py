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

_FALLBACK = "I'm having a connection issue right now. Could you give me a moment and try again?"


def _auto_advance_stage(memory: SessionMemory) -> None:
    """
    Python-controlled stage gating. Runs after every turn.

    The LLM requests stage transitions via its META tag, but this function
    has the final say. It prevents two classes of failure:
      1. LLM stays stuck (never emits a transition tag) → Python advances when
         objective conditions are met (profile complete, high close readiness).
      2. LLM advances too early → Python blocks premature transitions.

    Rules:
      PROFILE → PERSONALIZE: only when profile.is_sufficient() is True.
      PERSONALIZE → EXPLAIN: always after one turn (it is a one-turn bridge).
      EXPLAIN → CLOSE: only when close_readiness >= 70 AND at least 3 EXPLAIN turns.
      All other transitions (including INTRODUCE→PROFILE, QA, HANDLE) are LLM-driven.
    """
    stage = memory.stage

    if stage == "PROFILE" and memory.customer_profile.is_sufficient():
        memory.previous_stage = stage
        memory.stage = "EXPLAIN"   # skip PERSONALIZE — first EXPLAIN turn opens with profile restatement
        memory.turn_in_stage = 0
        return

    if stage == "PERSONALIZE":
        # Safety: if LLM somehow sets PERSONALIZE, immediately move to EXPLAIN.
        memory.previous_stage = stage
        memory.stage = "EXPLAIN"
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
        if intel.close_readiness >= 70 and memory.turn_in_stage >= 3:
            memory.previous_stage = stage
            memory.stage = "CLOSE"
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
        meta = self.store.metadata
        plan_name = meta.get("plan_name", "this plan")
        company_name = meta.get("company_name", "")
        one_line_pitch = meta.get("one_line_pitch", "provides financial protection for your family")
        name = self.character["name"]

        import re as _re

        def _clean(s: str) -> str:
            # Strip any LLM-generated placeholders like [Name], [Age], [X]
            return _re.sub(r'\[[^\]]{0,40}\]', '', s).strip()

        plan_name = _clean(plan_name)
        company_name = _clean(company_name)
        one_line_pitch = _clean(one_line_pitch)

        company_part = f" from {company_name}" if company_name else ""
        pitch = one_line_pitch.lstrip()
        if pitch.lower().startswith("it "):
            pitch = pitch[3:]

        return (
            f"Hi, this is {name}{company_part}. "
            f"I'm calling to discuss the {plan_name} — a plan that {pitch}. "
            f"Have you come across this plan before, or would you like me to walk you through it quickly?"
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

        _auto_advance_stage(self.memory)

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
        # Extract profile fields from user text (covers the streaming path)
        if user_text:
            self.memory.customer_profile.apply_updates(extract_profile_fields(user_text))
        self.memory.turn_count += 1
        self.memory.log_turn("user", user_text)
        self.memory.log_turn("assistant", clean)

        if analysis and not llm_error:
            apply_analysis(self.memory, analysis, user_text)

        _auto_advance_stage(self.memory)

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

        # sarvam-m context window is 7192 tokens. Budget: ~5800 for system prompt,
        # ~600 for max_tokens output, leaving headroom for history turns.
        # sales_brief is the biggest variable — cap it so the prompt never overflows.
        BRIEF_CHAR_LIMIT = 2000
        DOC_CONTEXT_CHAR_LIMIT = 1000

        brief = self.store.sales_brief or "No product profile available."
        if len(brief) > BRIEF_CHAR_LIMIT:
            brief = brief[:BRIEF_CHAR_LIMIT] + "\n[... product profile truncated for brevity ...]"

        raw_context = self.store.get_context(user_text, top_k=3)
        if len(raw_context) > DOC_CONTEXT_CHAR_LIMIT:
            raw_context = raw_context[:DOC_CONTEXT_CHAR_LIMIT]

        # Recommendation block: inject at EXPLAIN and CLOSE only.
        # Fast arithmetic — no LLM call. Empty string at all other stages.
        if self.memory.stage in ("EXPLAIN", "CLOSE"):
            rec_block = build_recommendation_block(
                self.memory.customer_profile,
                self.store.metadata,
                self.store.sales_brief,
            )
            recommendation_block = (
                f"\nRECOMMENDED NUMBERS FOR THIS CUSTOMER:\n{rec_block}\n"
                if rec_block else ""
            )
        else:
            recommendation_block = ""

        stage_intent = STAGE_INTENTS.get(self.memory.stage, "")
        if self.memory.stage == "CLOSE":
            intent = self.memory.intelligence.buying_intent
            if intent == "hot":
                stage_intent += (
                    "\nBuying intent: HOT — skip soft probing. "
                    "Give the recommendation then ask directly: "
                    "'Shall I walk you through what the application looks like?'"
                )
            elif intent == "warm":
                stage_intent += (
                    "\nBuying intent: WARM — give the recommendation with numbers, "
                    "then ask: 'Would you like me to get you a personalised quote?'"
                )
            else:
                stage_intent += (
                    "\nBuying intent: COLD/UNKNOWN — before the close ask, "
                    "say: 'What is the one thing still holding you back?' "
                    "Address it, then make a single ask."
                )

        # Only inject deflection playbook when objections are likely to arise
        active_deflection = (
            DEFLECTION_PLAYBOOK
            if self.memory.stage in ("EXPLAIN", "CLOSE", "HANDLE")
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
            memory_summary=self.memory.memory_summary(),
            recommendation_block=recommendation_block,
            stage=self.memory.stage,
            explain_subtopic_line=explain_subtopic_line,
            stage_intent=stage_intent,
            voice_rules=VOICE_RULES,
            advisor_rules=ADVISOR_RULES,
            deflection_playbook=active_deflection,
            meta_tag_instruction=META_TAG_INSTRUCTION,
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
