"""No-network integration test of the explicit offline speech runner.

A fake Kokoro pipeline exercises the same runner path without downloading weights.
"""
import sys
import types
import wave
from pathlib import Path

import local_voice_demo
from local_voice_demo import run


def test_offline_demo_writes_wav_from_preloaded_pipeline(tmp_path: Path, monkeypatch):
    model_dir = tmp_path / "cached-model"
    model_dir.mkdir()
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setattr(local_voice_demo, "check_voice_readiness", lambda _: {"ready_to_attempt_offline_inference": True})
    called = {}

    class FakeModel:
        def __init__(self, **kwargs):
            called["model_config"] = kwargs["config"]
            called["model_weights"] = kwargs["model"]
        def to(self, _): return self
        def eval(self): return self

    class FakePipeline:
        def __init__(self, lang_code, repo_id, model=None, device=None):
            self.voices = {}
            called["lang_code"] = lang_code
            called["repo_id"] = repo_id

        def __call__(self, text, voice):
            called["text"] = text
            called["voice"] = voice
            yield ("text", "phonemes", [0.25, -0.25] * 2400)

    monkeypatch.setitem(sys.modules, "kokoro", types.SimpleNamespace(KPipeline=FakePipeline, KModel=FakeModel))
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(load=lambda *args, **kwargs: [1]))
    output = tmp_path / "demo.wav"
    result = run(model_dir=model_dir, output=output)
    assert output.exists()
    assert result["quality_check"] is True
    assert called == {
        "model_config": str(model_dir / "config.json"),
        "model_weights": str(model_dir / "kokoro-v1_0.pth"),
        "lang_code": "a",
        "repo_id": "hexgrad/Kokoro-82M",
        "text": "Welcome to Ammy Core Nova, your AI business assistant.",
        "voice": "af_heart",
    }
    with wave.open(str(output), "rb") as wav:
        assert wav.getframerate() == 24000
        assert wav.getnframes() == 4800
