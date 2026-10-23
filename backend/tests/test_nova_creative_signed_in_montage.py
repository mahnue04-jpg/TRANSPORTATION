"""Signed-in offline montage: create, poll, persist, and download. No paid render."""
from __future__ import annotations

import importlib
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user_context
from app.core.nova.creative_studio.router import router
from app.core.nova.creative_studio.service import CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore
from app.core.nova.router import require_nova_access
from app.db.session import get_db

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    shutil.which("espeak-ng") is None and shutil.which("espeak") is None,
    reason="local narration engine is not installed",
)


def _client(monkeypatch, service, user_id):
    holder = {
        "user": UserContext(
            user_id=user_id,
            email=f"{user_id}@example.invalid",
            role="staff",
            organization_id="org-a",
        )
    }
    studio_router = importlib.import_module("app.core.nova.creative_studio.router")
    monkeypatch.setattr(studio_router, "get_service", lambda db=None: service)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_nova_access] = lambda: None
    app.dependency_overrides[get_current_user_context] = lambda: holder["user"]
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app), holder


def test_signed_in_owner_polls_and_downloads_offline_montage(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    service = CreativeStudioService(CreativeStudioStore())
    client, holder = _client(monkeypatch, service, "owner-a")
    created = client.post(
        "/api/nova/creative/projects",
        json={
            "title": "AMICOR Nova 30s commercial",
            "project_type": "short_video",
            "platform": "TikTok",
            "duration_target": 30,
        },
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    service.generate_storyboard("owner-a", project_id)

    quote = client.get(f"/api/nova/creative/projects/{project_id}/preflight")
    assert quote.status_code == 200, quote.text
    assert quote.json()["purchasing_enabled"] is False
    assert quote.json()["requires_owner_budget_confirmation"] is True
    assert quote.json()["auto_top_up"] is False
    blocked = client.post(
        f"/api/nova/creative/projects/{project_id}/budget-confirm",
        json={"confirmed": True, "acknowledged_estimate_usd": quote.json()["estimated_total_usd"]},
    )
    if quote.json()["paid_render_allowed"] is False:
        assert blocked.status_code == 422
        assert blocked.json()["detail"]["code"] == "PAID_RENDER_BLOCKED"

    rendered = client.post(f"/api/nova/creative/projects/{project_id}/assemble/offline-commercial")
    assert rendered.status_code == 200, rendered.text
    body = rendered.json()
    assert body["lip_sync"] is False
    assert body["render_mode"] == "offline_montage_not_lipsync"
    assert body["paid_provider_charges"] is False
    assert body["paid_render_allowed"] is False
    assert body["license_status"] == "AMBER"
    assert "GPL-3.0-or-later" in body["commercial_use"]
    job_id = body["job"]["id"]
    asset_id = body["asset"]["id"]

    polled = client.get(f"/api/nova/creative/projects/{project_id}/jobs/{job_id}")
    assert polled.status_code == 200, polled.text
    assert polled.json()["ready"] is True
    assert polled.json()["job"]["status"] == "GENERATED"
    assert polled.json()["lip_sync"] is False
    assert polled.json()["paid_provider_charges"] is False

    detail = client.get(f"/api/nova/creative/projects/{project_id}")
    assert detail.status_code == 200
    assets = {item["id"]: item for item in detail.json()["assets"]}
    assert assets[asset_id]["metadata"]["render_mode"] == "offline_montage_not_lipsync"
    assert assets[asset_id]["metadata"]["lip_sync"] is False
    assert assets[asset_id]["metadata"]["quality_state"] == "PREVIEW_ONLY"
    assert assets[asset_id]["metadata"]["presenter_used"] is False
    assert assets[asset_id]["metadata"]["pipeline"] == "offline_title_card_fallback"
    assert assets[asset_id]["metadata"]["commercial_complete"] is False
    assert assets[asset_id]["media_available"] is True

    downloaded = client.get(f"/api/nova/creative/projects/{project_id}/assets/{asset_id}/file")
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-type"].startswith("video/mp4")
    assert len(downloaded.content) > 1000
    assert b"ftyp" in downloaded.content[:64]

    holder["user"] = UserContext(
        user_id="owner-b",
        email="owner-b@example.invalid",
        role="staff",
        organization_id="org-a",
    )
    denied = client.get(f"/api/nova/creative/projects/{project_id}/assets/{asset_id}/file")
    assert denied.status_code == 404
    denied_job = client.get(f"/api/nova/creative/projects/{project_id}/jobs/{job_id}")
    assert denied_job.status_code == 404

    html = (ROOT / "static/nova-creative/index.html").read_text(encoding="utf-8")
    script = (ROOT / "static/nova-creative/creative.js").read_text(encoding="utf-8")
    css = (ROOT / "static/nova-creative/creative.css").read_text(encoding="utf-8")
    assert "studio-provider-status-20261023" in html
    assert "Offline montage, not lip sync" in script
    assert "Download offline montage" in script
    assert "PREVIEW_ONLY" in script
    assert "Presenter NOT USED" in script
    assert "downloadProtectedAsset" in script
    assert "?part=captions" in script
    assert "Commercial-use clearance" in script
    assert "playsinline" in script
    assert "@media (max-width: 420px)" in css
