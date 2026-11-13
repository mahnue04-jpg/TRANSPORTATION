"""Read-only WAV quality report for locally generated Nova narration.

Uses Python standard library; never calls AI providers or downloads models.
"""
from dataclasses import asdict, dataclass
from pathlib import Path
import audioop
import wave


@dataclass(frozen=True)
class WavReport:
    path: str
    seconds: float
    sample_rate: int
    channels: int
    sample_width_bytes: int
    peak_fraction: float
    valid_for_narration: bool


def inspect_narration_wav(path: str | Path, *, max_seconds: float = 32.0) -> WavReport:
    src = Path(path)
    with wave.open(str(src), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.getnframes()
        data = wav.readframes(frames)
    seconds = frames / rate if rate else 0.0
    peak = audioop.max(data, sample_width) if data else 0
    max_pcm = float(2 ** (8 * sample_width - 1))
    level = peak / max_pcm if max_pcm else 0.0
    return WavReport(
        path=str(src), seconds=round(seconds, 3), sample_rate=rate,
        channels=channels, sample_width_bytes=sample_width,
        peak_fraction=round(level, 4),
        valid_for_narration=(0 < seconds <= max_seconds and channels == 1
                             and sample_width == 2 and rate == 24000
                             and level > 0.001),
    )
