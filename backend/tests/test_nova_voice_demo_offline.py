"""Verify the demo fails before importing model dependencies when offline is disabled."""
from pathlib import Path
import pytest
from local_voice_demo import run
from local_voice import VoiceNotReady


def test_demo_requires_offline_environment_before_model_import(tmp_path: Path, monkeypatch):
    model = tmp_path / "model"
    model.mkdir()
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    with pytest.raises(VoiceNotReady, match="HF_HUB_OFFLINE=1"):
        run(model_dir=model, output=tmp_path / "voice.wav")
    assert not (tmp_path / "voice.wav").exists()


def test_demo_rejects_missing_model_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    with pytest.raises(VoiceNotReady, match="directory is missing"):
        run(model_dir=tmp_path / "missing", output=tmp_path / "voice.wav")
