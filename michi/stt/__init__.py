"""STT factory."""

from __future__ import annotations

from ..config import ConfigError
from .base import STTEngine

__all__ = ["STTEngine", "create_stt"]


def create_stt(cfg, model_override: str | None = None) -> STTEngine:
    engine = str(cfg.get("stt.engine", "faster_whisper")).lower()

    if engine == "faster_whisper":
        from .faster_whisper_engine import FasterWhisperSTT

        return FasterWhisperSTT(cfg, model_override=model_override)

    if engine in ("openai_api", "openai", "api"):
        from .openai_api import OpenAIWhisperSTT

        return OpenAIWhisperSTT(cfg)

    raise ConfigError(f"Unknown stt.engine '{engine}' (use faster_whisper or openai_api).")
