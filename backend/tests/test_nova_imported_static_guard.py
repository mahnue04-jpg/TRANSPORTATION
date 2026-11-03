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
