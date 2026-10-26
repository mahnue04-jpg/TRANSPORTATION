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


def test_genova_readiness_is_read_only(monkeypatch):
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.store import CreativeStudioStore
    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project("owner-genova", {"title": "Genova", "project_type": "short_video"})
    monkeypatch.setenv("FAL_KEY", "test-only")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_PROVIDER", "kling")
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "false")
    monkeypatch.setattr(FalKlingAvatarProvider, "_request_json",
                        lambda *a, **kw: pytest.fail("Provider call not allowed in readiness"))
    result = svc.genova_avatar_readiness("owner-genova", project["id"])
    assert result["mode"] == "PREVIEW_PREFLIGHT_ONLY"
    assert result["provider_status"] == "DISABLED"
    assert result["can_generate"] is False
    assert result["paid_request_submitted"] is False
    assert result["budget_enforcement_ready"] is False


def test_genova_readiness_enforces_project_ownership():
    from app.core.nova.creative_studio.service import CreativeStudioService, CreativeStudioError
    from app.core.nova.creative_studio.store import CreativeStudioStore
    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project("owner-a", {"title": "Private Genova", "project_type": "short_video"})
    with pytest.raises(CreativeStudioError):
        svc.genova_avatar_readiness("owner-b", project["id"])


def test_genova_missing_image_guidance(monkeypatch):
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.store import CreativeStudioStore
    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project("diagnostic-owner", {"title": "Test commercial", "project_type": "short_video"})
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "false")
    monkeypatch.setattr(FalKlingAvatarProvider, "_request_json",
                        lambda *a, **kw: pytest.fail("Readiness must not call Fal"))
    state = svc.genova_avatar_readiness("diagnostic-owner", project["id"])
    assert state["generated_image_assets_in_project"] == 0
    assert state["approved_presenter_image_found"] is False
    assert "No generated image assets" in state["presenter_image_next_step"]
    assert state["can_generate"] is False


def test_genova_approval_rejects_unknown_image():
    from app.core.nova.creative_studio.service import CreativeStudioService, CreativeStudioError
    from app.core.nova.creative_studio.store import CreativeStudioStore
    svc = CreativeStudioService(CreativeStudioStore())
    p = svc.create_project("approval-owner", {"title": "Commercial", "project_type": "short_video"})
    with pytest.raises(CreativeStudioError):
        svc.set_genova_presenter_approval("approval-owner", p["id"], "not-in-project")
    with pytest.raises(CreativeStudioError):
        svc.set_genova_presenter_approval("other-owner", p["id"], "not-in-project")
    state = svc.genova_avatar_readiness("approval-owner", p["id"])
    assert state["approved_image_asset_id"] is None
    assert not state["can_generate"]


def test_genova_approval_revocation_is_project_scoped():
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.store import CreativeStudioStore
    svc = CreativeStudioService(CreativeStudioStore())
    p = svc.create_project("approval-owner-revoke", {"title": "Commercial", "project_type": "short_video"})
    result = svc.set_genova_presenter_approval("approval-owner-revoke", p["id"], None)
    assert result["approved"] is False
    assert result["approved_asset_id"] is None


def test_genova_approval_persists_and_revokes(monkeypatch, tmp_path):
    from app.core.nova.creative_studio import service as module
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.store import CreativeStudioStore
    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project("genova-persist-owner", {"title": "Test", "project_type": "short_video"})
    image = tmp_path / "genova.png"
    image.write_bytes(b"test-picture")
    asset = svc._save_text_asset(owner_id="genova-persist-owner", project_id=project["id"],
                                 kind="image", title="Genova Still", content="approved project still",
                                 status="GENERATED", url="/media/nova-creative/genova.png")
    monkeypatch.setattr(module, "_resolve_creative_media_url", lambda url: image if url.endswith("genova.png") else None)
    approved = svc.set_genova_presenter_approval("genova-persist-owner", project["id"], asset.id)
    assert approved["approved"] is True
    restored = svc._project_or_404("genova-persist-owner", project["id"])
    assert restored.metadata["approved_genova_image_asset_id"] == asset.id
    check = svc.genova_avatar_readiness("genova-persist-owner", project["id"])
    assert check["approved_presenter_image_found"] is True
    assert check["approved_image_asset_id"] == asset.id
    revoked = svc.set_genova_presenter_approval("genova-persist-owner", project["id"], None)
    assert revoked["approved"] is False
    check = svc.genova_avatar_readiness("genova-persist-owner", project["id"])
    assert check["approved_image_asset_id"] is None


def test_genova_upload_rejects_invalid_and_preserves_no_approval():
    from app.core.nova.creative_studio.service import CreativeStudioService, CreativeStudioError
    from app.core.nova.creative_studio.store import CreativeStudioStore
    svc = CreativeStudioService(CreativeStudioStore())
    p = svc.create_project("upload-owner", {"title": "Upload check", "project_type": "short_video"})
    for payload in (b"", b"not an image", b"x" * (8 * 1024 * 1024 + 1)):
        with pytest.raises(CreativeStudioError):
            svc.upload_genova_presenter_image("upload-owner", p["id"], payload, "test.png")
    assert svc.genova_avatar_readiness("upload-owner", p["id"])["approved_image_asset_id"] is None


def test_genova_upload_rejects_other_owner():
    from app.core.nova.creative_studio.service import CreativeStudioService, CreativeStudioError
    from app.core.nova.creative_studio.store import CreativeStudioStore
    from io import BytesIO
    from PIL import Image
    stream = BytesIO()
    Image.new("RGB", (300, 500)).save(stream, format="PNG")
    svc = CreativeStudioService(CreativeStudioStore())
    p = svc.create_project("upload-owner-a", {"title": "Upload check", "project_type": "short_video"})
    with pytest.raises(CreativeStudioError):
        svc.upload_genova_presenter_image("upload-owner-b", p["id"], stream.getvalue(), "genova.png")
