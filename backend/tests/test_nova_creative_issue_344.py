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
    assert "/preflight" in js
    assert "commercial_slideshow" in js
    assert "BUDGET" not in js or "budget-confirm" in js


def test_local_motion_path_exists_for_gated_providers():
    source = (Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio/service.py").read_text(encoding="utf-8")
    assert "local_image_motion_fallback" in source
    assert "provider_unavailable" in source
    assert "local_motion_not_slideshow" in source
    assert "burn_captions_and_cta_fade" in source
    assert "getamicor.com" in source
