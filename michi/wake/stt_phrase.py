"""Wake engine that actually hears "Hey Michi" on day one.

It transcribes short chunks with a tiny Whisper model and fuzzy-matches the phrase,
which matters because Whisper regularly hears "mishi", "michy", "meechee" or "mi chi".
Costs more CPU than a trained wake-word model — see PLAN.md phase 3 for the upgrade.
"""

from __future__ import annotations

import difflib
import re

import numpy as np

from ..logging_setup import get_logger
from ..runtime import should_run
from .base import WakeEngine, WakeResult

log = get_logger("wake")


def _normalise(text: str) -> str:
    text = text.lower().replace("!", " ").replace(",", " ").replace(".", " ")
    return re.sub(r"[^a-záéíóúñü ]+", " ", text)


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def find_wake_phrase(text: str, phrases: list[str], threshold: float) -> tuple[bool, str]:
    """Return (matched, remaining_text_after_the_phrase)."""
    words = _normalise(text).split()
    if not words:
        return False, ""

    for phrase in phrases:
        target = _normalise(phrase)
        span = len(target.split())
        for start in range(0, max(1, len(words) - span + 1)):
            window = " ".join(words[start : start + span])
            if _similarity(window, target) >= threshold:
                remainder = " ".join(words[start + span :]).strip()
                return True, remainder

    # Single-word fallback: just the name, said on its own.
    name_targets = {p.split()[-1] for p in (_normalise(x) for x in phrases) if p}
    for index, word in enumerate(words):
        for target in name_targets:
            if len(word) >= 4 and _similarity(word, target) >= max(threshold, 0.82):
                return True, " ".join(words[index + 1 :]).strip()

    return False, ""


class SttPhraseWake(WakeEngine):
    name = "stt_phrase"

    def __init__(self, cfg, stt=None):
        super().__init__(cfg)
        section = cfg.section("wake.stt_phrase")
        self.phrases = [str(p) for p in section.get("phrases", ["hey michi"])]
        self.threshold = float(section.get("fuzzy_threshold", 0.75))
        self.chunk_seconds = float(section.get("chunk_seconds", 2.0))
        self.print_transcripts = bool(cfg.get("logging.print_transcripts", False))

        if stt is not None:
            self.stt = stt
        else:
            from ..stt import create_stt

            wake_model = cfg.get("stt.faster_whisper.wake_model", "tiny.en")
            self.stt = create_stt(cfg, model_override=wake_model)

    def banner(self) -> str:
        hint = f" or press {self.hotkey.combo}" if self.hotkey and self.hotkey.available else ""
        return f"say \"{self.phrases[0]}\"{hint}"

    def wait(self, mic) -> WakeResult:
        silence_floor = mic.silence_threshold * 0.7
        mic.flush()

        while should_run():
            if self._hotkey_fired():
                return WakeResult(True, source="hotkey")
            if self._idling(mic):
                continue

            chunk = mic.read_seconds(self.chunk_seconds)
            if len(chunk) == 0:
                continue

            # Skip the transcription entirely when the room is quiet — this is
            # what keeps idle CPU use reasonable.
            level = float(np.sqrt(np.mean(np.square(chunk))))
            if level < silence_floor:
                continue

            try:
                text = self.stt.transcribe(chunk, mic.sample_rate)
            except Exception as exc:  # a transcription hiccup must not kill the loop
                log.warning("Wake transcription failed (%s) — continuing.", exc)
                continue
            if not text:
                continue
            log.debug("heard: %s", text)

            matched, remainder = find_wake_phrase(text, self.phrases, self.threshold)
            if matched:
                if self.print_transcripts:
                    log.info("wake: %s", text)
                return WakeResult(True, text=remainder, source="wake")

        return WakeResult(False)
