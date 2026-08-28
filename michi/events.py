"""A tiny event bus so the tray icon (and anything else) can follow what Michi is doing."""

from __future__ import annotations

import threading
from enum import Enum
from typing import Callable

from .logging_setup import get_logger

log = get_logger("events")


class State(str, Enum):
    STARTING = "starting"
    IDLE = "idle"           # waiting for the wake word
    LISTENING = "listening"  # capturing your sentence
    THINKING = "thinking"    # model call / tool run
    SPEAKING = "speaking"
    PAUSED = "paused"
    ERROR = "error"

    @property
    def label(self) -> str:
        return {
            State.STARTING: "Starting…",
            State.IDLE: "Waiting for the wake word",
            State.LISTENING: "Listening",
            State.THINKING: "Thinking",
            State.SPEAKING: "Speaking",
            State.PAUSED: "Paused",
            State.ERROR: "Error",
        }[self]


Listener = Callable[[State, str], None]


class EventBus:
    def __init__(self) -> None:
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()
        self.state: State = State.STARTING
        self.detail: str = ""

    def subscribe(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)
            state, detail = self.state, self.detail
        # Prime the new listener, but a bad one must not take the caller down.
        try:
            listener(state, detail)
        except Exception:
            log.debug("Event listener raised on subscribe", exc_info=True)

    def set_state(self, state: State, detail: str = "") -> None:
        with self._lock:
            if state == self.state and detail == self.detail:
                return
            self.state, self.detail = state, detail
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(state, detail)
            except Exception:
                log.debug("Event listener raised", exc_info=True)


BUS = EventBus()
