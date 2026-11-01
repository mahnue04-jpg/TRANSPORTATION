"""Offline quality checks for generated WAV narration."""
from array import array
from pathlib import Path
import wave
from narration_qa import inspect_narration_wav


def write_sample(path: Path, samples: list[int], rate: int = 24000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(array("h", samples).tobytes())


def test_short_non_silent_wav_is_accepted(tmp_path: Path):
    output = tmp_path / "sample.wav"
    write_sample(output, [10000, -10000] * 1200)
    report = inspect_narration_wav(output)
    assert report.valid_for_narration
    assert report.seconds == 0.1


def test_silent_wav_is_not_accepted(tmp_path: Path):
    output = tmp_path / "silent.wav"
    write_sample(output, [0] * 2400)
    assert not inspect_narration_wav(output).valid_for_narration


def test_excess_duration_is_rejected(tmp_path: Path):
    output = tmp_path / "long.wav"
    write_sample(output, [3000] * 24000)
    assert not inspect_narration_wav(output, max_seconds=0.5).valid_for_narration
