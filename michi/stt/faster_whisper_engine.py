"""Local speech-to-text with faster-whisper. Free, private, no per-minute cost."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..config import PROJECT_ROOT
from ..logging_setup import get_logger
from .base import STTEngine

log = get_logger("stt")


def _pick_device(preference: str) -> tuple[str, str]:
    """Return (device, compute_type) — falls back to CPU int8 when CUDA is absent."""
    if preference in ("cpu", "cuda"):
        device = preference
    else:
        device = "cpu"
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                device = "cuda"
        except Exception:
            pass
    return device, ("float16" if device == "cuda" else "int8")


class FasterWhisperSTT(STTEngine):
    name = "faster_whisper"

    def __init__(self, cfg, model_override: str | None = None):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "faster-whisper isn't installed. Run: pip install faster-whisper"
            ) from exc

        section = cfg.section("stt.faster_whisper")
        model_name = model_override or section.get("model", "small.en")
        model_name = self._resolve_local(str(model_name))
        device, auto_compute = _pick_device(str(section.get("device", "auto")).lower())
        compute_type = section.get("compute_type", "auto")
        if compute_type in (None, "", "auto"):
            compute_type = auto_compute

        self.language = None if str(model_name).endswith(".en") else cfg.get("assistant.language", "en")

        log.info("Loading Whisper '%s' on %s (%s).", model_name, device, compute_type)
        self.model = WhisperModel(model_name, device=device, compute_type=compute_type)

    @staticmethod
    def _resolve_local(model_name: str) -> str:
        """Use a local model folder when one is configured/available.

        Model names (tiny.en, small.en, ...) go to HuggingFace as usual. Anything
        else is treated as a path relative to the project root — which also
        sidesteps HuggingFace entirely for machines with flaky access to it.
        """
        candidate = Path(model_name)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        return str(candidate) if candidate.is_dir() else model_name

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if audio is None or len(audio) < sample_rate * 0.2:
            return ""
        audio = np.asarray(audio, dtype=np.float32)

        segments, _info = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
