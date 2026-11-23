"""Bound image requests separately from chat without calling paid providers."""
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from openai import APITimeoutError

from app.core.nova.creative_studio import providers
from app.core.nova.creative_studio import flags
from app.core.nova.creative_studio.service import CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore


def fake_image_client(monkeypatch, *, timeout=False):
    calls = []

    def generate(**kwargs):
        calls.append(("generate", kwargs))
        if timeout:
            raise APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/images/generations"))
        return SimpleNamespace(data=[SimpleNamespace(url="https://example.com/image.png", b64_json=None)])

    def with_options(**kwargs):
        calls.append(("options", kwargs))
        return SimpleNamespace(images=SimpleNamespace(generate=generate))

    monkeypatch.setattr(providers, "get_client", lambda: SimpleNamespace(with_options=with_options))
    monkeypatch.setattr(providers.OpenAIImageProvider, "status", lambda self: SimpleNamespace(status=providers.AVAILABLE))
    return calls


def test_image_has_own_timeout_and_no_automatic_retry(monkeypatch):
    calls = fake_image_client(monkeypatch)
    result = providers.OpenAIImageProvider().generate(prompt="Original hotel lobby", aspect_ratio="9:16")
    assert result["status"] == "GENERATED"
    assert calls[0] == ("options", {"timeout": 300.0, "max_retries": 0})
    assert len(calls) == 2
    assert calls[1][1]["size"] == "1024x1536"


def test_image_timeout_saves_failed_scene_without_starting_runway(monkeypatch):
    calls = fake_image_client(monkeypatch, timeout=True)
    import app.core.nova.creative_studio.service as service_module
    monkeypatch.setattr(service_module, "image_provider", providers.OpenAIImageProvider)
    monkeypatch.setattr(service_module, "video_provider", lambda: SimpleNamespace(
        provider_id="runway_video", status=lambda: SimpleNamespace(status=providers.AVAILABLE)))
    service = CreativeStudioService(CreativeStudioStore())
    project = service.create_project("owner", {"title": "Hotel", "project_type": "short_video", "duration_target": 15})
    service.generate_storyboard("owner", project["id"])
    result = service.request_video_generation("owner", project["id"])
    assert result["job"]["status"] == "ERROR"
    assert result["asset"]["status"] == "ERROR"
    assert "300 seconds" in result["provider"]["message"]
    assert result["url"] is None
    assert len([call for call in calls if call[0] == "generate"]) == 1
    assert any(asset["kind"] == "image" and asset["status"] == "ERROR"
               for asset in service.get_project("owner", project["id"])["assets"])


@pytest.mark.parametrize(("configured", "selected", "migration_required"), [
    (None, "gpt-image-2.6-sunburst", False),
    ("  ", "gpt-image-2.6-sunburst", False),
    (" gpt-image-2.6-flare ", "gpt-image-2.6-flare", False),
    ("gpt-image-2-2026-04-21", "gpt-image-2-2026-04-21", True),
])
def test_image_migration_preserves_request_contract_and_explicit_overrides(
    monkeypatch, configured, selected, migration_required,
):
    if configured is None:
        monkeypatch.delenv("NOVA_CREATIVE_IMAGE_MODEL", raising=False)
    else:
        monkeypatch.setenv("NOVA_CREATIVE_IMAGE_MODEL", configured)
    calls = fake_image_client(monkeypatch)
    result = providers.OpenAIImageProvider().generate(prompt="Original scene artwork", aspect_ratio="16:9")
    assert calls == [
        ("options", {"timeout": 300.0, "max_retries": 0}),
        ("generate", {"model": selected, "prompt": "Original scene artwork",
                      "size": "1536x1024", "n": 1, "output_format": "png"}),
    ]
    assert result["model"] == selected
    guardrails = flags.creative_guardrails()
    assert guardrails["IMAGE_PROVIDER_MODEL"] == selected
    assert guardrails["IMAGE_PROVIDER_MODEL_MIGRATION_REQUIRED"] is migration_required


def test_new_image_model_does_not_activate_paid_generation(monkeypatch):
    monkeypatch.delenv("NOVA_CREATIVE_IMAGE_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture-not-a-key")
    monkeypatch.setenv("NOVA_CREATIVE_IMAGE_LIVE_ENABLED", "false")
    def forbidden():
        raise AssertionError("Disabled image provider must not create a client")
    monkeypatch.setattr(providers, "get_client", forbidden)
    result = providers.OpenAIImageProvider().generate(prompt="Original artwork", aspect_ratio="1:1")
    assert result["status"] == providers.DISABLED
    assert result["asset_generated"] is False
    assert flags.creative_guardrails()["IMAGE_PROVIDER_LIVE_ENABLED"] is False


def test_image_model_change_invalidates_prior_budget_approval(monkeypatch):
    service = CreativeStudioService(CreativeStudioStore())
    project = service.create_project("owner", {"title": "Scene artwork", "project_type": "short_video", "duration_target": 15})
    monkeypatch.setenv("NOVA_CREATIVE_IMAGE_MODEL", "gpt-image-2")
    before = service.preflight_quote("owner", project["id"])
    confirmation = {
        "confirmed": True,
        "acknowledged_estimate_usd": before["estimated_total_usd"],
        "quote_fingerprint": before["quote_fingerprint"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    }
    assert service._budget_confirmation_matches(confirmation, before) is True
    monkeypatch.setenv("NOVA_CREATIVE_IMAGE_MODEL", "gpt-image-2.6-sunburst")
    after = service.preflight_quote("owner", project["id"])
    assert after["providers"]["image"]["model"] == "gpt-image-2.6-sunburst"
    assert service._budget_confirmation_matches(confirmation, after) is False
