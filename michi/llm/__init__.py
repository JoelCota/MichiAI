"""LLM provider registry — maps config `type:` values to adapter classes."""

from __future__ import annotations

from ..config import Config, ConfigError, _find_missing_env
from ..logging_setup import get_logger
from .base import LLMProvider, Reply, StreamChunk, ToolCall, ToolSpec

log = get_logger("llm")

__all__ = [
    "LLMProvider",
    "Reply",
    "StreamChunk",
    "ToolCall",
    "ToolSpec",
    "create_provider",
    "PROVIDER_TYPES",
]

PROVIDER_TYPES: dict[str, str] = {
    "anthropic": "michi.llm.anthropic_provider:AnthropicProvider",
    "openai_compat": "michi.llm.openai_compat:OpenAICompatProvider",
    # Aliases so obvious config values just work.
    "claude": "michi.llm.anthropic_provider:AnthropicProvider",
    "openai": "michi.llm.openai_compat:OpenAICompatProvider",
    "ollama": "michi.llm.openai_compat:OpenAICompatProvider",
    "groq": "michi.llm.openai_compat:OpenAICompatProvider",
    "opencode": "michi.llm.openai_compat:OpenAICompatProvider",
}


def _import(target: str):
    import importlib

    module_name, class_name = target.split(":")
    return getattr(importlib.import_module(module_name), class_name)


def _build_provider(name: str, settings: dict) -> LLMProvider:
    ptype = str(settings["type"]).lower()
    if ptype not in PROVIDER_TYPES:
        raise ConfigError(
            f"Provider '{name}' has unknown type '{ptype}'. "
            f"Known types: {', '.join(sorted(set(PROVIDER_TYPES)))}"
        )
    provider = _import(PROVIDER_TYPES[ptype])(settings)
    provider.name = name
    return provider


def create_provider(cfg: Config) -> LLMProvider:
    """Build the provider selected by `llm.active` in config.yaml, plus any
    `llm.fallback` chain to fail over to."""
    name, settings = cfg.active_provider()
    primary = _build_provider(name, settings)

    fallback_names = [str(n) for n in (cfg.get("llm.fallback") or [])]
    chain = [primary]
    providers = cfg.section("llm.providers")
    for fname in fallback_names:
        if fname == name:
            continue
        if fname not in providers:
            log.warning("Fallback provider '%s' is not defined — skipping.", fname)
            continue
        fsettings = dict(providers[fname])
        missing = _find_missing_env(fsettings)
        if missing:
            log.warning(
                "Fallback provider '%s' needs env var %s — skipping.", fname, missing
            )
            continue
        try:
            chain.append(_build_provider(fname, fsettings))
        except ConfigError as exc:
            log.warning("Fallback provider '%s' skipped: %s", fname, exc)

    if len(chain) == 1:
        return primary

    from .fallback import FallbackProvider

    log.info("Fallback chain: %s", " -> ".join(p.describe() for p in chain))
    return FallbackProvider(chain)
