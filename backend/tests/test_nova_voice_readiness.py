"""Offline readiness checks; no model download and no provider calls."""
from pathlib import Path
import voice_readiness


def test_missing_model_is_not_ready(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(voice_readiness.importlib.util, "find_spec", lambda name: None)
    status = voice_readiness.check(tmp_path / "missing")
    assert not status["model_directory_exists"]
    assert not status["ready_to_attempt_offline_inference"]


def test_empty_directory_is_not_ready(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(voice_readiness.importlib.util, "find_spec", lambda name: object())
    status = voice_readiness.check(tmp_path)
    assert status["model_directory_exists"]
    assert not status["model_directory_nonempty"]
    assert not status["ready_to_attempt_offline_inference"]


def test_preloaded_directory_and_package_are_reported(tmp_path: Path, monkeypatch):
    (tmp_path / "config.json").write_text("{}", encoding="utf8")
    monkeypatch.setattr(voice_readiness.importlib.util, "find_spec", lambda name: object())
    status = voice_readiness.check(tmp_path)
    assert not status["ready_to_attempt_offline_inference"]
    assert "kokoro-v1_0.pth" in status["missing_required_files"]
    assert "config.json" in status["model_files"]


def test_complete_file_set_and_dependencies_are_required(tmp_path: Path, monkeypatch):
    (tmp_path / "voices").mkdir()
    for filename in voice_readiness.REQUIRED_FILES:
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setattr(voice_readiness.importlib.util, "find_spec", lambda name: object())
    status = voice_readiness.check(tmp_path)
    assert status["missing_required_files"] == []
    assert not status["ready_to_attempt_offline_inference"]
    assert len(status["empty_required_files"]) == 3
    for filename in voice_readiness.REQUIRED_FILES:
        (tmp_path / filename).write_bytes(b"nonempty")
    assert voice_readiness.check(tmp_path)["ready_to_attempt_offline_inference"]
    monkeypatch.setattr(voice_readiness.importlib.util, "find_spec", lambda name: None if name == "torch" else object())
    assert not voice_readiness.check(tmp_path)["ready_to_attempt_offline_inference"]
    monkeypatch.setattr(voice_readiness.importlib.util, "find_spec", lambda name: None if name == "en_core_web_sm" else object())
    assert not voice_readiness.check(tmp_path)["ready_to_attempt_offline_inference"]
