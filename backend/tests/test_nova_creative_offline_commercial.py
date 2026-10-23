"""Offline 30s montage and first-party Nova click destinations. No paid providers."""

from __future__ import annotations

import shutil

import pytest

from app.core.nova.creative_studio.click_destinations import (
    classify_destination,
    replacement_pack,
    tracked_nova_url,
    verify_click_destination,
)
from app.core.nova.creative_studio.export import export_project_package
from app.core.nova.creative_studio.service import CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore


def test_profile_links_reject_platform_homes_and_aggregators():
    tiktok = tracked_nova_url("TikTok")
    instagram = tracked_nova_url("Instagram")
    assert classify_destination(tiktok) == "first_party_nova"
    assert classify_destination(instagram) == "first_party_nova"
    assert "utm_source=tiktok" in tiktok
    assert "utm_source=instagram" in instagram
    assert "/nova-today/" in tiktok
    assert classify_destination("https://www.tiktok.com/") == "platform_home"
    assert classify_destination("https://www.instagram.com/") == "platform_home"
    assert classify_destination("https://linktr.ee/amicor") == "aggregator"
    assert classify_destination("getamicor.com") == "bare_text"
    pack = replacement_pack("TikTok")
    assert pack["publish"] is False
    assert pack["connected_account_audit"]["post_ids"] == []
    assert pack["connected_account_audit"]["posts_read"] is False
    assert "not clickable" in pack["platform_limits"].lower()


def test_click_through_accepts_only_a_nova_product_200():
    url = tracked_nova_url("Instagram")

    def ok_fetch(current: str):
        assert current == url
        return 200, None

    verified = verify_click_destination(url, fetch=ok_fetch)
    assert verified["verified"] is True
    assert verified["classification"] == "first_party_nova"

    def home_redirect(current: str):
        if "nova-today" in current:
            return 302, "https://www.instagram.com/"
        return 200, None

    diverted = verify_click_destination(url, fetch=home_redirect)
    assert diverted["verified"] is False
    assert diverted["classification"] == "platform_home"


def test_export_holds_green_until_license_audio_captions_and_click_through_pass():
    payload = {
        "project": {"title": "Montage", "platform": "TikTok", "status": "ACTIVE"},
        "brief": {},
        "brand": {},
        "scenes": [],
        "assets": [
            {
                "id": "vid",
                "kind": "video",
                "title": "Offline",
                "status": "GENERATED",
                "url": "/media/offline.mp4",
                "metadata": {
                    "final_promo": True,
                    "render_mode": "offline_montage_not_lipsync",
                    "captions_burned_in": True,
                    "audio_present": True,
                    "duration_seconds": 30,
                    "license_status": "AMBER",
                    "click_destination": {
                        "website_field_url": tracked_nova_url("TikTok"),
                        "http_status": 200,
                        "verified": True,
                    },
                },
            }
        ],
    }
    social = export_project_package(payload)["package"]["social_media_package"]
    assert social["production_ready"] is False
    assert social["offline_montage"] is True
    assert social["readiness"]["audio"] == "GREEN"
    assert social["readiness"]["captions"] == "GREEN"
    assert social["readiness"]["click_through"] == "GREEN"
    assert social["readiness"]["license"] == "AMBER"
    assert social["readiness"]["overall"] == "AMBER"
    assert social["readiness"]["public_publish"] == "HOLD"
    assert social["readiness"]["lip_sync_presenter"] == "RED"
    assert social["commercial_complete"] is False


@pytest.mark.skipif(shutil.which("espeak-ng") is None and shutil.which("espeak") is None, reason="local narration engine is not installed")
def test_offline_thirty_second_montage_is_downloadable_and_not_a_paid_render(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")

    def forbid_paid(*_args, **_kwargs):
        raise AssertionError("paid provider was called")

    monkeypatch.setattr(
        "app.core.nova.creative_studio.providers.OpenAIVoiceProvider.generate",
        forbid_paid,
    )
    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project(
        "owner-offline",
        {
            "title": "AMICOR Nova 30s commercial",
            "project_type": "short_video",
            "platform": "TikTok",
            "duration_target": 30,
        },
    )
    board = svc.generate_storyboard("owner-offline", project["id"])
    assert len(board["scenes"]) == 6
    rendered = svc.render_offline_commercial("owner-offline", project["id"])
    meta = rendered["asset"]["metadata"]
    assert meta["paid_provider_charges"] is False
    assert meta["lip_sync"] is False
    assert meta["presenter"] is False
    assert meta["presenter_used"] is False
    assert meta["quality_state"] == "PREVIEW_ONLY"
    assert meta["pipeline"] == "offline_title_card_fallback"
    assert meta["commercial_complete"] is False
    assert rendered["pipeline"] == "offline_title_card_fallback"
    assert rendered["commercial_complete"] is False
    assert meta["publish_ready"] is False
    assert meta["captions_burned_in"] is True
    assert meta["audio_present"] is True
    assert meta["commercial_slideshow"] is False
    assert 28.0 <= float(meta["duration_seconds"]) <= 32.0
    assert meta["license_status"] == "AMBER"
    assert meta["click_destination"]["classification"] == "first_party_nova"
    assert meta["click_destination"]["publish"] is False
    video = tmp_path / rendered["url"].rsplit("/", 1)[-1]
    captions = video.with_suffix(".srt")
    audio = tmp_path / rendered["audio"]["url"].rsplit("/", 1)[-1]
    assert video.is_file() and video.stat().st_size > 20000
    assert audio.is_file() and audio.stat().st_size > 1000
    assert "getamicor.com" in captions.read_text(encoding="utf-8").lower()
