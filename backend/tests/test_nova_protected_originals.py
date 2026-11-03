"""Regression checks for protected originals in both Creative Studio stores."""
from app.core.nova.creative_studio.models import CreativeAsset
from app.core.nova.creative_studio.store import CreativeStudioStore


def asset(asset_id, *, source=None, status="GENERATED"):
    return CreativeAsset(
        id=asset_id, project_id="project", owner_id="owner", kind="video",
        title=asset_id, content="", status=status,
        metadata={"source": source} if source else {},
    )


def test_media_reset_preserves_owner_imports():
    store = CreativeStudioStore()
    for row in [
        asset("original", source="owner_video_import"),
        asset("older-import", source="owner_import"),
        asset("preview"),
    ]:
        store.save_asset(row)
    deleted = store.delete_assets_by_kinds("project", "owner", {"video"})
    assert [row.id for row in deleted] == ["preview"]
    assert {row.id for row in store.list_assets("project", "owner")} == {"original", "older-import"}


def test_preview_cleanup_preserves_imported_original():
    store = CreativeStudioStore()
    store.save_asset(asset("original", source="owner_video_import"))
    store.save_asset(asset("preview"))
    deleted = store.delete_assets_by_ids("project", "owner", {"original", "preview"})
    assert [row.id for row in deleted] == ["preview"]
    assert [row.id for row in store.list_assets("project", "owner")] == ["original"]


def test_failed_cleanup_preserves_owner_original():
    store = CreativeStudioStore()
    store.save_asset(asset("original", source="owner_video_import", status="ERROR"))
    store.save_asset(asset("failed-preview", status="ERROR"))
    assert store.delete_failed_video_assets("project", "owner") == 1
    assert [row.id for row in store.list_assets("project", "owner")] == ["original"]


def test_approved_master_protected():
    store = CreativeStudioStore()
    row = asset("approved")
    row.metadata["approved_master"] = True
    store.save_asset(row)
    assert store.delete_assets_by_kinds("project", "owner", {"video"}) == []
    assert store.get_project("project", "owner") is None
    assert len(store.list_assets("project", "owner")) == 1


def test_import_reset_preserves_original_file_and_checksum(tmp_path, monkeypatch):
    """Exercise the service cleanup and disk file, without live users or providers."""
    import hashlib
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio import video_import

    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    monkeypatch.setattr(video_import, "validate_video", lambda path: {
        "duration_seconds": 30.0, "width": 720, "height": 1280,
        "video_codec": "h264", "audio_codec": "aac", "decode_verified": True,
    })
    store = CreativeStudioStore()
    service = CreativeStudioService(store)
    project = service.create_project("owner", {
        "title": "Protected test commercial", "project_type": "promo_video",
        "platform": "TikTok", "duration_target": 30,
    })
    project_id = project["id"]
    original = b"test-fixture-mp4-bytes-no-actual-playback"
    saved = service.import_finished_video("owner", project_id, original, content_type="video/mp4")
    saved_id = saved["asset"]["id"]
    saved_path, _, _ = service.open_asset_file("owner", project_id, saved_id)
    assert saved_path.read_bytes() == original
    assert saved["asset"]["metadata"]["sha256"] == hashlib.sha256(original).hexdigest()

    disposable = tmp_path / "disposable-preview.mp4"
    disposable.write_bytes(b"disposable")
    store.save_asset(CreativeAsset(
        id="disposable", project_id=project_id, owner_id="owner",
        kind="video", title="Preview", content="Preview",
        url="/media/nova-creative/disposable-preview.mp4",
    ))
    result = service.reset_project_media("owner", project_id)
    assert result["deleted_media_files"] == 1
    assert not disposable.exists()
    assert saved_path.is_file()
    assert saved_path.read_bytes() == original
    readback, media_type, _ = service.open_asset_file("owner", project_id, saved_id)
    assert media_type == "video/mp4"
    assert hashlib.sha256(readback.read_bytes()).hexdigest() == hashlib.sha256(original).hexdigest()
    assert len([a for a in store.list_assets(project_id, "owner") if a.id == saved_id]) == 1


def test_real_h264_aac_mp4_survives_cleanup(tmp_path, monkeypatch):
    """Decode a real local MP4 and retain exact bytes after routine reset."""
    import hashlib
    import shutil
    import subprocess

    import pytest
    from app.core.nova.creative_studio.service import CreativeStudioService

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/ffprobe required for actual MP4 validation")

    source = tmp_path / "valid-original.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=blue:size=256x256:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-movflags", "+faststart",
        str(source),
    ], check=True, timeout=30)
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    media_dir = tmp_path / "studio"
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(media_dir))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    store = CreativeStudioStore()
    service = CreativeStudioService(store)
    project_id = service.create_project("owner", {
        "title": "Real-media retention", "project_type": "promo_video",
        "platform": "TikTok", "duration_target": 30,
    })["id"]
    saved = service.import_finished_video("owner", project_id, original, content_type="video/mp4")
    asset_id = saved["asset"]["id"]
    assert saved["asset"]["metadata"]["decode_verified"] is True
    assert saved["asset"]["metadata"]["sha256"] == digest
    assert service.import_finished_video(
        "owner", project_id, original, content_type="video/mp4"
    )["reused"] is True

    media_dir.mkdir(parents=True, exist_ok=True)
    preview = media_dir / "temporary-preview.mp4"
    preview.write_bytes(b"temporary-preview")
    store.save_asset(CreativeAsset(
        id="temporary-preview", project_id=project_id, owner_id="owner",
        kind="video", title="Disposable preview", content="",
        url="/media/nova-creative/temporary-preview.mp4",
    ))
    result = service.reset_project_media("owner", project_id)
    assert result["deleted_media_files"] == 1
    assert not preview.exists()
    saved_path, mime, _ = service.open_asset_file("owner", project_id, asset_id)
    assert mime == "video/mp4"
    assert hashlib.sha256(saved_path.read_bytes()).hexdigest() == digest
    with pytest.raises(Exception):
        service.open_asset_file("different-owner", project_id, asset_id)


