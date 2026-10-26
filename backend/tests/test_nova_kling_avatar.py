"""Offline Kling Avatar v2 tests. No real Fal API calls or credits."""
import pytest
from app.core.nova.creative_studio.kling import FalKlingAvatarProvider, AVATAR_MODEL

TASK = {
    "request_id": "avatar-123",
    "status_url": "https://queue.fal.run/fal-ai/kling-video/requests/avatar-123/status",
    "response_url": "https://queue.fal.run/fal-ai/kling-video/requests/avatar-123",
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
    "https://queue.fal.run/fal-ai/kling-video/ai-avatar/v2/standard/requests/avatar-123/status",
    "https://queue.fal.run/fal-ai/kling-video/requests/other-id/status",
    "https://queue.fal.run/fal-ai/kling-video/requests/avatar-123/status/extra",
    "https://queue.fal.run/fal-ai/kling-video/requests/avatar-123/status?token=secret",
    "https://queue.fal.run/fal-ai/kling-video/requests/avatar-123/status#fragment",
    "https://queue.fal.run@attacker.example/fal-ai/kling-video/requests/avatar-123/status",
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


def save_test_narration(svc, project, root):
    import wave
    path = root / "test-narration.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000)
    return svc._save_text_asset(owner_id=project["owner_id"], project_id=project["id"],
        kind="audio", title="TEST narration - synthetic silence", content="Test narration only.",
        url="/media/nova-creative/test-narration.wav", status="GENERATED")


def test_narration_approval_tracks_exact_file_script_and_revocation(upload_context):
    from app.core.nova.creative_studio.service import CreativeStudioService
    svc, project, root = upload_context
    audio = save_test_narration(svc, project, root)
    assert svc.genova_narration_readiness("image-owner", project["id"])["approved"] is False
    svc.set_genova_narration_approval("image-owner", project["id"], audio.id)
    restored = CreativeStudioService(svc.store)
    assert restored.genova_avatar_readiness("image-owner", project["id"])["approved_narration_audio_found"]
    assert not restored.genova_avatar_readiness("image-owner", project["id"])["can_generate"]
    svc.set_genova_narration_approval("image-owner", project["id"], None)
    assert not svc.genova_narration_readiness("image-owner", project["id"])["approved"]
    svc.set_genova_narration_approval("image-owner", project["id"], audio.id)
    # Changing valid audio bytes also invalidates approval.
    with (root / "test-narration.wav").open("ab") as stream:
        stream.write(b"changed")
    assert not svc.genova_narration_readiness("image-owner", project["id"])["approved"]


def test_narration_rejects_foreign_missing_invalid_and_changed_script(upload_context):
    from app.core.nova.creative_studio.service import CreativeStudioError
    svc, project, root = upload_context
    audio = save_test_narration(svc, project, root)
    other = svc.create_project("image-owner", {"title": "Other", "project_type": "short_video"})
    for owner, pid in [("another-owner", project["id"]), ("image-owner", other["id"])]:
        with pytest.raises(CreativeStudioError):
            svc.set_genova_narration_approval(owner, pid, audio.id)
    svc.set_genova_narration_approval("image-owner", project["id"], audio.id)
    svc._save_text_asset(owner_id="image-owner", project_id=project["id"], kind="presenter_script", title="New script", content="Changed words.")
    assert not svc.genova_narration_readiness("image-owner", project["id"])["approved"]
    with pytest.raises(CreativeStudioError, match="latest presenter script"):
        svc.set_genova_narration_approval("image-owner", project["id"], audio.id)
    (root / "test-narration.wav").unlink()
    assert not svc.genova_narration_readiness("image-owner", project["id"])["candidate_audio"]


def test_narration_approval_persists_in_database(upload_context):
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.store import DbCreativeStudioStore
    from app.core.nova.creative_studio.schema_ensure import ensure_nova_creative_schema
    from app.db.session import SessionLocal, engine
    _, _, root = upload_context
    ensure_nova_creative_schema(engine)
    with SessionLocal() as db:
        svc = CreativeStudioService(DbCreativeStudioStore(db))
        project = svc.create_project("narration-db-owner", {"title": "TEST persistence", "project_type": "short_video"})
        audio = save_test_narration(svc, project, root)
        svc.set_genova_narration_approval("narration-db-owner", project["id"], audio.id)
    with SessionLocal() as db:
        restored = CreativeStudioService(DbCreativeStudioStore(db))
        result = restored.genova_narration_readiness("narration-db-owner", project["id"])
        assert result["approved"] and result["approved_asset_id"] == audio.id


@pytest.fixture
def reviewed_budget(upload_context, monkeypatch):
    for key in ["NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "NOVA_CREATIVE_KLING_LIVE_ENABLED", "NOVA_CREATIVE_VOICE_LIVE_ENABLED", "NOVA_CREATIVE_TALKING_PRESENTER_LIVE_ENABLED"]:
        monkeypatch.setenv(key, "false")
    monkeypatch.setenv("NOVA_CREATIVE_IMAGE_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_CREATIVE_OWNER_REPORTED_FAL_BALANCE_USD", "100")
    return upload_context


@pytest.mark.parametrize("acknowledged", [None, -1, 0, float("nan"), float("inf"), 1000])
def test_budget_rejects_missing_invalid_or_over_ceiling_acknowledgement(reviewed_budget, acknowledged):
    from app.core.nova.creative_studio.service import CreativeStudioError
    svc, project, _ = reviewed_budget
    with pytest.raises(CreativeStudioError) as exc:
        svc.confirm_render_budget("image-owner", project["id"], confirmed=True, acknowledged_estimate_usd=acknowledged, quote_fingerprint=svc.preflight_quote("image-owner", project["id"])["quote_fingerprint"])
    assert exc.value.code == "INVALID_RENDER_BUDGET"


def test_budget_confirmation_expires_and_changes_invalidate_it(reviewed_budget):
    from app.core.nova.creative_studio.service import CreativeStudioError
    svc, project, _ = reviewed_budget
    pid = project["id"]
    quote = svc.preflight_quote("image-owner", pid)
    svc.confirm_render_budget("image-owner", pid, confirmed=True, acknowledged_estimate_usd=quote["estimated_total_usd"], quote_fingerprint=quote["quote_fingerprint"])
    assert svc.preflight_quote("image-owner", pid)["owner_budget_confirmed"]
    svc.require_budget_confirmation_for_paid("image-owner", pid)
    saved = svc._project_or_404("image-owner", pid)
    saved.metadata["budget_confirmation"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    svc.store.save_project(saved)
    with pytest.raises(CreativeStudioError):
        svc.require_budget_confirmation_for_paid("image-owner", pid)
    svc.confirm_render_budget("image-owner", pid, confirmed=True, acknowledged_estimate_usd=quote["estimated_total_usd"], quote_fingerprint=quote["quote_fingerprint"])
    svc._save_text_asset(owner_id="image-owner", project_id=pid, kind="presenter_script", title="Changed script", content="New words.")
    assert not svc.preflight_quote("image-owner", pid)["owner_budget_confirmed"]
    with pytest.raises(CreativeStudioError):
        svc.require_budget_confirmation_for_paid("image-owner", pid)


@pytest.mark.parametrize("balance", ["nan", "inf", "-1", "0.01"])
def test_budget_rejects_unknown_invalid_or_insufficient_balance(reviewed_budget, monkeypatch, balance):
    from app.core.nova.creative_studio.service import CreativeStudioError
    svc, project, _ = reviewed_budget
    monkeypatch.setenv("NOVA_CREATIVE_OWNER_REPORTED_FAL_BALANCE_USD", balance)
    quote = svc.preflight_quote("image-owner", project["id"])
    with pytest.raises(CreativeStudioError):
        svc.confirm_render_budget("image-owner", project["id"], confirmed=True, acknowledged_estimate_usd=quote["estimated_total_usd"], quote_fingerprint=quote["quote_fingerprint"])


def test_cannot_confirm_a_different_project_snapshot_at_the_same_price(reviewed_budget):
    from app.core.nova.creative_studio.service import CreativeStudioError
    svc, project, _ = reviewed_budget
    quote = svc.preflight_quote("image-owner", project["id"])
    svc._save_text_asset(owner_id="image-owner", project_id=project["id"], kind="presenter_script", title="Changed", content="New words.")
    with pytest.raises(CreativeStudioError) as exc:
        svc.confirm_render_budget("image-owner", project["id"], confirmed=True,
            acknowledged_estimate_usd=quote["estimated_total_usd"], quote_fingerprint=quote["quote_fingerprint"])
    assert exc.value.code == "STALE_RENDER_QUOTE"


@pytest.mark.parametrize("invalid", ["corrupt", "too_long", "missing"])
def test_narration_rejects_invalid_audio_files(upload_context, invalid):
    import wave
    from app.core.nova.creative_studio.service import CreativeStudioError
    svc, project, root = upload_context
    audio = save_test_narration(svc, project, root)
    path = root / "test-narration.wav"
    if invalid == "missing":
        path.unlink()
    elif invalid == "corrupt":
        path.write_bytes(b"not audio")
    else:
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(8000)
            stream.writeframes(b"\0\0" * 8000 * 37)
    with pytest.raises(CreativeStudioError):
        svc.set_genova_narration_approval("image-owner", project["id"], audio.id)


def test_narration_http_approval_revoke_and_wrong_owner(upload_context, monkeypatch):
    from importlib import import_module
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    routes = import_module("app.core.nova.creative_studio.router")
    svc, project, root = upload_context
    audio = save_test_narration(svc, project, root)
    app = FastAPI()
    app.include_router(routes.router)
    user = {"id": "image-owner"}
    app.dependency_overrides[routes.require_nova_access] = lambda: None
    app.dependency_overrides[routes.get_current_user_context] = lambda: SimpleNamespace(user_id=user["id"])
    app.dependency_overrides[routes.get_db] = lambda: None
    monkeypatch.setattr(routes, "get_service", lambda db: svc)
    base = f"/api/nova/creative/projects/{project['id']}"
    with TestClient(app) as client:
        response = client.put(base + "/genova-narration-approval", json={"asset_id": audio.id})
        assert response.status_code == 200, response.text
        assert client.get(base + "/genova-narration").json()["approved"] is True
        assert client.put(base + "/genova-narration-approval", json={"asset_id": None}).json()["approved"] is False
        user["id"] = "another-owner"
        assert client.get(base + "/genova-narration").status_code == 404
        assert client.put(base + "/genova-narration-approval", json={"asset_id": audio.id}).status_code == 404


def narration_upload_bytes(seconds=1):
    import io
    import wave
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * (8000 * seconds))
    return buffer.getvalue()


def test_narration_import_preserves_assets_and_requires_separate_approval(upload_context):
    svc, project, root = upload_context
    old = save_test_narration(svc, project, root)
    svc.set_genova_narration_approval("image-owner", project["id"], old.id)
    result = svc.upload_genova_narration("image-owner", project["id"], narration_upload_bytes(),
                                         "New reviewed script.", content_type="audio/wav")
    assert result["approved"] is False and result["paid_request_submitted"] is False
    state = svc.genova_narration_readiness("image-owner", project["id"])
    assert state["approved"] is False
    assert state["candidate_audio"][0]["asset_id"] == result["asset"]["id"]
    assert state["candidate_audio"][0]["filename"].endswith(".wav")
    assert old.id in [a.id for a in svc.store.list_assets(project["id"], "image-owner")]
    path, _, _ = svc.open_asset_file("image-owner", project["id"], result["asset"]["id"])
    assert path.read_bytes() == narration_upload_bytes()
    assert result["asset"]["metadata"]["license_status"] == "AMBER"
    assert svc.set_genova_narration_approval("image-owner", project["id"], result["asset"]["id"])["approved"]


@pytest.mark.parametrize("data,script,mime", [
    (b"not audio", "Script", "audio/wav"),
    (narration_upload_bytes(), "Script", "audio/mpeg"),
    (narration_upload_bytes(), "Script", "text/plain"),
    (narration_upload_bytes(), "  ", "audio/wav"),
    (narration_upload_bytes(), "x" * 10001, "audio/wav"),
    (b"x" * (32 * 1024 * 1024 + 1), "Script", "audio/wav"),
    (narration_upload_bytes(61), "Script", "audio/wav"),
])
def test_narration_import_rejects_invalid_without_saved_assets(upload_context, data, script, mime):
    from app.core.nova.creative_studio.service import CreativeStudioError
    svc, project, root = upload_context
    with pytest.raises(CreativeStudioError):
        svc.upload_genova_narration("image-owner", project["id"], data, script, content_type=mime)
    assert not svc.store.list_assets(project["id"], "image-owner")
    assert not list(root.iterdir())


def test_imported_narration_http_private_owner_only(upload_context, monkeypatch):
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
    app.mount("/media/nova-creative", StaticFiles(directory=root))
    app.mount("/static/generated/nova-creative", StaticFiles(directory=root))
    base = f"/api/nova/creative/projects/{project['id']}"
    with TestClient(app) as client:
        response = client.post(base + "/genova-narration-upload", data={"script": "Reviewed script."},
                               files={"file": ("../../unsafe.wav", narration_upload_bytes(), "audio/wav")})
        assert response.status_code == 200, response.text
        asset = response.json()["asset"]
        name = asset["url"].rsplit("/", 1)[-1]
        assert name.startswith("genova_narration_upload_")
        for url in [asset["url"], "/static/generated/nova-creative/" + name]:
            assert client.get(url).status_code == 404
        download = base + f"/assets/{asset['id']}/file"
        assert client.get(download).content == narration_upload_bytes()
        assert client.get(base + "/genova-narration").json()["approved"] is False
        user["id"] = "other-owner"
        assert client.get(download).status_code == 404
        assert client.post(base + "/genova-narration-upload", data={"script": "Reviewed script."},
                           files={"file": ("a.wav", narration_upload_bytes(), "audio/wav")}).status_code == 404



def saved_avatar_token(avatar):
    import base64
    import json
    from app.core.nova.creative_studio.kling import AVATAR_TOKEN_PREFIX
    return AVATAR_TOKEN_PREFIX + base64.urlsafe_b64encode(json.dumps(TASK).encode()).decode()


@pytest.mark.parametrize("failure_stage", ["status", "result", "download"])
def test_avatar_interrupted_recovery_keeps_same_task_without_resubmit(avatar, monkeypatch, failure_stage):
    calls = []
    interrupted = {"active": True}
    def request(method, url, *, payload=None):
        calls.append((method, url))
        assert method == "GET", "Recovery must never submit paid generation"
        if interrupted["active"] and failure_stage == ("status" if url.endswith("/status") else "result"):
            raise RuntimeError("simulated private error must not leak")
        return {"status": "COMPLETED"} if url.endswith("/status") else {"video": {"url": "https://example.test/out.mp4"}}
    def download(url):
        if interrupted["active"] and failure_stage == "download":
            raise OSError("simulated private file path must not leak")
        return "/media/nova-creative/recovered.mp4"
    monkeypatch.setattr(avatar, "_request_json", request)
    monkeypatch.setattr(avatar, "_save_remote_video", download)
    token = saved_avatar_token(avatar)
    first = avatar.generate_avatar(image_url=None, audio_url=None, resume_task_id=token)
    assert first["status"] == "PROCESSING"
    assert first["task_id"] == token and first["can_resubmit"] is False
    assert "private" not in first["message"]
    interrupted["active"] = False
    second = avatar.generate_avatar(image_url=None, audio_url=None, resume_task_id=first["task_id"])
    assert second["status"] == "GENERATED"
    assert second["task_id"] == token
    assert all(method == "GET" for method, url in calls)


def test_saved_avatar_can_be_recovered_with_paid_generation_off(avatar, monkeypatch):
    monkeypatch.setenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_CREATIVE_KLING_LIVE_ENABLED", "false")
    calls = []
    def request(method, url, *, payload=None):
        calls.append(method)
        assert method == "GET"
        return {"status": "COMPLETED"} if url.endswith("/status") else {"video": {"url": "https://example.test/out.mp4"}}
    monkeypatch.setattr(avatar, "_request_json", request)
    monkeypatch.setattr(avatar, "_save_remote_video", lambda url: "/media/nova-creative/recovered.mp4")
    result = avatar.generate_avatar(image_url=None, audio_url=None, resume_task_id=saved_avatar_token(avatar))
    assert result["status"] == "GENERATED" and calls == ["GET", "GET"]
    assert avatar.generate_avatar(image_url="https://example.test/a.png", audio_url="https://example.test/a.wav")["status"] == "DISABLED"
    assert calls == ["GET", "GET"]


def test_avatar_ambiguous_submission_does_not_auto_retry(avatar, monkeypatch):
    calls = []
    def request(method, url, *, payload=None):
        calls.append(method)
        raise RuntimeError("private transport details")
    monkeypatch.setattr(avatar, "_request_json", request)
    result = avatar.generate_avatar(image_url="https://example.test/a.png", audio_url="https://example.test/a.wav")
    assert calls == ["POST"]
    assert result["status"] == "ERROR"
    assert result["submission_uncertain"] is True and result["can_resubmit"] is False
    assert "private" not in result["message"]


@pytest.mark.parametrize("request_id", ["../avatar-123", "avatar-123/extra", "avatar-123?x=1", "", "x" * 201])
def test_avatar_rejects_invalid_request_ids(avatar, request_id):
    with pytest.raises(RuntimeError):
        avatar._validate_task(dict(TASK, request_id=request_id))


def test_avatar_rejects_swapped_status_and_result_urls(avatar):
    with pytest.raises(RuntimeError):
        avatar._validate_task(dict(TASK, status_url=TASK["response_url"], response_url=TASK["status_url"]))
