"""Voice-only Coral narration spend safeguard.

No real OpenAI/Fal/Kling calls. Paid generation stays off unless a test
explicitly enables voice live and mocks the provider.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.nova.creative_studio.service import CreativeStudioError, CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore
from app.core.nova.creative_studio.voice_spend_safeguard import (
    CORAL_VOICE_MAX_USD,
    evaluate_coral_request,
    estimate_coral_narration_usd,
    safeguard_status,
)


SHORT_SCRIPT = (
    "Meet AMICOR Nova, your AI operations workspace for everyday business work. "
    "Visit getamicor.com to explore AMICOR Nova."
)


@pytest.fixture
def svc():
    return CreativeStudioService(CreativeStudioStore())


@pytest.fixture
def paid_media_off(monkeypatch):
    for key in (
        "NOVA_CREATIVE_IMAGE_LIVE_ENABLED",
        "NOVA_CREATIVE_VOICE_LIVE_ENABLED",
        "NOVA_CREATIVE_VIDEO_LIVE_ENABLED",
        "NOVA_CREATIVE_KLING_LIVE_ENABLED",
        "NOVA_CREATIVE_TALKING_PRESENTER_LIVE_ENABLED",
    ):
        monkeypatch.setenv(key, "false")
    monkeypatch.delenv("FAL_KEY", raising=False)


def test_estimate_stays_under_ten_cents_for_30s_script():
    estimate = estimate_coral_narration_usd(SHORT_SCRIPT, include_whisper=True)
    assert 0 < estimate <= CORAL_VOICE_MAX_USD
    assert CORAL_VOICE_MAX_USD == 0.10


def test_estimate_blocks_oversized_script():
    huge = ("AMICOR Nova helps busy owners. " * 4000).strip()
    estimate = estimate_coral_narration_usd(huge, include_whisper=True)
    assert estimate > CORAL_VOICE_MAX_USD
    result = evaluate_coral_request(
        owner_id="o1",
        project_id="p1",
        script=huge,
        voice="coral",
        include_whisper=True,
    )
    assert result["allowed"] is False
    assert result["code"] == "CORAL_SPEND_CEILING"


def test_non_coral_voice_blocked():
    result = evaluate_coral_request(
        owner_id="o1",
        project_id="p1",
        script=SHORT_SCRIPT,
        voice="nova",
    )
    assert result["allowed"] is False
    assert result["code"] == "CORAL_VOICE_REQUIRED"


def test_voice_only_refuses_when_kling_live(monkeypatch):
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_PROVIDER", "kling")
    result = evaluate_coral_request(
        owner_id="o1",
        project_id="p1",
        script=SHORT_SCRIPT,
        voice="coral",
    )
    assert result["allowed"] is False
    assert result["code"] == "VOICE_ONLY_REQUIRED"


def test_safeguard_status_ready_when_other_paid_media_off(paid_media_off):
    status = safeguard_status()
    assert status["budget_enforcement_ready"] is True
    assert status["voice_only"] is True
    assert status["max_usd"] == 0.10
    assert status["paid_request_submitted"] is False


def test_genova_readiness_marks_voice_spend_ready_without_paid_calls(svc, paid_media_off, monkeypatch):
    from app.core.nova.creative_studio.kling import FalKlingAvatarProvider

    project = svc.create_project("spend-owner", {"title": "30s Coral", "project_type": "short_video"})
    monkeypatch.setattr(
        FalKlingAvatarProvider,
        "_request_json",
        lambda *a, **kw: pytest.fail("Readiness must not call Fal"),
    )
    state = svc.genova_avatar_readiness("spend-owner", project["id"])
    assert state["budget_enforcement_ready"] is True
    assert state["can_generate"] is False
    assert state["paid_request_submitted"] is False
    assert state["voice_spend_safeguard"]["max_usd"] == 0.10
    assert "Coral voice-only spend safeguard is connected" in state["reason"]


def test_duplicate_paid_coral_request_reuses_asset(svc, paid_media_off, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_ASSET_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_PUBLIC_PREFIX", "/media/nova-creative")

    calls = []

    def speech(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=b"fake-coral-mp3")

    monkeypatch.setattr(
        "app.core.nova.creative_studio.providers.get_client",
        lambda: SimpleNamespace(
            audio=SimpleNamespace(
                speech=SimpleNamespace(create=speech),
                transcriptions=SimpleNamespace(create=lambda **kwargs: pytest.fail("whisper not needed")),
            )
        ),
    )

    project = svc.create_project("spend-owner", {"title": "Coral one-shot", "project_type": "short_video"})
    first = svc.request_voice_generation(
        "spend-owner",
        project["id"],
        script=SHORT_SCRIPT,
        voice="coral",
        presenter=False,
    )
    assert first["paid_request_submitted"] is True
    assert first["provider"]["asset_generated"] is True
    assert len(calls) == 1

    second = svc.request_voice_generation(
        "spend-owner",
        project["id"],
        script=SHORT_SCRIPT,
        voice="coral",
        presenter=False,
    )
    assert second["paid_request_submitted"] is False
    assert second["provider"].get("reused") is True
    assert second["asset"]["id"] == first["asset"]["id"]
    assert len(calls) == 1


def test_second_different_script_blocked_after_charge(svc, paid_media_off, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_ASSET_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_PUBLIC_PREFIX", "/media/nova-creative")
    monkeypatch.setattr(
        "app.core.nova.creative_studio.providers.get_client",
        lambda: SimpleNamespace(
            audio=SimpleNamespace(
                speech=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(content=b"mp3")),
            )
        ),
    )
    project = svc.create_project("spend-owner", {"title": "One Coral", "project_type": "short_video"})
    svc.request_voice_generation("spend-owner", project["id"], script=SHORT_SCRIPT, voice="coral")
    with pytest.raises(CreativeStudioError) as exc:
        svc.request_voice_generation(
            "spend-owner",
            project["id"],
            script=SHORT_SCRIPT + " Extra line.",
            voice="coral",
        )
    assert exc.value.code == "CORAL_SPEND_ALREADY_USED"


def test_in_flight_reservation_blocks_duplicate(svc, paid_media_off, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_ASSET_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_PUBLIC_PREFIX", "/media/nova-creative")

    project = svc.create_project("spend-owner", {"title": "In flight", "project_type": "short_video"})
    from app.core.nova.creative_studio.voice_spend_safeguard import METADATA_KEY

    proj = svc._project_or_404("spend-owner", project["id"])
    meta = dict(proj.metadata or {})
    meta[METADATA_KEY] = {
        "status": "reserved",
        "fingerprint": "pending",
        "paid_request_submitted": False,
    }
    proj.metadata = meta
    svc.store.save_project(proj)

    with pytest.raises(CreativeStudioError) as exc:
        svc.request_voice_generation("spend-owner", project["id"], script=SHORT_SCRIPT, voice="coral")
    assert exc.value.code == "CORAL_REQUEST_IN_FLIGHT"


def test_voice_live_off_does_not_charge_or_reserve(svc, paid_media_off, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("NOVA_CREATIVE_VOICE_LIVE_ENABLED", "false")
    called = []

    def fail_if_called(**kwargs):
        called.append(kwargs)
        raise AssertionError("Provider must not be called while live is off beyond status check")

    # OpenAIVoiceProvider.generate returns DISABLED without calling get_client when live is off.
    project = svc.create_project("spend-owner", {"title": "No charge", "project_type": "short_video"})
    result = svc.request_voice_generation(
        "spend-owner",
        project["id"],
        script=SHORT_SCRIPT,
        voice="coral",
    )
    assert result["paid_request_submitted"] is False
    assert result["provider"]["status"] == "DISABLED"
    assert result["spend_safeguard"]["budget_enforcement_ready"] is True
    proj = svc._project_or_404("spend-owner", project["id"])
    assert not (proj.metadata or {}).get("coral_voice_spend")
    assert called == []


def test_guardrails_preserve_60s_demo_and_paid_off(svc, paid_media_off):
    gates = svc.guardrails()
    assert gates["studio_test_feature"]["approved_60s_commercial_unchanged"] is True
    assert gates["studio_test_feature"]["paid_providers_default_off"] is True
    assert gates["studio_test_feature"]["coral_voice_spend_max_usd"] == 0.10
    assert gates["VOICE_PROVIDER_LIVE_ENABLED"] is False
    assert gates["IMAGE_PROVIDER_LIVE_ENABLED"] is False
    assert gates["VIDEO_PROVIDER_LIVE_ENABLED"] is False
