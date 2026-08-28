"""Wake engine factory."""

from __future__ import annotations

from ..config import ConfigError
from ..logging_setup import get_logger
from .base import WakeEngine, WakeResult

log = get_logger("wake")

__all__ = ["WakeEngine", "WakeResult", "create_wake"]


def create_wake(cfg, stt=None) -> WakeEngine:
    engine = str(cfg.get("wake.engine", "stt_phrase")).lower()

    if engine == "stt_phrase":
        from .stt_phrase import SttPhraseWake

        return SttPhraseWake(cfg, stt=stt)

    if engine == "hybrid":
        from .hybrid import HybridWake

        try:
            return HybridWake(cfg)
        except Exception as exc:
            log.warning("Hybrid wake unavailable (%s) — falling back to stt_phrase.", exc)
            from .stt_phrase import SttPhraseWake

            return SttPhraseWake(cfg, stt=stt)

    if engine in ("openwakeword", "oww"):
        from .openwakeword_engine import OpenWakeWordWake

        try:
            return OpenWakeWordWake(cfg)
        except Exception as exc:
            log.warning("openWakeWord unavailable (%s) — falling back to stt_phrase.", exc)
            from .stt_phrase import SttPhraseWake

            return SttPhraseWake(cfg, stt=stt)

    if engine in ("hotkey", "push_to_talk", "ptt"):
        from .hotkey import HotkeyWake

        return HotkeyWake(cfg)

    raise ConfigError(
        f"Unknown wake.engine '{engine}' (use stt_phrase, hybrid, openwakeword or hotkey)."
    )
