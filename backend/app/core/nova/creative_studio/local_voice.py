"""Local-only Nova Voice adapter contract.

No import-time downloads, external APIs, purchases, or model execution.
A real inference backend is intentionally not connected until feasibility QA.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class VoiceNotReady(RuntimeError):
    pass


@dataclass(frozen=True)
class VoiceRequest:
    text: str
    speaker: str = "professional_female"
    sample_rate: int = 24000

    def validate(self) -> None:
        if not self.text.strip() or len(self.text) > 1600:
            raise ValueError("narration must contain 1–1600 characters")
        if self.sample_rate not in (22050, 24000, 44100, 48000):
            raise ValueError("unsupported sample rate")


def spoken_text(script: str) -> str:
    """Audio-only brand pronunciation; never alter captions or saved script."""
    import re
    return re.sub(r"\bAMICOR\b", "Ammy Core", script, flags=re.IGNORECASE)


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
