"""Push-to-talk only: no listening until you press the combo."""

from __future__ import annotations

import time

from ..runtime import should_run
from .base import WakeEngine, WakeResult


class HotkeyWake(WakeEngine):
    name = "hotkey"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.combo = str(cfg.get("wake.hotkey.combo", cfg.get("wake.hotkey_combo", "ctrl+alt+m")))
        if self.hotkey is None:
            from .base import HotkeyWatcher

            self.hotkey = HotkeyWatcher(self.combo)

    def banner(self) -> str:
        return f"press {self.combo} to talk"

    def wait(self, mic) -> WakeResult:
        mic.flush()
        while should_run():
            if self._hotkey_fired() and not self._idling(mic):
                mic.flush()
                return WakeResult(True, source="hotkey")
            time.sleep(0.05)
        return WakeResult(False)
