"""Bound image requests separately from chat without calling paid providers."""
from types import SimpleNamespace

import httpx
from openai import APITimeoutError

from app.core.nova.creative_studio import providers
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
