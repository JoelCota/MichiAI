"""OpenAI-compatible adapter (type: openai_compat).

One adapter, many providers — anything that speaks /v1/chat/completions:
OpenCode Zen, OpenAI, Groq, OpenRouter, Together, DeepSeek, Ollama, LM Studio.
Adding a new one is three lines of YAML, no code.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterator

from .base import LLMProvider, Reply, StreamChunk, ToolCall, ToolSpec


class OpenAICompatProvider(LLMProvider):
    name = "openai_compat"
    supports_streaming = True

    def __init__(self, settings: dict):
        super().__init__(settings)
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "The 'openai' package is not installed. Run: pip install openai"
            ) from exc

        api_key = settings.get("api_key") or "not-needed"
        if str(api_key).startswith("<<MISSING"):
            raise RuntimeError(
                "This provider needs an API key that isn't set. Check your .env file."
            )
        kwargs: dict[str, Any] = {"api_key": str(api_key)}
        if settings.get("base_url"):
            kwargs["base_url"] = settings["base_url"].rstrip("/")
        self.client = OpenAI(**kwargs)

    # -- conversion --------------------------------------------------------
    @staticmethod
    def _to_openai(messages: list[dict], system: str) -> list[dict]:
        out: list[dict] = []
        if system:
            out.append({"role": "system", "content": system})

        for msg in messages:
            role = msg["role"]

            if role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg["tool_call_id"],
                        "content": str(msg.get("content", "")),
                    }
                )
                continue

            if role == "assistant" and msg.get("tool_calls"):
                out.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or None,
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": json.dumps(call.arguments or {}),
                                },
                            }
                            for call in msg["tool_calls"]
                        ],
                    }
                )
                continue

            out.append({"role": role, "content": msg.get("content", "")})
        return out

    @staticmethod
    def _tools(tools: list[ToolSpec] | None) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in (tools or [])
        ]

    @staticmethod
    def _parse_arguments(raw) -> dict:
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _request_kwargs(
        self, messages: list[dict], system: str, tools: list[ToolSpec] | None
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_openai(messages, system),
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if tools:
            kwargs["tools"] = self._tools(tools)
            kwargs["tool_choice"] = "auto"
        extra = getattr(self, "settings", {}).get("extra_body")
        if extra:
            kwargs["extra_body"] = dict(extra)
        return kwargs

    # -- main --------------------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[ToolSpec] | None = None,
    ) -> Reply:
        response = self.client.chat.completions.create(
            **self._request_kwargs(messages, system, tools)
        )
        message = response.choices[0].message

        calls = [
            ToolCall(
                id=call.id or f"call_{uuid.uuid4().hex[:8]}",
                name=call.function.name,
                arguments=self._parse_arguments(call.function.arguments),
            )
            for call in (getattr(message, "tool_calls", None) or [])
        ]
        return Reply(text=(message.content or "").strip(), tool_calls=calls)

    def chat_stream(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[ToolSpec] | None = None,
    ) -> Iterator[StreamChunk]:
        kwargs = self._request_kwargs(messages, system, tools)
        kwargs["stream"] = True

        text_parts: list[str] = []
        # Tool calls arrive fragmented across chunks, keyed by index.
        partial: dict[int, dict] = {}

        for chunk in self.client.chat.completions.create(**kwargs):
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue

            if getattr(delta, "content", None):
                text_parts.append(delta.content)
                yield StreamChunk(text=delta.content)

            for fragment in (getattr(delta, "tool_calls", None) or []):
                index = fragment.index or 0
                slot = partial.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if fragment.id:
                    slot["id"] = fragment.id
                function = getattr(fragment, "function", None)
                if function is not None:
                    if getattr(function, "name", None):
                        slot["name"] = function.name
                    if getattr(function, "arguments", None):
                        slot["arguments"] += function.arguments

        calls = [
            ToolCall(
                id=slot["id"] or f"call_{uuid.uuid4().hex[:8]}",
                name=slot["name"],
                arguments=self._parse_arguments(slot["arguments"]),
            )
            for _, slot in sorted(partial.items())
            if slot["name"]
        ]
        yield StreamChunk(reply=Reply(text="".join(text_parts).strip(), tool_calls=calls))
