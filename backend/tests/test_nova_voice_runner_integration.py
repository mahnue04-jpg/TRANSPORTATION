"""No-network integration test of the explicit offline speech runner.

A fake Kokoro pipeline exercises the same runner path without downloading weights.
"""
import sys
import types
import wave
from pathlib import Path

from local_voice_demo import run


def test_offline_demo_writes_wav_from_preloaded_pipeline(tmp_path: Path, monkeypatch):
    model_dir = tmp_path / "cached-model"
    model_dir.mkdir()
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    called = {}

    class FakePipeline:
        def __init__(self, lang_code, repo_id):
            called["lang_code"] = lang_code
            called["repo_id"] = repo_id

        def __call__(self, text, voice):
            called["text"] = text
            called["voice"] = voice
            yield ("text", "phonemes", [0.25, -0.25] * 2400)

    monkeypatch.setitem(sys.modules, "kokoro", types.SimpleNamespace(KPipeline=FakePipeline))
    output = tmp_path / "demo.wav"
    result = run(model_dir=model_dir, output=output)
    assert output.exists()
    assert result["quality_check"] is True
    assert called == {
        "lang_code": "a",
        "repo_id": str(model_dir),
        "text": "Welcome to Ammy Core Nova, your AI business assistant.",
        "voice": "af_heart",
    }
    with wave.open(str(output), "rb") as wav:
        assert wav.getframerate() == 24000
        assert wav.getnframes() == 4800
