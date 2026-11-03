"""Local-only Nova Voice adapter contract.

No import-time downloads, external APIs, purchases, or model execution.
Studio integration is opt-in; importing this contract never loads a model.
"""
from dataclasses import dataclass
from pathlib import Path
import math
from typing import Protocol


class VoiceNotReady(RuntimeError):
    pass


@dataclass(frozen=True)
class VoiceRequest:
    text: str
    speaker: str = "professional_female"
    sample_rate: int = 24000
    speed: float = 1.0

    def validate(self) -> None:
        if not self.text.strip() or len(self.text) > 1600:
            raise ValueError("narration must contain 1–1600 characters")
        if self.sample_rate not in (22050, 24000, 44100, 48000):
            raise ValueError("unsupported sample rate")
        if not math.isfinite(self.speed) or not 0.5 <= self.speed <= 2.0:
            raise ValueError("speed must be between 0.5 and 2.0")


def spoken_text(script: str) -> str:
    """Audio-only brand pronunciation; never alter captions or saved script."""
    import re
    brand = "Amih-core"
    # Owner approved this literal spelling in the latest short Kokoro sample.
    # The written script and captions keep their original spelling.
    return re.sub(
        r"\bGetAmiCore?\.com\b|\bAMICOR\b",
        lambda match: "Get " + brand + " dot com" if "." in match.group(0) else brand,
        script,
        flags=re.IGNORECASE,
    )


class LocalVoiceBackend(Protocol):
    def generate_wav(self, request: VoiceRequest, destination: Path) -> Path:
        """Write actual PCM WAV audio locally or raise VoiceNotReady."""


class UnconfiguredLocalVoiceBackend:
    def generate_wav(self, request: VoiceRequest, destination: Path) -> Path:
        request.validate()
        raise VoiceNotReady(
            "No AMICOR-operated speech model is installed. "
            "No external service was called and no audio was generated."
        )
