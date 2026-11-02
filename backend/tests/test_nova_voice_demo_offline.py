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


def test_demo_rejects_incomplete_model_before_import(tmp_path: Path, monkeypatch):
    import sys
    import local_voice_demo
    model = tmp_path / "incomplete-model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.delitem(sys.modules, "kokoro", raising=False)
    monkeypatch.setattr(local_voice_demo, "check_voice_readiness",
                        lambda _: {"ready_to_attempt_offline_inference": False})
    with pytest.raises(VoiceNotReady, match="missing or empty"):
        run(model_dir=model, output=tmp_path / "voice.wav")
    assert "kokoro" not in sys.modules
    assert not (tmp_path / "voice.wav").exists()


def test_worker_rejects_unreviewed_model_weights_before_import(tmp_path, monkeypatch):
    import local_voice_demo
    model = tmp_path / "model"
    model.mkdir()
    (model / "kokoro-v1_0.pth").write_bytes(b"unreviewed weights")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setattr(local_voice_demo, "check_voice_readiness", lambda _: {"ready_to_attempt_offline_inference": True})
    with pytest.raises(VoiceNotReady, match="checksum"):
        run(model_dir=model, output=tmp_path / "voice.wav", verify_model=True)
    assert not (tmp_path / "voice.wav").exists()


def test_empty_custom_script_is_not_replaced_by_demo_greeting(tmp_path):
    with pytest.raises(ValueError):
        run(model_dir=tmp_path, output=tmp_path / "voice.wav", script="")
