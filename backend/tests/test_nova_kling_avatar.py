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


@pytest.fixture
def upload_context(monkeypatch, tmp_path):
    from app.core.nova.creative_studio import service as module, providers
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.store import CreativeStudioStore
    monkeypatch.setattr(module, "_creative_media_root_and_prefix", lambda: (tmp_path, "/media/nova-creative"))
    monkeypatch.setattr(providers, "_creative_media_root_and_prefix", lambda: (tmp_path, "/media/nova-creative"))
    monkeypatch.setattr(FalKlingAvatarProvider, "_request_json", lambda *a, **k: pytest.fail("Paid provider called"))
    svc = CreativeStudioService(CreativeStudioStore())
    project = svc.create_project("image-owner", {"title": "Upload security", "project_type": "short_video"})
    return svc, project, tmp_path


def image_bytes(fmt="PNG", size=(300, 500)):
    from io import BytesIO
    from PIL import Image
    buffer = BytesIO()
    Image.new("RGB", size, "blue").save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.mark.parametrize("fmt,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
def test_upload_roundtrip_and_revocation_never_falls_back(upload_context, fmt, mime):
    from PIL import Image
    from app.core.nova.creative_studio.service import CreativeStudioService, CreativeStudioError
    svc, project, root = upload_context
    pid = project["id"]
    result = svc.upload_genova_presenter_image("image-owner", pid, image_bytes(fmt), "../../unsafe.svg", content_type=mime)
    aid = result["asset"]["id"]
    path, actual_mime, _ = svc.open_asset_file("image-owner", pid, aid)
    assert path.parent == root
    assert path.name.startswith("genova_upload_") and path.suffix == ".png"
    assert actual_mime == "image/png"
    with Image.open(path) as image:
        assert image.format == "PNG" and image.size == (300, 500)
    assert result["approved"] is False
    # Even a legacy preferred plate must not bypass explicit approval.
    legacy = root / "nova-c4edd02f88a04f7081a79a18fd98a935.png"
    legacy.write_bytes(image_bytes())
    assert svc._resolve_genova_presenter_image("image-owner", pid) is None
    svc.set_genova_presenter_approval("image-owner", pid, aid)
    restored = CreativeStudioService(svc.store)
    assert restored.genova_avatar_readiness("image-owner", pid)["approved_image_asset_id"] == aid
    other = svc.create_project("image-owner", {"title": "Other project", "project_type": "short_video"})
    with pytest.raises(CreativeStudioError):
        svc.set_genova_presenter_approval("image-owner", other["id"], aid)
    with pytest.raises(CreativeStudioError):
        svc.open_asset_file("other-owner", pid, aid)
    svc.set_genova_presenter_approval("image-owner", pid, None)
    assert svc._resolve_genova_presenter_image("image-owner", pid) is None
    assert not svc.genova_avatar_readiness("image-owner", pid)["approved_presenter_image_found"]
    svc.set_genova_presenter_approval("image-owner", pid, aid)
    assert svc._resolve_genova_presenter_image("image-owner", pid) == path
    path.unlink()
    assert not svc.genova_avatar_readiness("image-owner", pid)["approved_presenter_image_found"]


@pytest.mark.parametrize("payload,mime", [
    (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/png"),
    (image_bytes("GIF"), "image/gif"),
    (image_bytes("PNG", (100, 100)), "image/png"),
    (image_bytes("PNG"), "image/jpeg"),
])
def test_upload_rejects_unsafe_or_mismatched_content_without_files(upload_context, payload, mime):
    from app.core.nova.creative_studio.service import CreativeStudioError
    svc, project, root = upload_context
    with pytest.raises(CreativeStudioError):
        svc.upload_genova_presenter_image("image-owner", project["id"], payload, "image.png", content_type=mime)
    assert not list(root.iterdir())
    assert not svc.store.list_assets(project["id"], "image-owner")


@pytest.mark.parametrize("mime", [None, "application/octet-stream", "image/svg+xml", "image/jpeg"])
def test_upload_http_rejects_missing_unsupported_or_mismatched_mime(upload_context, monkeypatch, mime):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from importlib import import_module
    routes = import_module("app.core.nova.creative_studio.router")
    svc, project, root = upload_context
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.require_nova_access] = lambda: None
    app.dependency_overrides[routes.get_current_user_context] = lambda: SimpleNamespace(user_id="image-owner")
    app.dependency_overrides[routes.get_db] = lambda: None
    monkeypatch.setattr(routes, "get_service", lambda db: svc)
    with TestClient(app) as client:
        url = f"/api/nova/creative/projects/{project['id']}/genova-image-upload"
        if mime is None:
            # HTTP clients otherwise infer image/png from the filename.
            body = (b'--studio-test\r\nContent-Disposition: form-data; name="file"; filename="test.png"\r\n\r\n'
                    + image_bytes() + b'\r\n--studio-test--\r\n')
            response = client.post(url, content=body, headers={"Content-Type": "multipart/form-data; boundary=studio-test"})
        else:
            response = client.post(url, files={"file": ("test.png", image_bytes(), mime)})
    assert response.status_code == 422
    assert not list(root.iterdir())
    assert not svc.store.list_assets(project["id"], "image-owner")


def test_uploaded_image_public_aliases_blocked_but_owner_api_works(upload_context, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.staticfiles import StaticFiles
    from app.middleware import SecurityHeadersMiddleware
    from importlib import import_module
    routes = import_module("app.core.nova.creative_studio.router")
    svc, project, root = upload_context
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(routes.router)
    user = {"id": "image-owner"}
    app.dependency_overrides[routes.require_nova_access] = lambda: None
    app.dependency_overrides[routes.get_current_user_context] = lambda: SimpleNamespace(user_id=user["id"])
    app.dependency_overrides[routes.get_db] = lambda: None
    monkeypatch.setattr(routes, "get_service", lambda db: svc)
    app.mount("/media/nova-creative", StaticFiles(directory=root), name="media")
    app.mount("/static/generated/nova-creative", StaticFiles(directory=root), name="legacy")
    with TestClient(app) as client:
        uploaded = client.post(f"/api/nova/creative/projects/{project['id']}/genova-image-upload",
                               files={"file": ("test.png", image_bytes(), "image/png")})
        assert uploaded.status_code == 200, uploaded.text
        asset = uploaded.json()["asset"]
        name = asset["url"].rsplit("/", 1)[-1]
        for url in [asset["url"], "/static/generated/nova-creative/" + name]:
            response = client.get(url)
            assert response.status_code == 404
            assert "no-store" in response.headers["cache-control"]
        download = f"/api/nova/creative/projects/{project['id']}/assets/{asset['id']}/file"
        assert client.get(download).status_code == 200
        user["id"] = "other-owner"
        assert client.get(download).status_code == 404
        user["id"] = "image-owner"
        assert client.get(download + "?token=invalid").status_code == 400
        # Protect only uploads; approved demo files remain available.
        (root / "approved-demo.mp4").write_bytes(b"preserved-demo")
        assert client.get("/media/nova-creative/approved-demo.mp4").content == b"preserved-demo"

