"""Windows' built-in voices via pyttsx3. Zero install, works offline, sounds robotic."""

from __future__ import annotations

from ..logging_setup import get_logger
from .base import TTSEngine

log = get_logger("tts")


class SapiTTS(TTSEngine):
    name = "sapi"

    def __init__(self, cfg):
        try:
            import pyttsx3  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pyttsx3 isn't installed. Run: pip install pyttsx3") from exc

        section = cfg.section("tts.sapi")
        self.voice_hint = str(section.get("voice", "") or "")
        self.rate = int(section.get("rate", 190))
        self._current = None
        # Fail fast at startup rather than mid-conversation.
        self._build()

    def _build(self):
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", self.rate)
        if self.voice_hint:
            needle = self.voice_hint.lower()
            for voice in engine.getProperty("voices"):
                if needle in voice.name.lower() or needle in str(voice.id).lower():
                    engine.setProperty("voice", voice.id)
                    break
            else:
                log.warning("No SAPI voice matching '%s' — using the default.", self.voice_hint)
        return engine

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        # A fresh engine per utterance: pyttsx3's run loop is not reliably reusable.
        engine = self._build()
        self._current = engine
        try:
            engine.say(text)
            engine.runAndWait()
        finally:
            self._current = None
            try:
                engine.stop()
            except Exception:
                pass

    def stop(self) -> None:
        engine = self._current
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass

    @staticmethod
    def list_voices() -> str:
        import pyttsx3

        engine = pyttsx3.init()
        return "\n".join(f"  {v.name}" for v in engine.getProperty("voices"))
