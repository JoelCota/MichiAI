"""Cloud transcription over any OpenAI-compatible /audio/transcriptions endpoint."""

from __future__ import annotations

import io

import numpy as np

from .base import STTEngine


class OpenAIWhisperSTT(STTEngine):
    name = "openai_api"

    def __init__(self, cfg):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("openai isn't installed. Run: pip install openai") from exc

        section = cfg.section("stt.openai_api")
        api_key = section.get("api_key", "")
        if not api_key or str(api_key).startswith("<<MISSING"):
            raise RuntimeError("The API-based STT engine needs OPENAI_API_KEY in your .env.")

        kwargs = {"api_key": api_key}
        if section.get("base_url"):
            kwargs["base_url"] = section["base_url"].rstrip("/")
        self.client = OpenAI(**kwargs)
        self.model = section.get("model", "whisper-1")
        self.language = cfg.get("assistant.language", "en")

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if audio is None or len(audio) < sample_rate * 0.2:
            return ""

        import soundfile as sf

        buffer = io.BytesIO()
        sf.write(buffer, np.asarray(audio, dtype=np.float32), sample_rate, format="WAV")
        buffer.seek(0)
        buffer.name = "speech.wav"

        response = self.client.audio.transcriptions.create(
            model=self.model, file=buffer, language=self.language
        )
        return (getattr(response, "text", "") or "").strip()
