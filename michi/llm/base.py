"""Provider-neutral chat interface.

Everything above this layer (agent loop, tools, history) speaks ONLY these types.
Each provider adapter converts them to and from its own wire format, which is why
switching `llm.active` in config.yaml is enough to change brains.

Internal message shapes
-----------------------
    {"role": "user",      "content": "what time is it"}
    {"role": "assistant", "content": "",  "tool_calls": [ToolCall, ...]}
    {"role": "tool",      "tool_call_id": "...", "name": "get_time", "content": "14:02"}
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object


@dataclass
class Reply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class StreamChunk:
    """One piece of a streaming response.

    Text chunks carry `text` and leave `reply` as None. The final chunk carries the
    assembled `reply` (including any tool calls) and no text.
    """

    text: str = ""
    reply: Reply | None = None

    @property
    def is_final(self) -> bool:
        return self.reply is not None


class LLMProvider(ABC):
    """One method that matters. Implementations must not raise on empty tool lists."""

    name: str = "provider"
    supports_streaming: bool = False

    def __init__(self, settings: dict):
        self.settings = settings
        self.model = settings.get("model", "")
        self.max_tokens = int(settings.get("max_tokens", 1024))
        self.temperature = float(settings.get("temperature", 0.7))

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[ToolSpec] | None = None,
    ) -> Reply:
        """Send the conversation, return the assistant's reply."""

    def chat_stream(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[ToolSpec] | None = None,
    ) -> Iterator[StreamChunk]:
        """Stream the reply. The default just wraps `chat` in a single final chunk,
        so a provider that can't stream still works everywhere streaming is used."""
        yield StreamChunk(reply=self.chat(messages, system, tools))

    def describe(self) -> str:
        return f"{self.name}:{self.model}"
