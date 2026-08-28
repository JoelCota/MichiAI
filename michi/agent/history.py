"""Rolling conversation memory."""

from __future__ import annotations

from ..llm.base import ToolCall


class History:
    """Keeps the last N user/assistant turns, never splitting a tool sequence."""

    def __init__(self, max_turns: int = 12):
        self.max_turns = max_turns
        self.messages: list[dict] = []
        self.summary: str = ""

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text: str, tool_calls: list[ToolCall] | None = None) -> None:
        message: dict = {"role": "assistant", "content": text}
        if tool_calls:
            message["tool_calls"] = tool_calls
        self.messages.append(message)

    def add_tool_result(self, call_id: str, name: str, content: str) -> None:
        self.messages.append(
            {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}
        )

    def trim(self) -> list[dict]:
        """Drop the oldest complete turns, keeping tool call/result pairs together.

        Returns the dropped messages so the caller can compress them into a
        rolling summary instead of losing the context outright.
        """
        user_indices = [i for i, m in enumerate(self.messages) if m["role"] == "user"
                        and "tool_call_id" not in m]
        if len(user_indices) <= self.max_turns:
            return []
        cut = user_indices[len(user_indices) - self.max_turns]
        dropped, self.messages = self.messages[:cut], self.messages[cut:]
        return dropped

    def set_summary(self, text: str) -> None:
        self.summary = (text or "").strip()

    def snapshot(self) -> list[dict]:
        return list(self.messages)

    def clear(self) -> None:
        self.messages.clear()

    def __len__(self) -> int:
        return len(self.messages)
