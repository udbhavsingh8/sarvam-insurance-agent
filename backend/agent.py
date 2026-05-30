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
from prompts import ADVISOR_RULES, DEFLECTION_PLAYBOOK, MAIN_SYSTEM_PROMPT, META_TAG_INSTRUCTION, OPENER_PROMPT, STAGE_INTENTS, VOICE_RULES, language_display_name
from rag import DocumentStore

_FALLBACK = "I'm having a connection issue right now. Could you give me a moment and try again?"


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
        Generate a contextual opening line using the product document metadata.
        Makes one lightweight LLM call — result is not cached (session is new each time).
        Falls back to a document-aware template if the LLM call fails.
        """
        meta = self.store.metadata
        plan_name = meta.get("plan_name", "this plan")
        company_name = meta.get("company_name", "")
        one_line_pitch = meta.get("one_line_pitch", "it provides financial protection for you and your family")
        language_name = language_display_name(self.memory.detected_language)

        prompt_text = OPENER_PROMPT.format(
            name=self.character["name"],
            persona=self.character["persona"],
            style_guide=self.character["style_guide"],
            language_name=language_name,
            plan_name=plan_name,
            company_name=company_name if company_name else "the insurer",
            one_line_pitch=one_line_pitch,
        )

        try:
            raw = self._llm.complete([
                {"role": "system", "content": prompt_text},
                {"role": "user", "content": "start"},
            ])
            return raw.strip()
        except Exception:
            # Fallback: build a simple but still contextual opener from metadata
            company_part = f" from {company_name}" if company_name else ""
            return (
                f"Hi, I'm {self.character['name']}. "
                f"I'm here to talk to you about {plan_name}{company_part} — {one_line_pitch}. "
                f"Have you come across this plan before, or would you like me to give you a quick overview?"
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

        self.memory.turn_count += 1
        self.memory.log_turn("user", user_text)
        self.memory.log_turn("assistant", clean)

        if analysis and not llm_error:
            apply_analysis(self.memory, analysis, user_text)

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
        self.memory.turn_count += 1
        self.memory.log_turn("user", user_text)
        self.memory.log_turn("assistant", clean)

        if analysis and not llm_error:
            apply_analysis(self.memory, analysis, user_text)

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
        system = MAIN_SYSTEM_PROMPT.format(
            name=self.character["name"],
            persona=self.character["persona"],
            style_guide=self.character["style_guide"],
            emotional_guide=self.character["emotional_guide"],
            language_name=language_display_name(self.memory.detected_language),
            document_context=self.store.get_context(user_text),
            memory_summary=self.memory.memory_summary(),
            stage=self.memory.stage,
            stage_intent=STAGE_INTENTS.get(self.memory.stage, ""),
            voice_rules=VOICE_RULES,
            advisor_rules=ADVISOR_RULES,
            deflection_playbook=DEFLECTION_PLAYBOOK,
            meta_tag_instruction=META_TAG_INSTRUCTION,
        )

        # Build history from turn_log (user/assistant pairs only), capped to last 20 turns
        MAX_HISTORY_TURNS = 20
        relevant_log = self.memory.turn_log[-(MAX_HISTORY_TURNS * 2):]
        history: list[dict] = []
        for entry in relevant_log:
            if entry["role"] in ("user", "assistant"):
                history.append({"role": entry["role"], "content": entry["text"]})

        # Current user turn
        history.append({"role": "user", "content": user_text})

        return [{"role": "system", "content": system}] + history
