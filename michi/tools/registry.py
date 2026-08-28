"""Tool registry.

Adding a capability to Michi is one decorated function:

    @tool(group="system", description="Set the volume to a percentage.",
          parameters={"level": {"type": "integer", "description": "0-100"}},
          required=["level"])
    def set_volume(level: int) -> str:
        ...
        return "Volume set to 40 percent."

Return a short string — it goes back to the model as the tool result, and the
model turns it into something spoken.
"""

from __future__ import annotations

import importlib
import inspect
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from ..llm.base import ToolSpec
from ..logging_setup import get_logger

log = get_logger("tools")

GROUP_MODULES = {
    "basics": "michi.tools.basics",
    "system": "michi.tools.system",
    "apps": "michi.tools.apps",
    "web": "michi.tools.web",
    "clipboard": "michi.tools.clipboard",
    "shell": "michi.tools.shell",
}


@dataclass
class ToolMeta:
    group: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    confirm: bool = False
    name: str = ""


def tool(
    group: str,
    description: str,
    parameters: dict[str, Any] | None = None,
    required: list[str] | None = None,
    confirm: bool = False,
    name: str = "",
) -> Callable:
    def decorator(fn: Callable) -> Callable:
        fn._michi_tool = ToolMeta(  # type: ignore[attr-defined]
            group=group,
            description=description,
            parameters=parameters or {},
            required=required or [],
            confirm=confirm,
            name=name or fn.__name__,
        )
        return fn

    return decorator


@dataclass
class RegisteredTool:
    meta: ToolMeta
    func: Callable

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.meta.name,
            description=self.meta.description,
            parameters={
                "type": "object",
                "properties": self.meta.parameters,
                "required": self.meta.required,
            },
        )


class ToolRegistry:
    def __init__(self, cfg=None, confirm_callback: Callable[[str], bool] | None = None):
        self.cfg = cfg
        self.tools: dict[str, RegisteredTool] = {}
        self.confirm_callback = confirm_callback
        self._confirm_names: set[str] = set(
            (cfg.get("tools.confirm_before", []) if cfg else []) or []
        )
        self.max_result_chars = int(cfg.get("tools.max_result_chars", 2000) if cfg else 2000)
        self.rate_limits = (cfg.get("tools.rate_limits", {}) if cfg else {}) or {}
        self._call_times: dict[str, deque[float]] = {}

    # -- loading -----------------------------------------------------------
    def load_groups(self, groups: list[str]) -> None:
        for group in groups:
            module_path = GROUP_MODULES.get(group)
            if not module_path:
                log.warning("Unknown tool group '%s' in config — skipping.", group)
                continue
            try:
                module = importlib.import_module(module_path)
            except Exception as exc:
                log.warning("Tool group '%s' failed to load (%s) — skipping.", group, exc)
                continue
            self._scan(module, group)

    def _scan(self, module, group: str) -> None:
        loaded = 0
        for _, obj in inspect.getmembers(module, inspect.isfunction):
            meta: ToolMeta | None = getattr(obj, "_michi_tool", None)
            if meta is None or meta.group != group:
                continue
            if meta.name in self._confirm_names:
                meta.confirm = True
            self.tools[meta.name] = RegisteredTool(meta=meta, func=obj)
            loaded += 1
        log.debug("Tool group '%s': %d tool(s).", group, loaded)

    # -- use ---------------------------------------------------------------
    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self.tools.values()]

    def names(self) -> list[str]:
        return sorted(self.tools)

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        registered = self.tools.get(name)
        if registered is None:
            return f"Error: no tool named '{name}'."

        if registered.meta.confirm and self.confirm_callback is not None:
            if not self.confirm_callback(name):
                return "The user declined that action."

        limited = self._check_rate_limit(name)
        if limited is not None:
            return limited

        try:
            signature = inspect.signature(registered.func)
            unknown = set(arguments or {}) - set(signature.parameters) - {"cfg"}
            if unknown:
                log.warning(
                    "Tool '%s' got unknown argument(s) %s — ignoring.",
                    name, ", ".join(sorted(unknown)),
                )
            accepted = {
                k: v for k, v in (arguments or {}).items() if k in signature.parameters
            }
            if "cfg" in signature.parameters and "cfg" not in accepted:
                accepted["cfg"] = self.cfg
            result = registered.func(**accepted)
            text = str(result) if result is not None else "Done."
        except Exception as exc:  # tools must never crash the assistant
            log.exception("Tool '%s' failed", name)
            return f"Error running {name}: {exc}"
        return self._truncate(text)

    # -- guards ------------------------------------------------------------
    def _truncate(self, text: str) -> str:
        """Cap huge tool results so one bad call can't blow up the token budget."""
        if len(text) <= self.max_result_chars:
            return text
        return text[: self.max_result_chars] + (
            f"\n[truncated — {len(text)} chars total]"
        )

    def _check_rate_limit(self, name: str) -> str | None:
        """Return an error message when a tool exceeds its configured rate limit."""
        limits = self.rate_limits.get(name)
        if not limits:
            return None
        per_minute = int(limits.get("per_minute", 0) or 0)
        if per_minute <= 0:
            return None
        now = time.monotonic()
        times = self._call_times.setdefault(name, deque())
        while times and now - times[0] > 60:
            times.popleft()
        if len(times) >= per_minute:
            log.warning("Tool '%s' rate-limited (%d/minute).", name, per_minute)
            return (
                f"Error: {name} is limited to {per_minute} calls per minute — "
                "wait a moment and try again."
            )
        times.append(now)
        return None


def build_registry(cfg, confirm_callback=None) -> ToolRegistry:
    registry = ToolRegistry(cfg, confirm_callback)
    registry.load_groups(cfg.get("tools.enabled", []) or [])
    log.info("Tools available: %s", ", ".join(registry.names()) or "(none)")
    return registry
