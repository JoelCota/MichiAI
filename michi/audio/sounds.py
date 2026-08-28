"""Short synthesised tones — the audible 'I'm listening' cue.

Generated with numpy rather than shipped as wav files, so there are no binary
assets to lose and the pitch is trivially tweakable.
"""

from __future__ import annotations

import numpy as np

from ..logging_setup import get_logger

log = get_logger("audio")

SAMPLE_RATE = 44100


def _tone(frequencies: list[float], duration: float, volume: float) -> np.ndarray:
    """A short blip with a raised-cosine envelope so it doesn't click."""
    samples = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, samples, endpoint=False)
    wave = np.zeros(samples, dtype=np.float32)
    for index, frequency in enumerate(frequencies):
        start = int(samples * index / len(frequencies))
        end = int(samples * (index + 1) / len(frequencies))
        segment = t[start:end] - t[start]
        wave[start:end] = np.sin(2 * np.pi * frequency * segment)

    fade = max(1, int(SAMPLE_RATE * 0.008))
    envelope = np.ones(samples, dtype=np.float32)
    envelope[:fade] = np.linspace(0, 1, fade)
    envelope[-fade:] = np.linspace(1, 0, fade)
    return (wave * envelope * volume).astype(np.float32)


class Chime:
    """Plays cue tones on the configured output device. Never raises."""

    def __init__(self, cfg):
        section = cfg.section("audio.chime")
        self.enabled = bool(section.get("enabled", True))
        self.volume = float(section.get("volume", 0.25))
        self.device = section.get("output_device", cfg.get("audio.output_device"))
        self._cache: dict[str, np.ndarray] = {}

    def _build(self, name: str) -> np.ndarray:
        if name not in self._cache:
            recipes = {
                "wake": ([660.0, 880.0], 0.16),      # rising: I'm listening
                "done": ([880.0, 660.0], 0.14),      # falling: finished
                "error": ([440.0, 330.0], 0.28),     # low double: something broke
            }
            frequencies, duration = recipes.get(name, recipes["wake"])
            self._cache[name] = _tone(frequencies, duration, self.volume)
        return self._cache[name]

    def play(self, name: str = "wake", blocking: bool = False) -> None:
        if not self.enabled:
            return
        try:
            import sounddevice as sd

            sd.play(self._build(name), SAMPLE_RATE, device=self.device)
            if blocking:
                sd.wait()
        except Exception as exc:
            log.debug("Chime '%s' failed: %s", name, exc)