def test_database_cleanup_preserves_originals_after_session_reopen(tmp_path, monkeypatch):
    """Exercise SQLAlchemy storage and service file cleanup across DB sessions."""
    import hashlib
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.store import DbCreativeStudioStore
    from app.core.nova.creative_studio.schema_ensure import ensure_nova_creative_schema
    from app.db.session import SessionLocal, engine

    ensure_nova_creative_schema(engine)
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")

    db = SessionLocal()
    try:
        svc = CreativeStudioService(DbCreativeStudioStore(db))
        project_id = svc.create_project("protected-test-owner", {
            "title": "SQL cleanup isolation", "project_type": "promo_video",
            "platform": "TikTok", "duration_target": 30,
        })["id"]
        original = tmp_path / "sql-owner-original.mp4"
        original.write_bytes(b"original-master-file")
        preview = tmp_path / "sql-disposable-preview.mp4"
        preview.write_bytes(b"generated-preview")
        for asset_id, filename, metadata, status in [
            ("sql-original", original.name, {"source": "owner_video_import"}, "GENERATED"),
            ("sql-preview", preview.name, {"source": "generated_preview"}, "GENERATED"),
            ("sql-failed-import", "no-file.mp4", {"source": "owner_import"}, "ERROR"),
            ("sql-failed-preview", "no-file-2.mp4", {}, "ERROR"),
        ]:
            svc.store.save_asset(CreativeAsset(
                id=asset_id, project_id=project_id, owner_id="protected-test-owner",
                kind="video", title=asset_id, content="", status=status,
                url="/media/nova-creative/" + filename, metadata=metadata,
            ))
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        svc = CreativeStudioService(DbCreativeStudioStore(db2))
        assert svc.store.delete_failed_video_assets(project_id, "protected-test-owner") == 1
        removed = svc.store.delete_assets_by_ids(
            project_id, "protected-test-owner", {"sql-original", "sql-preview", "sql-failed-import"}
        )
        assert [a.id for a in removed] == ["sql-preview"]
        # Delete by ID removes the preview record; recreate it to exercise service-level unlink.
        svc.store.save_asset(CreativeAsset(
            id="sql-preview", project_id=project_id, owner_id="protected-test-owner",
            kind="video", title="Disposable", content="",
            url="/media/nova-creative/" + preview.name,
        ))
        reset = svc.reset_project_media("protected-test-owner", project_id)
        assert reset["deleted_media_files"] == 1
        assert not preview.exists()
        assert original.read_bytes() == b"original-master-file"
        rows = {a.id: a for a in svc.store.list_assets(project_id, "protected-test-owner")}
        assert "sql-original" in rows
        assert "sql-failed-import" in rows
        assert "sql-preview" not in rows
        assert hashlib.sha256(original.read_bytes()).hexdigest() == hashlib.sha256(
            b"original-master-file"
        ).hexdigest()
    finally:
        db2.close()


def test_authenticated_http_import_download_after_reset(tmp_path, monkeypatch):
    """HTTP import/download requires owner and returns original bytes after cleanup."""
    import hashlib
    import importlib

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.auth import UserContext, get_current_user_context
    from app.core.nova.creative_studio import video_import
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.router import router
    from app.core.nova.router import require_nova_access
    from app.db.session import get_db

    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    monkeypatch.setattr(video_import, "validate_video", lambda path: {
        "duration_seconds": 30.0, "width": 720, "height": 1280,
        "video_codec": "h264", "audio_codec": "aac", "decode_verified": True,
    })
    service = CreativeStudioService(CreativeStudioStore())
    routes = importlib.import_module("app.core.nova.creative_studio.router")
    monkeypatch.setattr(routes, "get_service", lambda db=None: service)
    user = {"id": "import-owner"}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_nova_access] = lambda: None
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user_context] = lambda: UserContext(
        user_id=user["id"], email="test-owner@example.invalid",
        role="staff", organization_id="test-org",
    )
    project_id = service.create_project("import-owner", {
        "title": "HTTP protected commercial", "project_type": "promo_video",
        "platform": "TikTok", "duration_target": 30,
    })["id"]
    original = b"fake-video-bytes-for-http-transport-only"
    client = TestClient(app)
    uploaded = client.post(
        f"/api/nova/creative/projects/{project_id}/finished-video-upload",
        files={"file": ("approved.mp4", original, "video/mp4")},
    )
    assert uploaded.status_code == 200, uploaded.text
    asset_id = uploaded.json()["asset"]["id"]
    url = f"/api/nova/creative/projects/{project_id}/assets/{asset_id}/file"
    result = client.get(url)
    assert result.status_code == 200, result.text
    assert result.headers["content-type"].startswith("video/mp4")
    assert "no-store" in result.headers["cache-control"]
    assert hashlib.sha256(result.content).hexdigest() == hashlib.sha256(original).hexdigest()
    assert client.get(url + "?token=forbidden").status_code == 400

    service.reset_project_media("import-owner", project_id)
    again = client.get(url)
    assert again.status_code == 200
    assert again.content == original

    user["id"] = "other-owner"
    assert client.get(url).status_code == 404
    assert client.post(
        f"/api/nova/creative/projects/{project_id}/finished-video-upload",
        files={"file": ("approved.mp4", original, "video/mp4")},
    ).status_code == 404
