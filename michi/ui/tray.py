"""System tray icon: shows what Michi is doing and lets you pause or quit her.

Optional — if pystray/Pillow aren't installed, Michi logs a note and runs headless.
"""

from __future__ import annotations

import threading

from ..config import PROJECT_ROOT
from ..events import BUS, State
from ..logging_setup import get_logger
from ..runtime import is_paused, request_shutdown, resume, pause

log = get_logger("tray")

# Dot colour per state — readable against both light and dark taskbars.
COLOURS = {
    State.STARTING: (150, 150, 150),
    State.IDLE: (90, 160, 250),
    State.LISTENING: (60, 200, 120),
    State.THINKING: (245, 180, 60),
    State.SPEAKING: (170, 120, 245),
    State.PAUSED: (120, 120, 120),
    State.ERROR: (230, 80, 80),
}


class TrayIcon:
    def __init__(self, assistant):
        import pystray  # noqa: F401  (import here so absence is a soft failure)
        from PIL import Image  # noqa: F401

        self.assistant = assistant
        self.name = assistant.name
        self._icon = None
        self._thread: threading.Thread | None = None

    # -- drawing -----------------------------------------------------------
    @staticmethod
    def _image(state: State):
        from PIL import Image, ImageDraw

        size = 64
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        colour = COLOURS.get(state, COLOURS[State.IDLE])

        draw.ellipse([4, 4, size - 4, size - 4], fill=colour + (255,))
        if state == State.PAUSED:  # two pause bars
            draw.rectangle([23, 20, 29, 44], fill=(255, 255, 255, 235))
            draw.rectangle([35, 20, 41, 44], fill=(255, 255, 255, 235))
        elif state == State.LISTENING:  # inner ring
            draw.ellipse([18, 18, size - 18, size - 18], outline=(255, 255, 255, 235), width=4)
        elif state == State.SPEAKING:  # small centred dot
            draw.ellipse([26, 26, size - 26, size - 26], fill=(255, 255, 255, 235))
        return image

    # -- menu actions ------------------------------------------------------
    def _toggle_pause(self, *_):
        if is_paused():
            resume()
            BUS.set_state(State.IDLE)
        else:
            pause()
            BUS.set_state(State.PAUSED)
        self._refresh(BUS.state, BUS.detail)

    def _open_folder(self, *_):
        import subprocess
        import sys

        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(PROJECT_ROOT)])

    def _quit(self, *_):
        request_shutdown()
        try:
            self.assistant.speaker.interrupt()
        except Exception:
            pass
        if self._icon is not None:
            self._icon.stop()

    # -- lifecycle ---------------------------------------------------------
    def _refresh(self, state: State, detail: str = "") -> None:
        if self._icon is None:
            return
        try:
            self._icon.icon = self._image(state)
            suffix = f" — {detail}" if detail else ""
            self._icon.title = f"{self.name}: {state.label}{suffix}"[:127]
            self._icon.update_menu()
        except Exception:
            log.debug("Tray refresh failed", exc_info=True)

    def start(self) -> None:
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem(lambda _: f"{self.name}: {BUS.state.label}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: "Resume listening" if is_paused() else "Pause listening",
                self._toggle_pause,
            ),
            pystray.MenuItem("Open Michi folder", self._open_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

        self._icon = pystray.Icon(
            "michi", self._image(BUS.state), f"{self.name}: {BUS.state.label}", menu
        )
        BUS.subscribe(self._refresh)

        self._thread = threading.Thread(target=self._icon.run, name="michi-tray", daemon=True)
        self._thread.start()
        log.info("Tray icon running.")

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
