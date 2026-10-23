"""Issue #351 — Creative Studio walking presenter + AMICOR Stripe TEST checkout."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.nova.creative_studio.service import CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore
from app.core.nova.creative_studio.studio_checkout import (
    CUSTOMER_PRICE_USD,
    FakeStudioStripeClient,
    RENDER_COST_CEILING_USD,
    checkout_readiness,
    complete_test_checkout,
    create_studio_checkout_order,
    public_pricing,
    record_production_cost,
    reset_studio_orders_for_tests,
    set_studio_stripe_override,
    sync_studio_order_from_stripe,
)
from app.core.nova.creative_studio.walking_presenter import (
    DEFAULT_SCRIPT,
    canonical_spoken_script,
    caption_script,
    validate_presenter_mp4,
    word_aligned_cues,
)


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "nova-creative" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "nova-creative" / "creative.js").read_text(encoding="utf-8")


def test_amicor_pronunciation_is_canonical_for_speech_but_branded_in_captions():
    spoken = canonical_spoken_script(DEFAULT_SCRIPT)
    captions = caption_script(DEFAULT_SCRIPT)
    assert "AH-mih-kor" in spoken
    assert "AMICOR" in captions
    assert "AH-mih-kor" not in captions


def test_word_aligned_cues_cover_every_script_word():
    cues = word_aligned_cues(DEFAULT_SCRIPT, 5.5)
    joined = " ".join(cue["text"] for cue in cues)
    for token in caption_script(DEFAULT_SCRIPT).split():
        assert token in joined
    assert cues[0]["start"] == 0.0
    assert cues[-1]["end"] == pytest.approx(5.5, abs=0.05)


def test_studio_pricing_is_clear_and_test_safe():
    pricing = public_pricing()
    assert pricing["customer_price_usd"] == CUSTOMER_PRICE_USD
    assert pricing["internal_render_cost_ceiling_usd"] == RENDER_COST_CEILING_USD
    assert pricing["auto_billing"] is False
    assert pricing["requires_explicit_checkout"] is True
    assert "30-second" in pricing["scope"]


def test_studio_checkout_test_mode_creates_order_receipt_and_cost_tracking():
    reset_studio_orders_for_tests()
    fake = FakeStudioStripeClient()
    set_studio_stripe_override(fake)
    try:
        started = create_studio_checkout_order(
            owner_id="owner-351",
            project_id="proj-351",
            success_url="https://example.test/success",
            cancel_url="https://example.test/cancel",
            estimated_render_cost_usd=2.04,
        )
        order = started["order"]
        assert order["customer_price_usd"] == 49.0
        assert order["third_party_checkout_shown"] is False
        assert order["auto_billing"] is False
        assert order["branded_as"] == "AMICOR"
        assert started["checkout"]["url"].startswith("https://checkout.stripe.com/")
        assert order["production_cost"]["estimated_render_cost_usd"] == 2.04
        assert order["production_cost"]["ceiling_usd"] == RENDER_COST_CEILING_USD

        fake.mark_paid(started["checkout"]["id"])
        synced = sync_studio_order_from_stripe(order["id"], owner_id="owner-351")
        assert synced["status"] == "paid"
        assert synced["job_status"] == "queued_for_production"
        assert synced["receipt"]["receipt_id"].startswith("rcpt_")
        assert synced["receipt"]["customer_price_usd"] == 49.0

        costed = record_production_cost(
            order["id"],
            owner_id="owner-351",
            actual_render_cost_usd=0.0,
            paid_provider_charges=False,
            note="Local walking presenter proof; no provider invoice.",
        )
        assert costed["production_cost"]["actual_render_cost_usd"] == 0.0
        assert costed["production_cost"]["paid_provider_charges"] is False
        assert costed["receipt"]["production_cost_summary"]["actual_render_cost_usd"] == 0.0
    finally:
        set_studio_stripe_override(None)
        reset_studio_orders_for_tests()


def test_studio_checkout_blocks_over_ceiling():
    reset_studio_orders_for_tests()
    set_studio_stripe_override(FakeStudioStripeClient())
    try:
        with pytest.raises(ValueError, match="ceiling"):
            create_studio_checkout_order(
                owner_id="owner-351",
                project_id="proj-351",
                success_url="https://example.test/success",
                cancel_url="https://example.test/cancel",
                estimated_render_cost_usd=RENDER_COST_CEILING_USD + 1,
            )
    finally:
        set_studio_stripe_override(None)
        reset_studio_orders_for_tests()


def test_ui_exposes_walking_presenter_and_checkout_controls():
    assert 'id="build-walking-presenter"' in HTML
    assert 'id="build-walking-commercial-30s"' in HTML
    assert 'id="accept-voice-license"' in HTML
    assert 'id="complete-studio-test-checkout"' in HTML
    assert 'id="studio-test-readiness"' in HTML
    assert "TEST feature readiness" in HTML
    assert "AMICOR Studio checkout" in HTML
    assert 'id="start-studio-checkout"' in HTML
    assert "/assemble/walking-presenter-proof" in JS
    assert "/assemble/walking-commercial-30s" in JS
    assert "/voice-license" in JS
    assert "/complete-test" in JS
    assert "/api/nova/creative/pricing" in JS
    assert "/checkout" in JS
    assert "studio_test_feature" in JS


def test_voice_license_acceptance_turns_green():
    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project(
        "owner-351",
        {"title": "License", "project_type": "short_video", "platform": "TikTok", "duration_target": 30},
    )
    before = svc._project_voice_license("owner-351", project["id"])
    assert before is None
    accepted = svc.accept_voice_license("owner-351", project["id"], accepted=True, note="Owner ok")
    assert accepted["license_status"] == "GREEN"
    assert svc._project_voice_license("owner-351", project["id"]) == "GREEN"


def test_checkout_readiness_and_complete_test_flow():
    reset_studio_orders_for_tests()
    fake = FakeStudioStripeClient()
    set_studio_stripe_override(fake)
    try:
        readiness = checkout_readiness()
        assert readiness["payment_mode"] == "test_fake"
        assert readiness["local_test_simulation_available"] is True
        started = create_studio_checkout_order(
            owner_id="owner-351",
            project_id="proj-351",
            success_url="https://example.test/success",
            cancel_url="https://example.test/cancel",
            estimated_render_cost_usd=2.0,
        )
        paid = complete_test_checkout(started["order"]["id"], owner_id="owner-351")
        assert paid["status"] == "paid"
        assert paid["receipt"]["receipt_id"].startswith("rcpt_")
        assert paid["job_status"] == "queued_for_production"
    finally:
        set_studio_stripe_override(None)
        reset_studio_orders_for_tests()


def test_service_checkout_persists_order_asset(monkeypatch):
    reset_studio_orders_for_tests()
    set_studio_stripe_override(FakeStudioStripeClient())
    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project(
        "owner-351",
        {
            "title": "Nova 30s commercial",
            "project_type": "short_video",
            "platform": "TikTok",
            "duration_target": 30,
        },
    )
    try:
        started = svc.start_studio_checkout(
            "owner-351",
            project["id"],
            success_url="https://example.test/success",
            cancel_url="https://example.test/cancel",
        )
        assert started["order"]["project_id"] == project["id"]
        listed = svc.list_studio_checkout_orders("owner-351", project["id"])
        assert len(listed["orders"]) == 1
        assert listed["pricing"]["customer_price_usd"] == 49.0
    finally:
        set_studio_stripe_override(None)
        reset_studio_orders_for_tests()


def test_walking_presenter_render_and_ffprobe(tmp_path, monkeypatch):
    pytest.importorskip("edge_tts")
    pytest.importorskip("PIL")

    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")

    def forbid_paid(*_args, **_kwargs):
        raise AssertionError("paid provider was called")

    monkeypatch.setattr(
        "app.core.nova.creative_studio.providers.OpenAIVoiceProvider.generate",
        forbid_paid,
    )
    monkeypatch.setattr(
        "app.core.nova.creative_studio.providers.DidTalkingPresenterProvider.generate",
        forbid_paid,
    )

    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project(
        "owner-351",
        {
            "title": "Walking presenter proof",
            "project_type": "short_video",
            "platform": "TikTok",
            "duration_target": 30,
        },
    )
    rendered = svc.render_walking_presenter_proof("owner-351", project["id"])
    assert rendered["lip_sync"] is True
    assert rendered["paid_provider_charges"] is False
    assert rendered["milestone"] == "5s_walking_presenter"
    assert rendered["validation"]["ok"] is True
    meta = rendered["asset"]["metadata"]
    assert meta["full_body_walking"] is True
    assert meta["word_aligned_captions"] is True
    assert meta["commercial_slideshow"] is False
    assert meta["lip_sync_method"] == "phoneme_viseme_plus_waveform"
    assert "AMICOR" in (rendered["asset"]["content"] or "")

    video = tmp_path / rendered["url"].rsplit("/", 1)[-1]
    assert video.is_file()
    probe = validate_presenter_mp4(video)
    assert probe["ok"] is True
    assert 4.5 <= probe["duration_seconds"] <= 6.5
    assert probe["video_codec"] in {"h264", "avc1"}
    assert probe["audio_codec"] in {"aac", "mp4a"}
    srt = video.with_suffix(".srt")
    assert srt.is_file()
    assert "AMICOR" in srt.read_text(encoding="utf-8")


def test_thirty_second_walking_commercial_and_green_license(tmp_path, monkeypatch):
    pytest.importorskip("edge_tts")
    pytest.importorskip("PIL")

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
        "owner-351",
        {
            "title": "30s walking commercial",
            "project_type": "short_video",
            "platform": "TikTok",
            "duration_target": 30,
        },
    )
    svc.generate_storyboard("owner-351", project["id"])
    svc.accept_voice_license("owner-351", project["id"], accepted=True, note="Owner accepted for #351")
    rendered = svc.render_walking_commercial_30s("owner-351", project["id"])
    assert rendered["milestone"] == "30s_walking_commercial"
    assert rendered["lip_sync"] is True
    assert rendered["mobile_download_ready"] is True
    assert rendered["paid_provider_charges"] is False
    assert rendered["license_status"] == "GREEN"
    assert rendered["pipeline"] == "presenter_30s"
    assert rendered["presenter_used"] is True
    assert rendered["commercial_complete"] is False
    assert rendered["asset"]["metadata"]["pipeline"] == "presenter_30s"
    assert rendered["asset"]["metadata"]["render_mode"] == "local_walking_commercial_30s"
    assert rendered["validation"]["ok"] is True
    video = tmp_path / rendered["url"].rsplit("/", 1)[-1]
    probe = validate_presenter_mp4(video, min_seconds=28.0, max_seconds=32.0)
    assert probe["ok"] is True
    assert 28.0 <= probe["duration_seconds"] <= 32.0
    assert probe["video_codec"] in {"h264", "avc1"}
    assert probe["audio_codec"] in {"aac", "mp4a"}
    assert video.with_suffix(".srt").is_file()
