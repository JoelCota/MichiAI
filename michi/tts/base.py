from __future__ import annotations

import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from ..logging_setup import get_logger

log = get_logger("tts")


def stop_playback() -> None:
    """Cut off whatever sounddevice is currently playing (barge-in)."""
    try:
        import sounddevice as sd

        sd.stop()
    except Exception:
        pass


class TTSEngine(ABC):
    name = "tts"

    @abstractmethod
    def speak(self, text: str) -> None:
        """Say `text` out loud, blocking until finished."""

    def stop(self) -> None:
        """Interrupt playback. Engines that render to a file get this for free."""
        stop_playback()


def play_audio_file(path: str | Path) -> None:
    """Play a wav/mp3 file. Tries soundfile+sounddevice, falls back to Windows."""
    path = str(path)
    try:
        import sounddevice as sd
        import soundfile as sf

        data, samplerate = sf.read(path, dtype="float32")
        sd.play(data, samplerate)
        sd.wait()
        return
    except Exception as exc:
        log.debug("soundfile playback failed (%s) — falling back.", exc)

    if sys.platform == "win32":
        escaped = path.replace("'", "''")
        script = (
            "Add-Type -AssemblyName presentationCore; "
            "$p = New-Object System.Windows.Media.MediaPlayer; "
            f"$p.Open([uri]'{escaped}'); $p.Play(); "
            "Start-Sleep -Milliseconds 400; "
            "while($p.NaturalDuration.HasTimeSpan -and "
            "$p.Position -lt $p.NaturalDuration.TimeSpan){Start-Sleep -Milliseconds 100}"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        log.warning("No playback backend available for %s", path)
