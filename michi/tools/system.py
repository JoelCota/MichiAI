"""Windows system control: volume, media keys, lock, screenshot."""

from __future__ import annotations

import datetime
import subprocess
import sys

from ..config import PROJECT_ROOT
from .registry import tool


def _press(key: str, times: int = 1) -> None:
    import pyautogui

    for _ in range(times):
        pyautogui.press(key)


@tool(
    group="system",
    description="Change the system volume. Use direction up/down, or set an exact level.",
    parameters={
        "direction": {
            "type": "string",
            "enum": ["up", "down", "mute", "unmute", "set"],
            "description": "What to do to the volume.",
        },
        "amount": {
            "type": "integer",
            "description": "Steps for up/down (default 5), or 0-100 when direction is 'set'.",
        },
    },
    required=["direction"],
)
def set_volume(direction: str, amount: int = 0) -> str:
    direction = direction.lower()

    if direction in ("mute", "unmute"):
        _press("volumemute")
        return "Muted." if direction == "mute" else "Unmuted."

    if direction == "set":
        level = max(0, min(100, int(amount)))
        # Windows volume moves in 2% steps: floor to 0, then step up.
        _press("volumedown", 50)
        _press("volumeup", round(level / 2))
        return f"Volume set to about {level} percent."

    steps = int(amount) if amount else 5
    _press("volumeup" if direction == "up" else "volumedown", steps)
    return f"Volume {direction}."


@tool(
    group="system",
    description="Control media playback in whatever app is playing.",
    parameters={
        "action": {
            "type": "string",
            "enum": ["play", "pause", "playpause", "next", "previous", "stop"],
            "description": "The playback action.",
        }
    },
    required=["action"],
)
def media_control(action: str) -> str:
    keys = {
        "play": "playpause",
        "pause": "playpause",
        "playpause": "playpause",
        "next": "nexttrack",
        "previous": "prevtrack",
        "stop": "stop",
    }
    key = keys.get(action.lower())
    if not key:
        return f"Unknown media action '{action}'."
    _press(key)
    return f"Media: {action}."


@tool(group="system", description="Lock the Windows session.", confirm=True)
def lock_screen() -> str:
    if sys.platform != "win32":
        return "Locking is only wired up for Windows."
    subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False)
    return "Locking the screen."


@tool(
    group="system",
    description="Take a screenshot and save it. Returns the file path.",
    parameters={"filename": {"type": "string", "description": "Optional file name."}},
)
def take_screenshot(filename: str = "") -> str:
    import pyautogui

    folder = PROJECT_ROOT / "data" / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    name = filename or f"shot_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
    if not name.lower().endswith(".png"):
        name += ".png"
    path = folder / name
    pyautogui.screenshot().save(path)
    return f"Screenshot saved to {path}."


@tool(group="system", description="Report CPU, memory and battery status.")
def system_status() -> str:
    try:
        import psutil
    except ImportError:
        return "psutil isn't installed, so I can't read system status."

    cpu = psutil.cpu_percent(interval=0.4)
    mem = psutil.virtual_memory()
    parts = [f"CPU at {cpu:.0f} percent", f"memory at {mem.percent:.0f} percent"]
    battery = getattr(psutil, "sensors_battery", lambda: None)()
    if battery is not None:
        state = "charging" if battery.power_plugged else "on battery"
        parts.append(f"battery {battery.percent:.0f} percent, {state}")
    return ", ".join(parts) + "."
