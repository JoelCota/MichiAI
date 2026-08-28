from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class STTEngine(ABC):
    name = "stt"

    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Return the recognised text, or '' if nothing intelligible was said."""
