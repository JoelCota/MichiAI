"""Process-wide run state, so any tool or the tray icon can steer the main loop."""

from __future__ import annotations

import threading

_shutdown = threading.Event()
_paused = threading.Event()


# -- shutdown ---------------------------------------------------------------
def request_shutdown() -> None:
    _shutdown.set()


def should_run() -> bool:
    return not _shutdown.is_set()


# -- pause (stop listening without quitting) --------------------------------
def pause() -> None:
    _paused.set()


def resume() -> None:
    _paused.clear()


def toggle_pause() -> bool:
    if _paused.is_set():
        _paused.clear()
    else:
        _paused.set()
    return _paused.is_set()


def is_paused() -> bool:
    return _paused.is_set()


def reset() -> None:
    _shutdown.clear()
    _paused.clear()
