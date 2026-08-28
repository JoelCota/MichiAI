"""Cloud TTS over any OpenAI-compatible /audio/speech endpoint."""

from __future__ import annotations

import tempfile
from pathlib import Path

from .base import TTSEngine, play_audio_file


class OpenAITTS(TTSEngine):
    name = "openai_api"

    def __init__(self, cfg):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("openai isn't installed. Run: pip install openai") from exc

        section = cfg.section("tts.openai_api")
        api_key = section.get("api_key", "")
        if not api_key or str(api_key).startswith("<<MISSING"):
            raise RuntimeError("API-based TTS needs OPENAI_API_KEY in your .env.")

        kwargs = {"api_key": api_key}
        if section.get("base_url"):
            kwargs["base_url"] = section["base_url"].rstrip("/")
        self.client = OpenAI(**kwargs)
        self.model = section.get("model", "gpt-4o-mini-tts")
        self.voice = section.get("voice", "alloy")

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        out = Path(tempfile.gettempdir()) / "michi_speech.wav"
        with self.client.audio.speech.with_streaming_response.create(
            model=self.model, voice=self.voice, input=text, response_format="wav"
        ) as response:
            response.stream_to_file(out)
        play_audio_file(out)
