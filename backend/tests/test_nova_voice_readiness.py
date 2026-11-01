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
    assert status["ready_to_attempt_offline_inference"]
    assert "config.json" in status["model_files"]
