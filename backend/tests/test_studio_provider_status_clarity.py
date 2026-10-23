"""Provider status names and media-root selection. No secret values. No paid calls."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.nova.creative_studio.providers import (
    approved_60s_demo_report,
    media_storage_report,
    provider_statuses,
)

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "sk-test-sentinel-must-not-leak"


def _blob() -> str:
    return json.dumps(provider_statuses(), sort_keys=True)


def test_missing_credentials_are_not_described_as_a_live_flag(monkeypatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "RUNWAYML_API_SECRET",
        "NOVA_CREATIVE_VIDEO_API_KEY",
        "FAL_KEY",
        "DID_API_KEY",
        "NOVA_CREATIVE_IMAGE_LIVE_ENABLED",
        "NOVA_CREATIVE_VOICE_LIVE_ENABLED",
        "NOVA_CREATIVE_VIDEO_LIVE_ENABLED",
        "NOVA_CREATIVE_TALKING_PRESENTER_LIVE_ENABLED",
        "NOVA_CREATIVE_KLING_LIVE_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_PROVIDER", "runway")
    rows = {row["kind"]: row for row in provider_statuses()}
    for kind in ("image", "voice", "video", "talking_presenter"):
        assert rows[kind]["status"] == "CONFIG_REQUIRED"
        assert rows[kind]["configured"] is False
        assert rows[kind]["block_reason"] == "credential_missing"
    assert rows["image"]["credential_env_names"] == ["OPENAI_API_KEY"]
    assert rows["image"]["live_flag_names"] == ["NOVA_CREATIVE_IMAGE_LIVE_ENABLED"]
    assert "RUNWAYML_API_SECRET" in rows["video"]["credential_env_names"]
    assert rows["talking_presenter"]["credential_env_names"] == ["DID_API_KEY"]
    assert SENTINEL not in _blob()


def test_present_credential_with_live_flag_off_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SENTINEL)
    monkeypatch.delenv("NOVA_CREATIVE_IMAGE_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("NOVA_CREATIVE_VOICE_LIVE_ENABLED", raising=False)
    rows = {row["kind"]: row for row in provider_statuses()}
    for kind in ("image", "voice"):
        assert rows[kind]["status"] == "DISABLED"
        assert rows[kind]["configured"] is True
        assert rows[kind]["block_reason"] == "live_flag_off"
    assert SENTINEL not in _blob()
    assert SENTINEL not in rows["image"]["message"]


def test_custom_media_dir_is_not_echoed(monkeypatch, tmp_path: Path) -> None:
    secret_path = tmp_path / "secret-media-root"
    secret_path.mkdir()
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(secret_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    report = media_storage_report()
    encoded = json.dumps(report)
    assert report["selection"] == "configured"
    assert report["path"] == "custom"
    assert report["env_present"]["NOVA_CREATIVE_MEDIA_DIR"] is True
    assert str(secret_path) not in encoded


def test_status_ui_names_the_block_and_keeps_commercial_complete_off() -> None:
    script = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    html = (ROOT / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")
    assert "studio-provider-status-20261023" in html
    assert "Credential missing" in script
    assert "A live flag is not the cause." in script
    assert "Live flag is off" in script
    assert "container static directory. Files here disappear on deploy." in script
    assert "The asset record is no longer in this project" in script
    assert "Commercial complete stays off." in script
    assert "regenerate the file" in script


def test_approved_60s_demo_is_saved_playback_not_a_provider_call() -> None:
    demo = (ROOT / "static" / "nova-one-minute-demo" / "index.html").read_text(encoding="utf-8")
    studio = (ROOT / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")
    report = approved_60s_demo_report()
    assert report["mode"] == "static_playback"
    assert report["uses_live_providers"] is False
    assert report["provider_calls"] == []
    assert report["claims_lip_sync"] is False
    assert report["proves_studio_provider_configuration"] is False
    assert report["video_path"] in demo
    assert report["audio_path"] in demo
    assert "does not call the live image, video, voice, or talking-presenter providers" in studio
    assert "It does not claim lip-sync." in demo
