"""Issue #344 — Nova Creative Studio commercial pipeline (non-billable)."""

from __future__ import annotations

from pathlib import Path

from app.core.nova.creative_studio.export import export_project_package
from app.core.nova.creative_studio.generation import assemble_short_video
from app.core.nova.creative_studio.preflight import accessible_balance_status, quote_project_render
from app.core.nova.creative_studio.presenter_media import even_spaced_cues, srt_text
from app.core.nova.creative_studio.service import CreativeStudioError, CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore


def test_thirty_second_storyboard_has_six_commercial_beats():
    board = assemble_short_video(
        topic="AMICOR Nova business services commercial",
        audience="small business owners",
        platform="TikTok",
        duration_target=30,
        style="modern professional",
        tone="clear and confident",
        cta="Visit getamicor.com to explore AMICOR Nova.",
        brand_name="AMICOR",
    )
    headings = [scene["heading"] for scene in board["scenes"]]
    assert headings == ["Hook", "Problem", "Capabilities", "Process", "Progress", "CTA"]
    assert abs(sum(float(scene["duration_seconds"]) for scene in board["scenes"]) - 30.0) < 0.01
    assert "getamicor.com" in board["final_cta"].lower()
    assert any("research" in scene["voiceover_text"].lower() for scene in board["scenes"])
    assert any("review" in scene["voiceover_text"].lower() for scene in board["scenes"])


def test_preflight_quote_never_enables_purchasing(monkeypatch):
    monkeypatch.delenv("NOVA_CREATIVE_OWNER_REPORTED_FAL_BALANCE_USD", raising=False)
    balance = accessible_balance_status()
    assert balance["status"] == "cannot_verify"
    assert balance["amount"] is None

    quote = quote_project_render(scene_count=6, duration_target=30)
    assert quote["purchasing_enabled"] is False
    assert quote["auto_top_up"] is False
    assert quote["requires_owner_budget_confirmation"] is True
    assert quote["estimated_total_usd"] > 0
    assert quote["scene_count"] == 6
    assert "fal_key_present" in quote["providers"]


def test_budget_confirmation_blocks_when_paid_not_allowed(monkeypatch):
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_PROVIDER", "fal")
    monkeypatch.setenv("FAL_KEY", "test-not-a-real-key")
    monkeypatch.setenv("NOVA_CREATIVE_OWNER_REPORTED_FAL_BALANCE_USD", "-3.16")

    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project(
        "owner-344",
        {
            "title": "Nova 30s commercial",
            "project_type": "short_video",
            "platform": "TikTok",
            "duration_target": 30,
        },
    )
    quote = svc.preflight_quote("owner-344", project["id"])
    assert quote["paid_render_allowed"] is False
    try:
        svc.confirm_render_budget("owner-344", project["id"], confirmed=True, acknowledged_estimate_usd=1.0)
        assert False, "expected PAID_RENDER_BLOCKED"
    except CreativeStudioError as exc:
        assert exc.code == "PAID_RENDER_BLOCKED"


def test_export_rejects_slideshow_as_commercial_ready():
    package = export_project_package(
        {
            "project": {"title": "Demo", "platform": "TikTok", "project_type": "short_video"},
            "brief": {"cta": "Visit getamicor.com"},
            "brand": {"preferred_cta": "Visit getamicor.com"},
            "assets": [
                {
                    "id": "vid1",
                    "kind": "video",
                    "title": "Final",
                    "status": "GENERATED",
                    "url": "/media/final.mp4",
                    "metadata": {"final_promo": True, "render_mode": "ffmpeg_compat_stills", "commercial_slideshow": True},
                }
            ],
            "scenes": [],
        }
    )
    social = package["package"]["social_media_package"]
    assert social["production_ready"] is False
    assert social["slideshow_blocked"] is True
    assert social["commercial_ready_candidate"] is False


def test_unconfigured_video_keeps_config_required_and_asset_generated_false(monkeypatch):
    monkeypatch.delenv("RUNWAYML_API_SECRET", raising=False)
    monkeypatch.delenv("NOVA_CREATIVE_VIDEO_API_KEY", raising=False)
    monkeypatch.delenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", raising=False)
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_PROVIDER", "runway")

    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project(
        "owner-344",
        {
            "title": "Gated scene",
            "project_type": "short_video",
            "platform": "TikTok",
            "duration_target": 30,
        },
    )
    svc.generate_storyboard("owner-344", project["id"])
    video = svc.request_video_generation("owner-344", project["id"])
    assert video["url"] is None
    assert video["job"]["status"] == "CONFIG_REQUIRED"
    assert video["provider"]["asset_generated"] is False
    assert video["provider"]["status"] == "CONFIG_REQUIRED"
    assert video["asset"]["url"] is None
    assert video["asset"]["status"] == "PROVIDER_CONFIG_REQUIRED"


