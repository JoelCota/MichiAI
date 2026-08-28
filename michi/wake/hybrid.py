"""Hybrid wake: openWakeWord as the always-on gate, Whisper as the verifier.

The ONNX model listens at near-zero CPU for its trigger word (a pretrained one
like `hey_jarvis`, or your own hey_michi.onnx). Only when it fires does the tiny
Whisper model wake up for a couple of seconds to check the wake phrase really
was said and to capture whatever came after it.

The gate fires at the END of the phrase, so the verifier transcribes a rolling
preroll of the last ~2.5 seconds plus the following utterance: it hears
"hey jarvis, what time is it" as one clip, matches the phrase, and returns the
remainder as the command.

Best of both worlds: idle CPU ≈ openwakeword alone, but Michi still verifies
against the actual phrases instead of trusting the gate blindly.
"""

from __future__ import annotations

import numpy as np

from ..logging_setup import get_logger
from ..runtime import should_run
from .base import WakeResult
from .openwakeword_engine import FRAME, OpenWakeWordWake
from .stt_phrase import find_wake_phrase

log = get_logger("wake")

PREROLL_SECONDS = 2.5


def hybrid_phrases(cfg, gate_label: str | None = None) -> list[str]:
    """Phrases the verifier accepts: the configured wake phrases, plus whatever
    word the openWakeWord gate listens for (so "hey jarvis" gates verify)."""
    configured = [str(p) for p in cfg.section("wake.stt_phrase").get("phrases", ["hey michi"])]
    if not gate_label:
        gate_label = str(cfg.section("wake.openwakeword").get("model", "hey_jarvis"))
    spoken = str(gate_label).replace("_", " ").strip()
    if spoken and spoken not in configured:
        configured.insert(0, spoken)
    return configured


class HybridWake(OpenWakeWordWake):
    name = "hybrid"

    def __init__(self, cfg):
        super().__init__(cfg)
        section = cfg.section("wake.stt_phrase")
        self.phrases = hybrid_phrases(cfg, gate_label=self.label)
        self.threshold = float(section.get("fuzzy_threshold", 0.75))
        self.chunk_seconds = float(section.get("chunk_seconds", 2.0))

        from ..stt import create_stt

        wake_model = cfg.get("stt.faster_whisper.wake_model", "tiny.en")
        self.stt = create_stt(cfg, model_override=wake_model)
        log.info(
            "Hybrid wake: gate='%s' (threshold=%.2f), verify=%s",
            self.label, self.threshold, self.phrases,
        )

    def banner(self) -> str:
        hint = f" or press {self.hotkey.combo}" if self.hotkey and self.hotkey.available else ""
        gate = self.label.replace("_", " ")
        return f"say \"{gate}\" or \"{self.phrases[-1]}\"{hint}"

    def wait(self, mic) -> WakeResult:
        mic.flush()
        buffer = np.zeros(0, dtype=np.float32)
        preroll = np.zeros(0, dtype=np.float32)
        max_preroll = int(mic.sample_rate * PREROLL_SECONDS)

        while should_run():
            if self._hotkey_fired():
                return WakeResult(True, source="hotkey")
            if self._idling(mic):
                buffer = np.zeros(0, dtype=np.float32)
                preroll = np.zeros(0, dtype=np.float32)
                continue

            chunk = mic.read_seconds(0.1)
            if len(chunk) == 0:
                continue
            buffer = np.concatenate([buffer, chunk])
            preroll = np.concatenate([preroll, chunk])
            if len(preroll) > max_preroll:
                preroll = preroll[len(preroll) - max_preroll :]

            while len(buffer) >= FRAME:
                frame, buffer = buffer[:FRAME], buffer[FRAME:]
                scores = self.model.predict((frame * 32767).astype(np.int16))
                if not any(score >= self.threshold for score in scores.values()):
                    continue
                self.model.reset()
                result = self._verify(mic, preroll)
                if result is not None:
                    return result
                buffer = np.zeros(0, dtype=np.float32)  # false wake — keep listening
                preroll = np.zeros(0, dtype=np.float32)

        return WakeResult(False)

    def _verify(self, mic, preroll: np.ndarray) -> WakeResult | None:
        """The gate fired — is the user actually addressing Michi?

        Transcribes the preroll (which holds the phrase the gate just heard)
        plus the following utterance, so the full "hey jarvis, what time is it"
        clip is checked at once and the command comes back as the remainder.
        """
        tail = mic.read_seconds(self.chunk_seconds)
        audio = np.concatenate([preroll, tail]) if len(preroll) else tail
        if len(audio) == 0:
            return None
        try:
            text = self.stt.transcribe(audio, mic.sample_rate)
        except Exception as exc:
            log.warning("Wake verification failed (%s) — ignoring trigger.", exc)
            return None
        if not text:
            return None
        log.debug("wake gate heard: %s", text)
        matched, remainder = find_wake_phrase(text, self.phrases, self.threshold)
        if not matched:
            log.debug("gate triggered, but not a wake phrase — ignoring.")
            return None
        return WakeResult(True, text=remainder, source="wake")
