"""Offline Kling Avatar v2 tests. No real Fal API calls or credits."""
import pytest
from app.core.nova.creative_studio.kling import FalKlingAvatarProvider, AVATAR_MODEL

TASK = {
    "request_id": "avatar-123",
    "status_url": f"https://queue.fal.run/{AVATAR_MODEL}/requests/avatar-123/status",
    "response_url": f"https://queue.fal.run/{AVATAR_MODEL}/requests/avatar-123",
}

@pytest.fixture
def avatar(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "test-only")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_PROVIDER", "kling")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "true")
    return FalKlingAvatarProvider()


def test_disabled_by_default(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "test-only")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_PROVIDER", "kling")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "false")
    provider = FalKlingAvatarProvider()
    provider._request_json = lambda *args, **kw: pytest.fail("Paid call attempted")
    result = provider.generate_avatar(image_url="https://example.test/genova.png", audio_url="https://example.test/audio.wav")
    assert result["status"] == "DISABLED"
    assert not result["asset_generated"]


def test_queue_submit_once_then_resume(avatar, monkeypatch):
    calls = []
    def fake_request(method, url, *, payload=None):
        calls.append((method, url, payload))
        if method == "POST":
            return TASK
        if url.endswith("/status"):
            return {"status": "COMPLETED"}
        return {"video": {"url": "https://example.test/result.mp4"}}
    monkeypatch.setattr(avatar, "_request_json", fake_request)
    monkeypatch.setattr(avatar, "_save_remote_video", lambda url: "/media/nova-creative/verified.mp4")
    first = avatar.generate_avatar(image_url="https://example.test/genova.png", audio_url="https://example.test/audio.wav")
    assert first["status"] == "PROCESSING"
    assert len(calls) == 1
    assert calls[0][1].endswith(AVATAR_MODEL)
    assert calls[0][2]["image_url"] == "https://example.test/genova.png"
    result = avatar.generate_avatar(image_url=None, audio_url=None, resume_task_id=first["task_id"])
    assert result["status"] == "GENERATED"
    assert result["url"].endswith("verified.mp4")
    assert len([call for call in calls if call[0] == "POST"]) == 1


@pytest.mark.parametrize("bad_url", [
    "http://queue.fal.run/fal-ai/kling-video/ai-avatar/v2/standard/requests/avatar-123/status",
    "https://attacker.example/fal-ai/kling-video/ai-avatar/v2/standard/requests/avatar-123/status",
    "https://queue.fal.run/fal-ai/kling-video/requests/avatar-123/status",
])
def test_reject_foreign_queue_url(avatar, bad_url):
    with pytest.raises(RuntimeError):
        avatar._validate_task(dict(TASK, status_url=bad_url))


def test_reject_missing_inputs_without_network(avatar, monkeypatch):
    monkeypatch.setattr(avatar, "_request_json", lambda *a, **k: pytest.fail("Paid call attempted"))
    result = avatar.generate_avatar(image_url="", audio_url="")
    assert result["status"] == "ERROR"
