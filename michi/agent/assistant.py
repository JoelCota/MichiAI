"""Wires every layer together and runs the listen -> think -> speak loop."""

from __future__ import annotations

import threading
import time

import numpy as np

from ..audio import Chime, Microphone
from ..events import BUS, State
from ..logging_setup import get_logger, setup_logging
from ..runtime import is_paused, request_shutdown, should_run
from ..stt import create_stt
from ..tools import build_registry
from ..tts import Speaker, create_tts, set_active_speaker
from ..wake import create_wake
from .brain import Brain

log = get_logger("assistant")

AFFIRMATIVE = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "do it", "go ahead",
    "please do", "confirm", "si", "sí", "claro", "dale", "hazlo",
}


class Assistant:
    def __init__(self, cfg):
        self.cfg = cfg
        setup_logging(cfg)
        self.bus = BUS
        self.bus.set_state(State.STARTING)

        self.name = cfg.get("assistant.name", "Michi")
        self.followup_seconds = float(cfg.get("assistant.followup_seconds", 8))
        self.streaming = bool(cfg.get("assistant.streaming", True))
        self.print_transcripts = bool(cfg.get("logging.print_transcripts", True))
        self.barge_in = bool(cfg.get("audio.barge_in", False))

        log.info("Starting %s ...", self.name)

        from ..llm import create_provider

        self.provider = create_provider(cfg)
        log.info("Brain: %s%s", self.provider.describe(),
                 "" if self.provider.supports_streaming else " (no streaming)")

        self.tools = build_registry(cfg, confirm_callback=self._confirm)
        self.brain = Brain(cfg, self.provider, self.tools)

        self.stt = create_stt(cfg)
        self.tts = create_tts(cfg)
        self.speaker = Speaker(self.tts, min_chars=int(cfg.get("tts.min_chunk_chars", 12)))
        set_active_speaker(self.speaker)
        log.info("Voice: %s", self.tts.name)

        self.mic = Microphone(cfg)
        self.chime = Chime(cfg)
        # The wake engine loads its own (tiny) STT model so constant scanning stays
        # cheap while the command itself is transcribed by the bigger one above.
        self.wake = create_wake(cfg)

        self._tray = None

    # -- speaking ----------------------------------------------------------
    def say(self, text: str, wait: bool = True) -> None:
        if not text:
            return
        if self.print_transcripts:
            log.info("%s: %s", self.name, text)
        self.speaker.begin()
        self.speaker.say(text)
        if wait:
            self.speaker.wait()

    # -- listening ---------------------------------------------------------
    def listen(self, preroll=None) -> str:
        self.bus.set_state(State.LISTENING)
        audio = self.mic.record_utterance(preroll=preroll)
        if len(audio) == 0:
            return ""
        self.bus.set_state(State.THINKING, "transcribing")
        try:
            text = self.stt.transcribe(audio, self.mic.sample_rate)
        except Exception as exc:  # an STT hiccup must not kill the assistant
            log.exception("Transcription failed")
            return ""
        if text and self.print_transcripts:
            log.info("you: %s", text)
        return text

    def _confirm(self, tool_name: str) -> bool:
        pretty = tool_name.replace("_", " ")
        self.say(f"Do you want me to {pretty}?")
        answer = self.listen().strip().lower().rstrip(".!?")
        approved = any(word in answer for word in AFFIRMATIVE)
        log.info("confirm %s -> %s (heard: %r)", tool_name, approved, answer)
        return approved

    # -- barge-in ----------------------------------------------------------
    def _watch_for_interruption(self, stop: threading.Event) -> None:
        """Cut Michi off when the user starts talking over her.

        Off by default: without headphones the mic hears Michi's own voice and
        she'd interrupt herself. Enable audio.barge_in once you've checked it.
        """
        threshold = self.mic.silence_threshold * 3.0
        loud_since: float | None = None

        while not stop.is_set() and self.speaker.busy:
            chunk = self.mic.read_seconds(0.1)
            if len(chunk) == 0:
                continue
            level = float(np.sqrt(np.mean(np.square(chunk))))
            now = time.monotonic()
            if level > threshold:
                loud_since = loud_since or now
                if now - loud_since > 0.35:
                    log.info("Interrupted by the user.")
                    self.speaker.interrupt()
                    return
            else:
                loud_since = None

    # -- main loop ---------------------------------------------------------
    def run(self, with_tray: bool | None = None) -> None:
        if with_tray is None:
            with_tray = bool(self.cfg.get("ui.tray", False))
        if with_tray:
            self._start_tray()

        with self.mic:
            self.say(f"{self.name} is ready.")
            print(f"\n  [{self.wake.banner()}]   Ctrl+C to quit\n")

            while should_run():
                self.bus.set_state(State.PAUSED if is_paused() else State.IDLE)
                result = self.wake.wait(self.mic)
                if not result.triggered:
                    break

                self.chime.play("wake")
                command = result.text.strip()
                if len(command.split()) < 2:
                    # Wake word only — prompt and listen for the actual request.
                    command = self.listen(preroll=result.preroll)

                if not command.strip():
                    continue

                self._handle_turn(command)

    def _handle_turn(self, command: str) -> None:
        self._speak_answer(command)

        # Follow-up window: keep the conversation open without the wake word.
        deadline = time.monotonic() + self.followup_seconds
        while should_run() and not is_paused() and time.monotonic() < deadline:
            self.mic.flush()
            follow_up = self.listen()
            if not follow_up.strip():
                break
            self._speak_answer(follow_up)
            deadline = time.monotonic() + self.followup_seconds

        self.bus.set_state(State.IDLE)

    def _speak_answer(self, command: str) -> None:
        self.bus.set_state(State.THINKING)
        self.speaker.begin()

        streamed: list[str] = []

        def on_delta(delta: str) -> None:
            streamed.append(delta)
            self.speaker.feed(delta)

        use_stream = self.streaming and self.provider.supports_streaming
        answer = self.brain.respond(command, on_delta=on_delta if use_stream else None)

        if use_stream and streamed:
            self.speaker.flush()
            if self.print_transcripts:
                log.info("%s: %s", self.name, answer)
        else:
            self.say(answer, wait=False)

        stop = threading.Event()
        watcher = None
        if self.barge_in:
            watcher = threading.Thread(
                target=self._watch_for_interruption, args=(stop,), daemon=True
            )
            watcher.start()

        self.speaker.wait()
        stop.set()
        if watcher is not None:
            watcher.join(timeout=0.5)

    # -- tray --------------------------------------------------------------
    def _start_tray(self) -> None:
        try:
            from ..ui.tray import TrayIcon

            self._tray = TrayIcon(self)
            self._tray.start()
        except Exception as exc:
            log.warning("Tray icon unavailable (%s) — running without it.", exc)

    def shutdown(self) -> None:
        request_shutdown()
        self.bus.set_state(State.STARTING, "shutting down")
        try:
            self.speaker.shutdown()
        except Exception:
            pass
        try:
            self.mic.stop()
        except Exception:
            pass
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass

    # -- keyboard-only mode ------------------------------------------------
    def run_text_mode(self) -> None:
        print(f"\n  {self.name} — text mode. Type 'quit' to exit.\n")
        while should_run():
            try:
                line = input("you: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line.lower() in ("quit", "exit", "bye"):
                break

            use_stream = self.streaming and self.provider.supports_streaming
            print(f"{self.name}: ", end="", flush=True)
            if use_stream:
                printed: list[str] = []

                def on_delta(delta: str) -> None:
                    printed.append(delta)
                    print(delta, end="", flush=True)

                answer = self.brain.respond(line, on_delta=on_delta)
                if not printed:
                    print(answer, end="")
            else:
                print(self.brain.respond(line), end="")
            print("\n")
