"""TTS factory, plus a module-level handle so background tools (timers) can speak."""

from __future__ import annotations

from ..config import ConfigError
from ..logging_setup import get_logger
from .base import TTSEngine
from .speaker import Speaker, split_sentences

log = get_logger("tts")

__all__ = [
    "TTSEngine",
    "Speaker",
    "split_sentences",
    "create_tts",
    "speak_now",
    "get_active",
    "set_active_speaker",
    "get_active_speaker",
]

_ACTIVE: TTSEngine | None = None
_ACTIVE_SPEAKER: Speaker | None = None


def create_tts(cfg) -> TTSEngine:
    global _ACTIVE
    engine = str(cfg.get("tts.engine", "sapi")).lower()

    try:
        if engine == "sapi":
            from .sapi import SapiTTS

            instance: TTSEngine = SapiTTS(cfg)
        elif engine == "edge":
            from .edge import EdgeTTS

            instance = EdgeTTS(cfg)
        elif engine == "piper":
            from .piper import PiperTTS

            instance = PiperTTS(cfg)
        elif engine in ("openai_api", "openai", "api"):
            from .openai_api import OpenAITTS

            instance = OpenAITTS(cfg)
        else:
            raise ConfigError(
                f"Unknown tts.engine '{engine}' (use sapi, edge, piper or openai_api)."
            )
    except ConfigError:
        raise
    except Exception as exc:
        log.warning("TTS engine '%s' failed to start (%s) — falling back to Windows SAPI.", engine, exc)
        from .sapi import SapiTTS

        instance = SapiTTS(cfg)

    _ACTIVE = instance
    return instance


def get_active() -> TTSEngine | None:
    return _ACTIVE


def set_active_speaker(speaker: Speaker) -> None:
    """Register the assistant's Speaker so background announcements (timers, etc.)
    queue politely behind whatever Michi is currently saying."""
    global _ACTIVE_SPEAKER
    _ACTIVE_SPEAKER = speaker


def get_active_speaker() -> Speaker | None:
    return _ACTIVE_SPEAKER


def speak_now(text: str) -> None:
    """Speak from anywhere (used by timers and other background callbacks).

    Goes through the active Speaker when there is one, so the announcement waits
    its turn instead of talking over Michi mid-sentence.
    """
    if _ACTIVE_SPEAKER is not None:
        try:
            _ACTIVE_SPEAKER.say(text)
            return
        except Exception:
            log.exception("Background speech through Speaker failed")
    if _ACTIVE is not None:
        try:
            _ACTIVE.speak(text)
            return
        except Exception:
            log.exception("Background speech failed")
    print(f"[michi] {text}")
