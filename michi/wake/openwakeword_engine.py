"""openWakeWord — small ONNX model, very low idle CPU.

No pretrained "hey michi" model exists, so out of the box this listens for
`hey_jarvis`. Train your own (PLAN.md phase 3) and point `wake.openwakeword.model`
at the resulting models/hey_michi.onnx.
"""

from __future__ import annotations

import numpy as np

from ..logging_setup import get_logger
from ..runtime import should_run
from .base import WakeEngine, WakeResult

log = get_logger("wake")

PRETRAINED = {"alexa", "hey_jarvis", "hey_mycroft", "hey_rhasspy"}
FRAME = 1280  # openWakeWord expects 80 ms frames of 16 kHz int16


class OpenWakeWordWake(WakeEngine):
    name = "openwakeword"

    def __init__(self, cfg):
        super().__init__(cfg)
        try:
            from openwakeword.model import Model
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "openwakeword isn't installed. Run: pip install openwakeword onnxruntime"
            ) from exc

        section = cfg.section("wake.openwakeword")
        self.threshold = float(section.get("threshold", 0.5))
        requested = str(section.get("model", "hey_jarvis"))

        if requested in PRETRAINED:
            self.label = requested
            try:
                import openwakeword

                openwakeword.utils.download_models([requested])
            except Exception as exc:
                log.debug("Model download skipped/failed: %s", exc)
            self.model = Model(wakeword_models=[requested], inference_framework="onnx")
        else:
            path = cfg.resolve_path(requested)
            if not path.exists():
                raise RuntimeError(
                    f"Wake model not found at {path}. Use a pretrained name "
                    f"({', '.join(sorted(PRETRAINED))}) or train your own."
                )
            self.label = path.stem
            self.model = Model(wakeword_models=[str(path)], inference_framework="onnx")

        log.info("openWakeWord ready (model=%s, threshold=%.2f).", self.label, self.threshold)

    def banner(self) -> str:
        hint = f" or press {self.hotkey.combo}" if self.hotkey and self.hotkey.available else ""
        spoken = self.label.replace("_", " ")
        return f"say \"{spoken}\"{hint}"

    def wait(self, mic) -> WakeResult:
        mic.flush()
        buffer = np.zeros(0, dtype=np.float32)
        history: list[np.ndarray] = []

        while should_run():
            if self._hotkey_fired():
                return WakeResult(True, source="hotkey")
            if self._idling(mic):
                buffer = np.zeros(0, dtype=np.float32)
                continue

            chunk = mic.read_seconds(0.1)
            if len(chunk) == 0:
                continue
            buffer = np.concatenate([buffer, chunk])

            while len(buffer) >= FRAME:
                frame, buffer = buffer[:FRAME], buffer[FRAME:]
                history.append(frame)
                if len(history) > 6:  # keep ~0.5 s of pre-roll
                    history.pop(0)

                scores = self.model.predict((frame * 32767).astype(np.int16))
                if any(score >= self.threshold for score in scores.values()):
                    self.model.reset()
                    return WakeResult(
                        True, preroll=np.concatenate(history[-3:]), source="wake"
                    )

        return WakeResult(False)
