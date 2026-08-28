"""Piper — offline neural voices. Download piper.exe and a .onnx voice first.

    https://github.com/rhasspy/piper/releases   (piper_windows_amd64.zip -> ./piper/)
    https://huggingface.co/rhasspy/piper-voices (a .onnx + .onnx.json -> ./models/voices/)
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .base import TTSEngine, play_audio_file


class PiperTTS(TTSEngine):
    name = "piper"

    def __init__(self, cfg):
        section = cfg.section("tts.piper")
        self.exe = cfg.resolve_path(section.get("exe_path", "piper/piper.exe"))
        self.model = cfg.resolve_path(section.get("model_path", ""))

        if not self.exe.exists():
            raise RuntimeError(
                f"Piper executable not found at {self.exe}. Download it from "
                "https://github.com/rhasspy/piper/releases, or switch tts.engine to 'sapi'."
            )
        if not self.model.exists():
            raise RuntimeError(
                f"Piper voice not found at {self.model}. Grab one from "
                "https://huggingface.co/rhasspy/piper-voices"
            )

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        out = Path(tempfile.gettempdir()) / "michi_speech.wav"
        subprocess.run(
            [str(self.exe), "--model", str(self.model), "--output_file", str(out)],
            input=text.encode("utf-8"),
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if out.exists():
            play_audio_file(out)
