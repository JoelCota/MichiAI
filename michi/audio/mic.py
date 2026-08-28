"""Microphone capture with simple energy-based voice activity detection."""

from __future__ import annotations

import queue
import time

import numpy as np

from ..logging_setup import get_logger

log = get_logger("audio")


def list_devices() -> str:
    import sounddevice as sd

    lines = []
    for index, device in enumerate(sd.query_devices()):
        direction = []
        if device["max_input_channels"]:
            direction.append("in")
        if device["max_output_channels"]:
            direction.append("out")
        lines.append(f"  [{index:>2}] {device['name']}  ({'/'.join(direction)})")
    return "\n".join(lines)


def _resolve_device(value):
    """Accept null, an integer index, or a name substring."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)

    import sounddevice as sd

    needle = str(value).lower()
    for index, device in enumerate(sd.query_devices()):
        if needle in device["name"].lower() and device["max_input_channels"] > 0:
            return index
    log.warning("No input device matching '%s' — using the system default.", value)
    return None


class Microphone:
    """A single always-open input stream that other layers pull audio from."""

    def __init__(self, cfg):
        self.sample_rate = int(cfg.get("audio.sample_rate", 16000))
        self.device = _resolve_device(cfg.get("audio.input_device"))
        self.silence_threshold = float(cfg.get("audio.silence_threshold", 0.012))
        self.silence_duration = float(cfg.get("audio.silence_duration", 0.9))
        self.max_utterance = float(cfg.get("audio.max_utterance_seconds", 20))
        self.blocksize = 1024
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        import sounddevice as sd

        if self._stream is not None:
            return

        def callback(indata, frames, time_info, status):  # noqa: ARG001
            if status:
                log.debug("audio status: %s", status)
            self._queue.put(indata[:, 0].copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.blocksize,
            device=self.device,
            callback=callback,
        )
        self._stream.start()
        log.debug("Microphone open at %d Hz (device=%s).", self.sample_rate, self.device)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    # -- reading -----------------------------------------------------------
    def flush(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def read_seconds(self, seconds: float) -> np.ndarray:
        """Block until `seconds` of audio has been collected."""
        wanted = int(seconds * self.sample_rate)
        chunks: list[np.ndarray] = []
        collected = 0
        while collected < wanted:
            try:
                chunk = self._queue.get(timeout=2.0)
            except queue.Empty:
                break
            chunks.append(chunk)
            collected += len(chunk)
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)

    def record_utterance(self, preroll: np.ndarray | None = None) -> np.ndarray:
        """Record until the speaker goes quiet, or the max length is hit.

        `preroll` lets the wake engine hand over the audio it was already holding,
        so the first syllable after the wake word isn't clipped.
        """
        chunks: list[np.ndarray] = []
        if preroll is not None and len(preroll):
            chunks.append(preroll)

        started = time.monotonic()
        last_voice = started
        heard_voice = False

        while True:
            try:
                chunk = self._queue.get(timeout=1.0)
            except queue.Empty:
                if time.monotonic() - started > self.max_utterance:
                    break
                continue

            chunks.append(chunk)
            rms = float(np.sqrt(np.mean(np.square(chunk))))
            now = time.monotonic()

            if rms > self.silence_threshold:
                last_voice = now
                heard_voice = True
            elif heard_voice and (now - last_voice) > self.silence_duration:
                break
            elif not heard_voice and (now - started) > 4.0:
                break  # nobody said anything

            if now - started > self.max_utterance:
                break

        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        return audio if heard_voice else np.zeros(0, dtype=np.float32)


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
