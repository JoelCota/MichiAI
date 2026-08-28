"""Clipboard access and typing into the focused window."""

from __future__ import annotations

from .registry import tool


@tool(group="clipboard", description="Read whatever text is currently on the clipboard.")
def read_clipboard() -> str:
    import pyperclip

    text = pyperclip.paste() or ""
    if not text.strip():
        return "The clipboard is empty."
    if len(text) > 4000:
        return text[:4000] + " ... (truncated)"
    return text


@tool(
    group="clipboard",
    description="Put text on the clipboard so the user can paste it.",
    parameters={"text": {"type": "string", "description": "Text to copy."}},
    required=["text"],
)
def write_clipboard(text: str) -> str:
    import pyperclip

    pyperclip.copy(text)
    return "Copied to the clipboard."


@tool(
    group="clipboard",
    description="Type text into whatever window currently has focus (dictation).",
    parameters={"text": {"type": "string", "description": "Text to type out."}},
    required=["text"],
)
def type_text(text: str) -> str:
    import time

    import pyautogui
    import pyperclip

    # Paste rather than keystroke-simulate: fast and handles accents correctly.
    previous = ""
    try:
        previous = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(text)
    time.sleep(0.05)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.15)
    if previous:
        try:
            pyperclip.copy(previous)
        except Exception:
            pass
    return "Typed it."
