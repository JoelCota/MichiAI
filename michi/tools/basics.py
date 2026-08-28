"""Always-useful tools with no OS dependencies."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import PROJECT_ROOT
from ..logging_setup import get_logger
from .registry import tool

log = get_logger("tools")

NOTES_FILE = PROJECT_ROOT / "data" / "notes.json"
TIMERS_FILE = PROJECT_ROOT / "data" / "timers.json"
if os.environ.get("MICHI_TESTING") == "1":  # keep the test suite out of real data
    TIMERS_FILE = Path(tempfile.gettempdir()) / "michi_test_timers.json"

_timers: dict[str, "_TimerEntry"] = {}
_timers_lock = threading.Lock()


@dataclass
class _TimerEntry:
    label: str
    ends_at: float
    key: str = ""
    thread: threading.Timer | None = None


def _load_notes() -> dict:
    if NOTES_FILE.exists():
        try:
            return json.loads(NOTES_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_notes(notes: dict) -> None:
    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    NOTES_FILE.write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")


# -- timers (persistent across restarts) ------------------------------------
def _load_timers() -> list[dict]:
    if TIMERS_FILE.exists():
        try:
            data = json.loads(TIMERS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_timers() -> None:
    with _timers_lock:
        entries = [{"label": t.label, "ends_at": t.ends_at} for t in _timers.values()]
    try:
        TIMERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TIMERS_FILE.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("Couldn't save timers (%s).", exc)


def _timer_fired(key: str, label: str) -> None:
    from ..tts import speak_now

    with _timers_lock:
        _timers.pop(key, None)
    _save_timers()
    speak_now(f"Time's up for {label}." if label else "Time's up.")


def _arm(entry: _TimerEntry) -> None:
    delay = max(0.5, entry.ends_at - time.time())
    entry.thread = threading.Timer(delay, _timer_fired, args=(entry.key, entry.label))
    entry.thread.daemon = True
    entry.thread.start()


def restore_timers() -> int:
    """Re-arm timers that survived a restart. Called when the tools load."""
    restored = 0
    now = time.time()
    for item in _load_timers():
        try:
            label = str(item.get("label", ""))
            ends_at = float(item["ends_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if ends_at <= now:
            continue
        key = label or f"__unnamed_{int(time.time() * 1000) + restored}"
        with _timers_lock:
            if key in _timers:
                continue
            entry = _TimerEntry(label=label, ends_at=ends_at, key=key)
            _arm(entry)
            _timers[key] = entry
        restored += 1
    _save_timers()  # also drops expired entries from disk
    if restored:
        log.info("Restored %d timer(s) from disk.", restored)
    return restored


# -- tools ------------------------------------------------------------------
@tool(group="basics", description="Get the current local date and time.")
def get_time() -> str:
    now = datetime.now()
    return now.strftime("%A, %B %d %Y, %I:%M %p").replace(" 0", " ")


@tool(
    group="basics",
    description="Start a countdown timer. Michi announces it when it finishes.",
    parameters={
        "minutes": {"type": "number", "description": "How many minutes to count down."},
        "label": {"type": "string", "description": "Optional name for the timer."},
    },
    required=["minutes"],
)
def start_timer(minutes: float, label: str = "") -> str:
    seconds = max(1.0, float(minutes) * 60.0)
    label = label.strip()
    with _timers_lock:
        key = label or f"__unnamed_{int(time.time() * 1000)}"
        if label and label in _timers:
            old = _timers.pop(label)
            if old.thread:
                old.thread.cancel()
        entry = _TimerEntry(label=label, ends_at=time.time() + seconds, key=key)
        _arm(entry)
        _timers[key] = entry
    _save_timers()
    pretty = f"{minutes:g} minute{'s' if minutes != 1 else ''}"
    return f"Timer set for {pretty}{' (' + label + ')' if label else ''}."


@tool(
    group="basics",
    description="Cancel a running timer by its label. Omit the label to cancel the most recent timer.",
    parameters={"label": {"type": "string", "description": "The timer's label."}},
)
def cancel_timer(label: str = "") -> str:
    with _timers_lock:
        if not _timers:
            return "No timers are running."
        if label:
            entry = _timers.pop(label.strip(), None)
            if entry is None:
                return f"No timer named '{label}'."
        else:
            label, entry = list(_timers.items())[-1]
            del _timers[label]
        if entry.thread:
            entry.thread.cancel()
    _save_timers()
    return f"Cancelled timer{(' ' + label) if label else ''}."


@tool(
    group="basics",
    description="List running countdown timers and how long each one has left.",
)
def list_timers() -> str:
    now = time.time()
    with _timers_lock:
        entries = list(_timers.values())
    if not entries:
        return "No timers are running."
    parts = []
    for entry in entries:
        remaining = max(0, int(entry.ends_at - now))
        minutes, seconds = divmod(remaining, 60)
        pretty = f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"
        parts.append(f"{entry.label} — {pretty} left" if entry.label else f"unnamed — {pretty} left")
    return "Timers: " + "; ".join(parts)


@tool(
    group="basics",
    description="Remember a fact for later. Use when the user says 'remember that ...'.",
    parameters={
        "key": {"type": "string", "description": "Short label, e.g. 'wifi password'."},
        "value": {"type": "string", "description": "What to remember."},
    },
    required=["key", "value"],
)
def remember(key: str, value: str) -> str:
    notes = _load_notes()
    notes[key.strip().lower()] = {"value": value, "saved": datetime.now().isoformat(timespec="seconds")}
    _save_notes(notes)
    return f"Saved: {key}."


@tool(
    group="basics",
    description="Recall something previously remembered. Omit key to list everything.",
    parameters={"key": {"type": "string", "description": "The label to look up."}},
)
def recall(key: str = "") -> str:
    notes = _load_notes()
    if not notes:
        return "Nothing has been saved yet."
    if not key:
        return "Saved items: " + ", ".join(notes)
    needle = key.strip().lower()
    if needle in notes:
        return notes[needle]["value"]
    for label, entry in notes.items():
        if needle in label or label in needle:
            return entry["value"]
    return f"Nothing saved under '{key}'."


@tool(
    group="basics",
    description="Forget a remembered note by its label.",
    parameters={"key": {"type": "string", "description": "The label to delete."}},
    required=["key"],
)
def forget(key: str) -> str:
    notes = _load_notes()
    needle = key.strip().lower()
    if needle in notes:
        del notes[needle]
        _save_notes(notes)
        return f"Forgot {key}."
    return f"Nothing saved under '{key}'."


@tool(group="basics", description="Stop listening and shut Michi down.")
def go_to_sleep() -> str:
    from ..runtime import request_shutdown

    request_shutdown()
    return "Shutting down. Goodbye."


# Re-arm timers left over from a previous session (unless the test suite is
# running, in which case timers point at a temp file and stay silent).
if os.environ.get("MICHI_TESTING") != "1":
    try:
        restore_timers()
    except Exception as exc:  # never break startup over a corrupt timer file
        log.warning("Timer restore failed (%s).", exc)