def test_export_caption_copy_alone_is_not_commercial_ready():
    """Caption text is not timed caption evidence. Burn-in or a sidecar is required."""
    payload = {
        "project": {"title": "Promo", "platform": "TikTok", "status": "ACTIVE"},
        "brief": {"cta": "Visit getamicor.com"},
        "brand": {"business_name": "AMICOR Nova"},
        "scenes": [],
        "assets": [
            {"id": "img1", "kind": "image", "title": "Artwork", "status": "GENERATED", "url": "/media/art.png", "metadata": {}},
            {"id": "aud1", "kind": "audio", "title": "Voice", "status": "GENERATED", "url": "/media/voice.mp3", "metadata": {}},
            {"id": "cap1", "kind": "caption", "title": "Caption", "status": "GENERATED", "content": "Save time. Stay in control.", "metadata": {}},
            {
                "id": "vid1",
                "kind": "video",
                "title": "Final",
                "status": "GENERATED",
                "url": "/media/final.mp4",
                "metadata": {"final_promo": True, "commercial_slideshow": False},
            },
            {
                "id": "pres1",
                "kind": "presenter_video",
                "title": "Presenter",
                "status": "GENERATED",
                "url": "/media/presenter.mp4",
                "metadata": {"publish_ready": True, "quality_state": "PUBLISH_READY"},
            },
        ],
    }
    social = export_project_package(payload, fmt="json")["package"]["social_media_package"]
    assert social["caption_copy"] == "Save time. Stay in control."
    assert social["production_ready"] is False

    payload["assets"][3]["metadata"]["captions_burned_in"] = True
    payload["assets"][3]["metadata"]["audio_present"] = True
    payload["assets"][3]["metadata"]["duration_seconds"] = 30
    payload["assets"][3]["metadata"]["license_status"] = "GREEN"
    payload["assets"][3]["metadata"]["click_destination"] = {
        "website_field_url": "https://getamicor.com/nova-today/?utm_source=tiktok&utm_medium=profile_website&utm_campaign=nova_30s_commercial",
        "http_status": 200,
        "verified": True,
    }
    ready = export_project_package(payload, fmt="json")["package"]["social_media_package"]
    assert ready["production_ready"] is True
    assert ready["readiness"]["overall"] == "GREEN"
    assert ready["click_through_verified"] is True
    assert ready["final_video"]["url"] == "/media/final.mp4"
    assert ready["presenter_video"]["publish_ready"] is True

    payload["assets"][3]["metadata"]["click_destination"] = {
        "website_field_url": "https://www.tiktok.com/",
        "http_status": 200,
        "verified": True,
    }
    wrong_dest = export_project_package(payload, fmt="json")["package"]["social_media_package"]
    assert wrong_dest["production_ready"] is False
    assert wrong_dest["click_destination"]["classification"] == "platform_home"
    assert wrong_dest["readiness"]["overall"] != "GREEN"

    payload["assets"][3]["metadata"]["commercial_slideshow"] = True
    blocked = export_project_package(payload, fmt="json")["package"]["social_media_package"]
    assert blocked["production_ready"] is False
    assert blocked["slideshow_blocked"] is True


def test_duration_contract_keeps_sixty_seconds_beside_thirty_second_default():
    html = (Path(__file__).resolve().parents[1] / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")
    js = (Path(__file__).resolve().parents[1] / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    assert '<option value="30" selected>30</option>' in html
    assert '<option value="60">60</option>' in html
    assert 'duration.value = "60"' in js
    assert 'duration.value = "30"' in js
    assert "Open the 60-second full-body demo" in html


def test_even_spaced_english_captions_cover_script():
    cues = even_spaced_cues(
        "Meet AMICOR Nova. Busywork piles up. Visit getamicor.com.",
        12.0,
        words_per_cue=4,
    )
    assert cues
    assert cues[0]["start"] == 0.0
    assert cues[-1]["end"] == 12.0
    joined = " ".join(cue["text"] for cue in cues)
    assert "AMICOR" in joined
    assert "getamicor.com" in joined
    assert "-->" in srt_text(cues)


def test_studio_ui_defaults_vertical_thirty_second_commercial():
    html = (Path(__file__).resolve().parents[1] / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")
    js = (Path(__file__).resolve().parents[1] / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")
    assert 'option value="vertical_short" selected' in html
    assert 'option value="30" selected' in html
    assert 'option value="9:16" selected' in html
    assert "getamicor.com" in html
    assert "run-preflight" in html
    assert "build-offline-montage" in html
    assert "prepare-nova-links" in html
    assert "/preflight" in js
    assert "/assemble/offline-commercial" in js
    assert "click-destinations" in js
    assert "commercial_slideshow" in js
    assert "BUDGET" not in js or "budget-confirm" in js


def test_local_motion_path_exists_for_gated_providers():
    source = (Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio/service.py").read_text(encoding="utf-8")
    assert "local_image_motion_fallback" in source
    assert "provider_unavailable" in source
    assert "local_motion_not_slideshow" in source
    assert "burn_captions_and_cta_fade" in source
    assert "getamicor.com" in source
