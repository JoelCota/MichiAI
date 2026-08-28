"""Microsoft Edge neural voices — free, high quality, needs an internet connection."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from .base import TTSEngine, play_audio_file


class EdgeTTS(TTSEngine):
    name = "edge"

    def __init__(self, cfg):
        try:
            import edge_tts  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("edge-tts isn't installed. Run: pip install edge-tts") from exc

        section = cfg.section("tts.edge")
        language = str(cfg.get("assistant.language", "en")).lower()
        default_voice = "es-MX-DaliaNeural" if language.startswith("es") else "en-US-AriaNeural"
        self.voice = section.get("voice") or default_voice
        self.rate = section.get("rate", "+0%")

    async def _synthesize(self, text: str, out_path: str) -> None:
        import edge_tts

        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
        await communicate.save(out_path)

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        tmp = Path(tempfile.gettempdir()) / "michi_speech.mp3"
        asyncio.run(self._synthesize(text, str(tmp)))
        play_audio_file(tmp)

    @staticmethod
    def list_voices(prefix: str = "") -> str:
        import edge_tts

        voices = asyncio.run(edge_tts.list_voices())
        names = sorted(v["ShortName"] for v in voices)
        if prefix:
            names = [n for n in names if n.lower().startswith(prefix.lower())]
        return "\n".join(f"  {n}" for n in names)
