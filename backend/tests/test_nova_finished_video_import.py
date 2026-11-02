"""Owner-scoped finished MP4 import preserves bytes without generating media."""
import hashlib
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user_context
from app.core.nova.creative_studio.router import router
from app.core.nova.creative_studio.service import CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore
from app.core.nova.router import require_nova_access
from app.db.session import get_db

# A container-header fixture, not a claim that these bytes are playable media.
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"original-fixture-bytes"


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    service = CreativeStudioService(CreativeStudioStore())
    routes = importlib.import_module("app.core.nova.creative_studio.router")
    monkeypatch.setattr(routes, "get_service", lambda db=None: service)
    user = {"id": "owner-a"}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_nova_access] = lambda: None
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user_context] = lambda: UserContext(
        user_id=user["id"], email=user["id"] + "@example.invalid",
        role="staff", organization_id="test-org",
    )
    client = TestClient(app)
    project = client.post("/api/nova/creative/projects", json={
        "title": "Approved commercial", "project_type": "promo_video",
        "duration_target": 30, "platform": "TikTok",
    })
    assert project.status_code == 200, project.text
    return client, user, project.json()["id"], tmp_path


def upload(client, project_id, *, data=MP4, source="owner_import", filename="approved.mp4", mime="video/mp4"):
    return client.post(
        f"/api/nova/creative/projects/{project_id}/assets/browser-final-promo",
        files={"file": (filename, data, mime)}, data={"source": source},
    )


def test_import_readback_and_download_preserve_original_bytes(studio):
    client, user, project_id, directory = studio
    saved = upload(client, project_id)
    assert saved.status_code == 200, saved.text
    asset = saved.json()["asset"]
    metadata = asset["metadata"]
    assert metadata["source"] == "owner_import"
    assert metadata["sha256"] == hashlib.sha256(MP4).hexdigest()
    assert metadata["publish_ready"] is False
    assert metadata["owner_review_required"] is True
    assert metadata.get("commercial_complete") is not True
    assert "Owner-imported" in asset["content"]
    assert "assembled" not in asset["content"]
    detail = client.get(f"/api/nova/creative/projects/{project_id}")
    assert detail.status_code == 200
    readback = next(a for a in detail.json()["assets"] if a["id"] == asset["id"])
    assert readback["media_available"] is True
    download_path = f"/api/nova/creative/projects/{project_id}/assets/{asset['id']}/file"
    download = client.get(download_path)
    assert download.status_code == 200, download.text
    assert download.content == MP4
    assert len(list(directory.glob("*.mp4"))) == 1
    # Same organization is insufficient: the project and file remain owner scoped.
    user["id"] = "owner-b"
    assert client.get(download_path).status_code == 404
    assert upload(client, project_id).status_code == 404
    assert len(list(directory.glob("*.mp4"))) == 1


@pytest.mark.parametrize("overrides", [
    {"data": b"not an MP4"}, {"data": b""}, {"source": "generated"},
    {"filename": "file.html"}, {"mime": "text/html"},
])
def test_invalid_import_creates_no_asset_or_file(studio, overrides):
    client, _, project_id, directory = studio
    response = upload(client, project_id, **overrides)
    assert response.status_code == 422, response.text
    assert not list(directory.iterdir())
    assert client.get(f"/api/nova/creative/projects/{project_id}").json()["assets"] == []


def test_existing_browser_assembly_upload_remains_compatible(studio):
    client, _, project_id, _ = studio
    response = client.post(
        f"/api/nova/creative/projects/{project_id}/assets/browser-final-promo",
        files={"file": ("preview.webm", b"existing browser preview", "video/webm")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["asset"]["metadata"]["render_mode"] == "browser_safe_upload"
