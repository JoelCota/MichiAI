"""Launching programs and moving windows around."""

from __future__ import annotations

import subprocess
import sys

from .registry import tool


def _aliases(cfg) -> dict:
    return (cfg.get("tools.app_aliases", {}) if cfg else {}) or {}


@tool(
    group="apps",
    description=(
        "Open an application by name. Understands friendly names like 'browser', "
        "'spotify', 'code', or a full path to an executable."
    ),
    parameters={"app": {"type": "string", "description": "Name or path of the program."}},
    required=["app"],
)
def open_app(app: str, cfg=None) -> str:
    wanted = app.strip().lower()
    target = _aliases(cfg).get(wanted, app.strip())

    if sys.platform != "win32":
        return f"(non-Windows) would launch: {target}"

    try:
        # `start` resolves App Paths entries, Store apps and shell verbs.
        subprocess.Popen(
            ["cmd", "/c", "start", "", target],
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return f"Opening {app}."
    except Exception as exc:
        return f"Couldn't open {app}: {exc}"


@tool(group="apps", description="List the titles of currently open windows.")
def list_windows() -> str:
    try:
        import pygetwindow as gw
    except ImportError:
        return "pygetwindow isn't installed."

    titles = [t for t in gw.getAllTitles() if t and t.strip()]
    if not titles:
        return "No open windows found."
    return "Open windows: " + "; ".join(titles[:15])


@tool(
    group="apps",
    description="Bring a window to the front by (partial) title.",
    parameters={"title": {"type": "string", "description": "Part of the window title."}},
    required=["title"],
)
def focus_window(title: str) -> str:
    try:
        import pygetwindow as gw
    except ImportError:
        return "pygetwindow isn't installed."

    needle = title.lower()
    for window in gw.getAllWindows():
        if window.title and needle in window.title.lower():
            try:
                if window.isMinimized:
                    window.restore()
                window.activate()
                return f"Focused {window.title}."
            except Exception as exc:
                return f"Found {window.title} but couldn't focus it: {exc}"
    return f"No window matching '{title}'."


@tool(
    group="apps",
    description="Close a window by (partial) title.",
    parameters={"title": {"type": "string", "description": "Part of the window title."}},
    required=["title"],
    confirm=True,
)
def close_window(title: str) -> str:
    try:
        import pygetwindow as gw
    except ImportError:
        return "pygetwindow isn't installed."

    needle = title.lower()
    for window in gw.getAllWindows():
        if window.title and needle in window.title.lower():
            name = window.title
            window.close()
            return f"Closed {name}."
    return f"No window matching '{title}'."


@tool(group="apps", description="Minimise every window and show the desktop.")
def show_desktop() -> str:
    import pyautogui

    pyautogui.hotkey("win", "d")
    return "Showing the desktop."
