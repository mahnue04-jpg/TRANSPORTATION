"""Regression tests for Creative Studio imported-original static URL isolation."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.nova.creative_studio.public_media_guard import GuardedCreativeStaticFiles


def test_owner_import_is_not_public_through_any_static_alias(tmp_path: Path):
    # The same storage tree can be mounted under a main media path and
    # aliases used by the site's static bundle.
    imported = tmp_path / "imported_video_secret.mp4"
    imported.write_bytes(b"private-original")
    preview = tmp_path / "preview.mp4"
    preview.write_bytes(b"disposable-preview")
    app = FastAPI()
    for prefix in ("/media/nova-creative", "/static", "/assets"):
        app.mount(prefix, GuardedCreativeStaticFiles(directory=tmp_path))
    client = TestClient(app)
    for prefix in ("/media/nova-creative", "/static", "/assets"):
        denied = client.get(prefix + "/" + imported.name)
        assert denied.status_code == 404
        assert b"private-original" not in denied.content
        assert "no-store" in denied.headers.get("cache-control", "")
        permitted = client.get(prefix + "/preview.mp4")
        assert permitted.status_code == 200
        assert permitted.content == b"disposable-preview"


def test_nonimport_name_still_served_and_import_path_cannot_bypass(tmp_path: Path):
    (tmp_path / "imported_video_hidden.mp4").write_bytes(b"original")
    (tmp_path / "public-thumbnail.png").write_bytes(b"thumbnail")
    client = TestClient(FastAPI())
    client.app.mount("/media/nova-creative", GuardedCreativeStaticFiles(directory=tmp_path))
    assert client.get("/media/nova-creative/imported_video_hidden.mp4").status_code == 404
    assert client.get("/media/nova-creative/public-thumbnail.png").content == b"thumbnail"


def test_imported_original_saved_outside_public_mount_and_owner_can_read(tmp_path, monkeypatch):
    """Private asset reference remains owner-readable, but not static-readable."""
    from app.core.nova.creative_studio import video_import
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.store import CreativeStudioStore

    public_dir = tmp_path / "public"
    private_dir = tmp_path / "private"
    public_dir.mkdir()
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(public_dir))
    monkeypatch.setenv("NOVA_CREATIVE_PRIVATE_MEDIA_DIR", str(private_dir))
    monkeypatch.setattr(video_import, "validate_video", lambda path: {
        "duration_seconds": 1.0, "video_codec": "h264",
        "audio_codec": "aac", "decode_verified": True,
    })
    service = CreativeStudioService(CreativeStudioStore())
    project_id = service.create_project("owner", {
        "title": "Private originals", "project_type": "promo_video",
        "platform": "TikTok", "duration_target": 30,
    })["id"]
    original = b"mock-private-original-no-real-codec"
    asset = service.import_finished_video("owner", project_id, original, content_type="video/mp4")["asset"]
    assert asset["url"].startswith("private-media://")
    path, mime, _ = service.open_asset_file("owner", project_id, asset["id"])
    assert path.read_bytes() == original
    assert mime == "video/mp4"
    assert path.parent == private_dir
    assert not list(public_dir.glob("imported_video_*.mp4"))
    app = FastAPI()
    app.mount("/media/nova-creative", GuardedCreativeStaticFiles(directory=public_dir))
    client = TestClient(app)
    assert client.get("/media/nova-creative/" + path.name).status_code == 404
    from app.core.nova.creative_studio.service import CreativeStudioError
    import pytest
    with pytest.raises(CreativeStudioError) as exc:
        service.open_asset_file("other-owner", project_id, asset["id"])
    assert exc.value.http_status == 404


def test_private_root_cannot_be_configured_under_public_static_root(tmp_path, monkeypatch):
    from app.core.nova.creative_studio.providers import _creative_private_media_root
    import pytest
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(public_dir))
    monkeypatch.setenv("NOVA_CREATIVE_PRIVATE_MEDIA_DIR", str(public_dir / "private"))
    with pytest.raises(ValueError, match="public static root"):
        _creative_private_media_root()
