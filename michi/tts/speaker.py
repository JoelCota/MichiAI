"""Sentence-level speech queue.

The single biggest latency win in a voice assistant: start speaking the first
sentence while the model is still generating the rest. A background thread pulls
finished sentences off a queue and speaks them in order, so the main loop never
blocks on audio.
"""

from __future__ import annotations

import queue
import re
import threading

from ..events import BUS, State
from ..logging_setup import get_logger

log = get_logger("tts")

# A sentence ends at .!?… (plus any closing quote/bracket) followed by space or end,
# or at a newline. The trailing-whitespace lookahead already protects decimals like
# "3.5"; only titles and abbreviations need an explicit exception.
_SENTENCE_END = re.compile(r'(?<=[.!?…])["\')\]]*(?=\s|$)|\n+')
_PROTECTED = re.compile(
    r"\b(?:mr|mrs|ms|dr|prof|sr|sra|srta|st|vs|etc|approx|min|max|fig)\.$",
    re.IGNORECASE,
)


def split_sentences(text: str, min_chars: int = 12) -> list[str]:
    """Split into speakable chunks, merging fragments shorter than `min_chars`.

    Merging matters: "Sure." on its own sounds clipped, and each chunk costs a
    round trip to the TTS engine.
    """
    if not text.strip():
        return []

    pieces: list[str] = []
    cursor = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end()
        candidate = text[cursor:end]
        if _PROTECTED.search(candidate.rstrip()):  # don't break on "Dr." or "etc."
            continue
        if candidate.strip():
            pieces.append(candidate.strip())
        cursor = end

    tail = text[cursor:].strip()
    if tail:
        pieces.append(tail)

    merged: list[str] = []
    for piece in pieces:
        if merged and len(merged[-1]) < min_chars:
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    return merged


class Speaker:
    """Feed it text (whole or in deltas); it speaks complete sentences as they arrive."""

    def __init__(self, engine, min_chars: int = 12, bus=BUS):
        self.engine = engine
        self.min_chars = min_chars
        self.bus = bus
        self._queue: queue.Queue = queue.Queue()
        self._buffer = ""
        self._interrupted = threading.Event()
        self._speaking = threading.Event()
        self._stop_thread = threading.Event()
        self._worker = threading.Thread(target=self._run, name="michi-speaker", daemon=True)
        self._worker.start()

    # -- worker ------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop_thread.is_set():
            try:
                sentence = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if sentence and not self._interrupted.is_set():
                    self._speaking.set()
                    if self.bus:
                        self.bus.set_state(State.SPEAKING, sentence[:60])
                    self.engine.speak(sentence)
            except Exception:
                log.exception("Speech failed for %r", sentence[:40])
            finally:
                self._speaking.clear()
                self._queue.task_done()

    # -- input -------------------------------------------------------------
    def feed(self, delta: str) -> None:
        """Add streamed text; anything that forms a complete sentence is queued."""
        if self._interrupted.is_set():
            return
        self._buffer += delta
        sentences = split_sentences(self._buffer, self.min_chars)
        if len(sentences) > 1:
            # Keep the last one back — more text may still be coming for it.
            for sentence in sentences[:-1]:
                self._queue.put(sentence)
            self._buffer = sentences[-1]

    def flush(self) -> None:
        """Queue whatever is left in the buffer."""
        remaining = self._buffer.strip()
        self._buffer = ""
        if remaining and not self._interrupted.is_set():
            for sentence in split_sentences(remaining, self.min_chars):
                self._queue.put(sentence)

    def say(self, text: str) -> None:
        """Queue a complete message (used when not streaming)."""
        if not text.strip():
            return
        self._interrupted.clear()
        for sentence in split_sentences(text, self.min_chars):
            self._queue.put(sentence)

    # -- control -----------------------------------------------------------
    def begin(self) -> None:
        self._interrupted.clear()
        self._buffer = ""

    @property
    def busy(self) -> bool:
        return self._speaking.is_set() or not self._queue.empty()

    def wait(self, timeout: float | None = None) -> None:
        """Block until everything queued has been spoken."""
        if timeout is None:
            self._queue.join()
            return
        clock = threading.Event()
        waited = 0.0
        while self.busy and waited < timeout:
            clock.wait(0.05)
            waited += 0.05

    def interrupt(self) -> None:
        """Barge-in: drop anything pending and cut off the current sentence."""
        self._interrupted.set()
        self._buffer = ""
        drained = 0
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                drained += 1
            except queue.Empty:
                break
        try:
            self.engine.stop()
        except Exception:
            pass
        if drained:
            log.debug("Interrupted, dropped %d queued sentence(s).", drained)

    def shutdown(self) -> None:
        self.interrupt()
        self._stop_thread.set()
