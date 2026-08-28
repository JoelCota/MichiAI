"""The thinking loop: prompt -> model -> (tools -> model)* -> spoken reply."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable

from ..llm.base import Reply
from ..logging_setup import get_logger
from ..tts.speaker import split_sentences
from .history import History

log = get_logger("brain")

MAX_TOOL_ROUNDS = 5
SUMMARY_MAX_CHARS = 300


class Brain:
    def __init__(self, cfg, provider, tools):
        self.cfg = cfg
        self.provider = provider
        self.tools = tools
        self.history = History(int(cfg.get("assistant.max_history_turns", 12)))
        self.name = cfg.get("assistant.name", "Michi")
        self.streaming = bool(cfg.get("assistant.streaming", True))
        self.summarize_history = bool(cfg.get("assistant.history_summary", True))
        self._summarizing = False

    # -- prompt ------------------------------------------------------------
    def system_prompt(self) -> str:
        persona = (self.cfg.get("assistant.persona") or "").strip()
        context = [
            persona,
            "",
            f"Current date and time: {datetime.now():%A %d %B %Y, %H:%M}.",
            "You are running on Windows.",
        ]
        if self.history.summary:
            context.append(f"Earlier in this conversation: {self.history.summary}")
        if self.tools.names():
            context.append(
                "When the user asks you to DO something on the computer, call the "
                "matching tool instead of describing the steps. After a tool runs, "
                "confirm the result in one short spoken sentence. When you decide to "
                "call a tool, do it immediately — say nothing (or at most a two-word "
                "acknowledgment) before calling it, and never state a result before "
                "the tool has actually run."
            )
        return "\n".join(part for part in context if part is not None).strip()

    # -- one model call ----------------------------------------------------
    def _ask(self, on_delta: Callable[[str], None] | None) -> Reply:
        messages = self.history.snapshot()
        system = self.system_prompt()
        specs = self.tools.specs()

        use_stream = bool(on_delta) and self.streaming and self.provider.supports_streaming
        if not use_stream:
            return self.provider.chat(messages=messages, system=system, tools=specs)

        # Stream sentence by sentence: complete sentences are handed over as they
        # form, but the trailing (possibly incomplete) sentence is held back. If the
        # round ends in a tool call, that held-back text is discarded instead of
        # being spoken — otherwise Michi narrates results before the tool has run.
        buffer = ""
        final: Reply | None = None
        for chunk in self.provider.chat_stream(messages=messages, system=system, tools=specs):
            if chunk.is_final:
                final = chunk.reply
                break
            if not chunk.text:
                continue
            buffer += chunk.text
            sentences = split_sentences(buffer)
            if len(sentences) > 1:
                for sentence in sentences[:-1]:
                    on_delta(sentence)
                buffer = sentences[-1]

        if final is None:
            return Reply()
        if final.wants_tools:
            if buffer.strip():
                log.debug("suppressed %d chars of pre-tool text", len(buffer.strip()))
        elif buffer.strip():
            on_delta(buffer)
        return final

    # -- main --------------------------------------------------------------
    def respond(self, user_text: str, on_delta: Callable[[str], None] | None = None) -> str:
        """Answer `user_text`. If `on_delta` is given and the provider supports it,
        text is handed over as it arrives so speech can start early."""
        self.history.add_user(user_text)
        dropped = self.history.trim()
        if dropped and self.summarize_history and not self._summarizing:
            self._summarizing = True
            threading.Thread(
                target=self._run_summary, args=(dropped,), daemon=True
            ).start()

        for round_number in range(MAX_TOOL_ROUNDS):
            try:
                reply = self._ask(on_delta)
            except Exception as exc:
                log.exception("Provider call failed")
                self.history.messages.pop()  # don't keep a turn we never answered
                return f"I couldn't reach the model. {type(exc).__name__}."

            if not reply.wants_tools:
                text = reply.text or "Sorry, I didn't catch that."
                self.history.add_assistant(text)
                return text

            self.history.add_assistant(reply.text, reply.tool_calls)
            for call in reply.tool_calls:
                log.info("tool -> %s(%s)", call.name, call.arguments or {})
                result = self.tools.call(call.name, call.arguments)
                log.debug("tool <- %s", result)
                self.history.add_tool_result(call.id, call.name, result)

            log.debug("tool round %d complete", round_number + 1)

        return "That took too many steps, so I stopped."

    def reset(self) -> None:
        self.history.clear()

    # -- rolling summary ----------------------------------------------------
    def _run_summary(self, dropped: list[dict]) -> None:
        try:
            text = self._summarize(dropped)
            if text:
                self.history.set_summary(text)
        except Exception:
            log.debug("History summarisation failed", exc_info=True)
        finally:
            self._summarizing = False

    def _summarize(self, dropped: list[dict]) -> str:
        """Compress dropped turns into one short line, so trimmed context is not lost."""
        lines = []
        for message in dropped:
            content = str(message.get("content", "") or "").strip()
            if not content:
                continue
            role = str(message.get("role", ""))
            lines.append(f"{role}: {content[:400]}")
        if not lines:
            return ""
        transcript = "\n".join(lines)
        prompt = (
            "Condense this earlier part of a conversation into one very short line "
            "(under 10 words, plain text, no labels or quotes).\n\n" + transcript
        )
        reply = self.provider.chat(messages=[{"role": "user", "content": prompt}])
        return (reply.text or "").strip()[:SUMMARY_MAX_CHARS]
