"""Fallback chain: try providers in order until one answers.

Wrap N providers behind one interface. When the primary fails (network error,
rate limit, provider outage), the next one gets the same request automatically,
so Michi degrades instead of going silent.
"""

from __future__ import annotations

from typing import Iterator

from ..logging_setup import get_logger
from .base import LLMProvider, Reply, StreamChunk, ToolSpec

log = get_logger("llm")


class FallbackProvider(LLMProvider):
    name = "fallback"
    supports_streaming = True

    def __init__(self, chain: list[LLMProvider]):
        super().__init__(chain[0].settings)
        self.chain = chain
        self.model = chain[0].model
        self.supports_streaming = any(p.supports_streaming for p in chain)

    def describe(self) -> str:
        return " -> ".join(p.describe() for p in self.chain)

    def chat(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[ToolSpec] | None = None,
    ) -> Reply:
        last_error: Exception | None = None
        for provider in self.chain:
            try:
                return provider.chat(messages=messages, system=system, tools=tools)
            except Exception as exc:
                last_error = exc
                log.warning(
                    "Provider %s failed (%s) — falling through to the next.",
                    provider.describe(), exc,
                )
        raise RuntimeError(f"All providers failed: {last_error}") from last_error

    def chat_stream(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[ToolSpec] | None = None,
    ) -> Iterator[StreamChunk]:
        last_error: Exception | None = None
        for provider in self.chain:
            spoke_some_text = False
            try:
                for chunk in provider.chat_stream(messages=messages, system=system, tools=tools):
                    if chunk.is_final:
                        yield chunk
                        return
                    if chunk.text:
                        spoke_some_text = True
                    yield chunk
                log.warning(
                    "Provider %s ended its stream without a reply — falling through.",
                    provider.describe(),
                )
            except Exception as exc:
                last_error = exc
                log.warning(
                    "Provider %s failed mid-stream (%s) — switching.",
                    provider.describe(), exc,
                )
                if spoke_some_text:
                    log.warning("Some partial text was already spoken before the switch.")
            # fall through to the next provider
        raise RuntimeError(f"All providers failed: {last_error}") from last_error
