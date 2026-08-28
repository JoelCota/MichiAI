"""Claude API adapter (type: anthropic)."""

from __future__ import annotations

import json
from typing import Any, Iterator

from .base import LLMProvider, Reply, StreamChunk, ToolCall, ToolSpec


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    supports_streaming = True

    def __init__(self, settings: dict):
        super().__init__(settings)
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "The 'anthropic' package is not installed. Run: pip install anthropic"
            ) from exc

        api_key = settings.get("api_key")
        if not api_key or str(api_key).startswith("<<MISSING"):
            raise RuntimeError(
                "No Anthropic API key. Set ANTHROPIC_API_KEY in your .env file."
            )
        kwargs: dict[str, Any] = {"api_key": api_key}
        if settings.get("base_url"):
            kwargs["base_url"] = settings["base_url"]
        self.client = anthropic.Anthropic(**kwargs)

    # -- conversion --------------------------------------------------------
    @staticmethod
    def _to_anthropic(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for msg in messages:
            role = msg["role"]

            if role == "tool":
                # Claude carries tool results as a user-role tool_result block.
                block = {
                    "type": "tool_result",
                    "tool_use_id": msg["tool_call_id"],
                    "content": str(msg.get("content", "")),
                }
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
                continue

            if role == "assistant" and msg.get("tool_calls"):
                blocks: list[dict] = []
                if msg.get("content"):
                    blocks.append({"type": "text", "text": msg["content"]})
                for call in msg["tool_calls"]:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": call.arguments or {},
                        }
                    )
                out.append({"role": "assistant", "content": blocks})
                continue

            out.append({"role": role, "content": msg.get("content", "")})
        return out

    @staticmethod
    def _tools(tools: list[ToolSpec] | None) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in (tools or [])
        ]

    @staticmethod
    def _to_reply(response) -> Reply:
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                args = block.input
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                calls.append(ToolCall(id=block.id, name=block.name, arguments=args or {}))
        return Reply(text="".join(text_parts).strip(), tool_calls=calls)

    def _request_kwargs(
        self, messages: list[dict], system: str, tools: list[ToolSpec] | None
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": self._to_anthropic(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._tools(tools)
        return kwargs

    # -- main --------------------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[ToolSpec] | None = None,
    ) -> Reply:
        response = self.client.messages.create(**self._request_kwargs(messages, system, tools))
        return self._to_reply(response)

    def chat_stream(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[ToolSpec] | None = None,
    ) -> Iterator[StreamChunk]:
        kwargs = self._request_kwargs(messages, system, tools)
        with self.client.messages.stream(**kwargs) as stream:
            for event in stream:
                if (
                    getattr(event, "type", "") == "content_block_delta"
                    and getattr(event.delta, "type", "") == "text_delta"
                ):
                    yield StreamChunk(text=event.delta.text)
            yield StreamChunk(reply=self._to_reply(stream.get_final_message()))
