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
    assert received == {"script": "Welcome to Amih-core Nova", "voice": "af_heart"}


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
    assert received == {"text": "Meet Amih-core", "voice": "af_heart", "speed": 0.87}


def test_native_timings_use_concatenated_pcm_offsets_and_approved_brand(tmp_path):
    import json
    from types import SimpleNamespace
    class Chunk:
        def __init__(self, text):
            self.tokens = [SimpleNamespace(text=text, start_ts=0, end_ts=.1)]
        def __iter__(self):
            return iter(("text", "phones", [.25, -.25] * 1200))
    def pipeline(text, voice):
        yield Chunk("Hello")
        yield Chunk("Amih-core")
    target, timing = tmp_path / "voice.wav", tmp_path / "timing.json"
    KokoroLocalBackend(pipeline).generate_wav(VoiceRequest("Hello AMICOR"), target,
                                            alignment_output=timing)
    result = json.loads(timing.read_text())
    assert result["alignment_available"] is True
    assert result["words"] == [{"word": "Hello", "start": 0, "end": .1},
                               {"word": "AMICOR", "start": .1, "end": .2}]


def test_legacy_audio_without_native_timings_does_not_invent_captions(tmp_path):
    import json
    target, timing = tmp_path / "voice.wav", tmp_path / "timing.json"
    KokoroLocalBackend(lambda *_args, **_kwargs: iter([("", "", [.2] * 2400)])).generate_wav(
        VoiceRequest("Hello"), target, alignment_output=timing)
    assert target.exists() and json.loads(timing.read_text())["alignment_available"] is False
