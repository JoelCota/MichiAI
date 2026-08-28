from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from ..logging_setup import get_logger
from ..runtime import is_paused

log = get_logger("wake")


@dataclass
class WakeResult:
    triggered: bool
    preroll: np.ndarray | None = None
    text: str = ""          # words already captured after the wake phrase
    source: str = "wake"    # "wake" | "hotkey" | "followup"


class HotkeyWatcher:
    """Background push-to-talk listener. Always available as a fallback."""

    def __init__(self, combo: str = "ctrl+alt+m"):
        self.combo = combo
        self.event = threading.Event()
        self._ok = False
        try:
            import keyboard

            keyboard.add_hotkey(combo, self.event.set)
            self._ok = True
            log.info("Push-to-talk ready: %s", combo)
        except Exception as exc:
            log.warning("Push-to-talk unavailable (%s). Wake word still works.", exc)

    @property
    def available(self) -> bool:
        return self._ok

    def triggered(self) -> bool:
        if self.event.is_set():
            self.event.clear()
            return True
        return False


class WakeEngine(ABC):
    name = "wake"

    def __init__(self, cfg):
        self.cfg = cfg
        self.hotkey: HotkeyWatcher | None = None
        if cfg.get("wake.always_allow_hotkey", True):
            self.hotkey = HotkeyWatcher(str(cfg.get("wake.hotkey_combo", "ctrl+alt+m")))

    def _hotkey_fired(self) -> bool:
        return self.hotkey is not None and self.hotkey.triggered()

    def _idling(self, mic) -> bool:
        """True while paused — callers skip their detection work and loop again."""
        if not is_paused():
            return False
        time.sleep(0.2)
        try:
            mic.flush()
        except Exception:
            pass
        return True

    @abstractmethod
    def wait(self, mic) -> WakeResult:
        """Block until the wake word (or hotkey) fires, or shutdown is requested."""

    def banner(self) -> str:
        hint = f" or press {self.hotkey.combo}" if self.hotkey and self.hotkey.available else ""
        return f"listening for the wake word{hint}"
