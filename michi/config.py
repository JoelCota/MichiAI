"""Config loading: YAML + ${ENV_VAR} expansion + dotted access."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    pass


def _expand(value: Any) -> Any:
    """Recursively replace ${VAR} / ${VAR:-default} with environment values."""
    if isinstance(value, str):

        def sub(match: re.Match) -> str:
            name, default = match.group(1), match.group(2)
            env = os.environ.get(name)
            if env:
                return env
            if default is not None:
                return default
            # Leave a recognisable marker so validation can report it nicely.
            return f"<<MISSING:{name}>>"

        return _ENV_PATTERN.sub(sub, value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


class Config:
    """Dict wrapper with dotted lookups: cfg.get('llm.providers.claude.model')."""

    def __init__(self, data: dict, path: Path | None = None):
        self.data = data
        self.path = path

    # -- access ------------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def require(self, dotted: str) -> Any:
        value = self.get(dotted, _MISSING)
        if value is _MISSING:
            raise ConfigError(f"config.yaml is missing required key: {dotted}")
        return value

    def section(self, dotted: str) -> dict:
        return self.get(dotted, {}) or {}

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    # -- derived helpers ---------------------------------------------------
    def active_provider(self) -> tuple[str, dict]:
        """Return (name, settings) for the provider selected by llm.active."""
        name = self.require("llm.active")
        providers = self.section("llm.providers")
        if name not in providers:
            available = ", ".join(sorted(providers)) or "(none defined)"
            raise ConfigError(
                f"llm.active is '{name}' but no such provider exists. Available: {available}"
            )
        settings = dict(providers[name])
        missing = _find_missing_env(settings)
        if missing:
            raise ConfigError(
                f"Provider '{name}' needs the environment variable {missing}. "
                f"Add it to your .env file (see .env.example)."
            )
        if "type" not in settings:
            raise ConfigError(f"Provider '{name}' is missing a 'type' (anthropic | openai_compat).")
        return name, settings

    def resolve_path(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else PROJECT_ROOT / p


class _Missing:
    pass


_MISSING = _Missing()


def _find_missing_env(settings: dict) -> str | None:
    for value in settings.values():
        if isinstance(value, str) and value.startswith("<<MISSING:"):
            return value[len("<<MISSING:") : -2]
    return None


def load_config(path: str | Path | None = None) -> Config:
    """Load .env then config.yaml, expanding ${VARS}."""
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:  # dotenv is optional; real env vars still work
        pass

    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    if not cfg_path.exists():
        raise ConfigError(
            f"No config file at {cfg_path}. Copy config.example.yaml to config.yaml."
        )

    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    if not isinstance(raw, dict):
        raise ConfigError(f"{cfg_path} did not parse to a mapping.")

    return Config(_expand(raw), cfg_path)


def check_config(path: str | Path | None = None) -> int:
    """Validate the config without touching audio or the network. Returns exit code."""
    try:
        cfg = load_config(path)
    except ConfigError as exc:
        print(f"[FAIL] {exc}")
        return 1

    print(f"config      : {cfg.path}")
    print(f"assistant   : {cfg.get('assistant.name', 'Michi')} ({cfg.get('assistant.language', 'en')})")

    try:
        name, settings = cfg.active_provider()
        key = settings.get("api_key")
        shown = "set" if key and not str(key).startswith("<<MISSING") else "MISSING"
        print(f"llm         : {name} -> {settings.get('type')} / {settings.get('model')} (api_key: {shown})")
    except ConfigError as exc:
        print(f"[FAIL] {exc}")
        return 1

    print(f"wake engine : {cfg.get('wake.engine')}")
    print(f"stt engine  : {cfg.get('stt.engine')}")
    print(f"tts engine  : {cfg.get('tts.engine')}")
    print(f"tools       : {', '.join(cfg.get('tools.enabled', []) or ['(none)'])}")
    print("\nConfig looks good.")
    return 0


if __name__ == "__main__":
    sys.exit(check_config())
