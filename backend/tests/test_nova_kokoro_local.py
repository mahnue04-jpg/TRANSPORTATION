"""Offline Kokoro adapter tests with a fake model; no audio provider or download."""
import wave
from pathlib import Path
import pytest
from kokoro_local import KokoroLocalBackend
from local_voice import VoiceRequest, VoiceNotReady


def test_fake_kokoro_pipeline_produces_real_pcm_wav(tmp_path: Path):
    received = {}
    def fake_pipeline(script, voice):
        received.update(script=script, voice=voice)
        yield ("text", "phonemes", [0.0, 0.5, -0.5] * 800)
    path = KokoroLocalBackend(fake_pipeline).generate_wav(
        VoiceRequest("Welcome to AMICOR Nova"), tmp_path / "voice.wav"
    )
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 24000
        assert wav.getnframes() == 2400
    assert received == {"script": "Welcome to [AMICOR](/ˈɑmɪkɔɹ/) Nova", "voice": "af_heart"}


def test_missing_local_model_fails_closed(tmp_path: Path):
    with pytest.raises(VoiceNotReady):
        KokoroLocalBackend().generate_wav(VoiceRequest("Hello"), tmp_path / "x.wav")
    assert not (tmp_path / "x.wav").exists()


def test_empty_audio_fails_without_output(tmp_path: Path):
    with pytest.raises(VoiceNotReady):
        KokoroLocalBackend(lambda text, voice: iter([])).generate_wav(
            VoiceRequest("Hello"), tmp_path / "x.wav"
        )
    assert not (tmp_path / "x.wav").exists()


def test_reviewed_speed_reaches_model_without_changing_written_script(tmp_path):
    received = {}
    def pipeline(text, **kwargs):
        received.update(text=text, **kwargs)
        yield ("text", "phonemes", [0.25, -0.25] * 1200)
    KokoroLocalBackend(pipeline).generate_wav(
        VoiceRequest("Meet AMICOR", speed=0.87), tmp_path / "voice.wav"
    )
    assert received == {"text": "Meet [AMICOR](/ˈɑmɪkɔɹ/)", "voice": "af_heart", "speed": 0.87}
