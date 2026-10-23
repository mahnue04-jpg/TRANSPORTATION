"""Studio download auth, brand persistence, and commercial-complete gates.

No paid providers, no publication, and no production deploy.
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user_context
from app.core.nova.creative_studio.export import commercial_complete_allowed, providers_cleared
from app.core.nova.creative_studio.models import CreativeAsset
from app.core.nova.creative_studio.providers import provider_statuses
from app.core.nova.creative_studio.router import router
from app.core.nova.creative_studio.service import CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore
from app.core.nova.router import require_nova_access
from app.db.session import get_db

ROOT = Path(__file__).resolve().parents[1]
NOVA_URL = (
    "https://getamicor.com/nova-today/"
    "?utm_source=tiktok&utm_medium=profile_website&utm_campaign=nova_30s_commercial"
)


def _owner(user_id: str, organization_id: str) -> UserContext:
    return UserContext(
        user_id=user_id,
        email=f"{user_id}@example.invalid",
        role="staff",
        organization_id=organization_id,
    )


def _client(monkeypatch, service, tokens: dict[str, UserContext]):
    revoked: set[str] = set()

    def current_user(request: Request) -> UserContext:
        header = request.headers.get("authorization") or ""
        if not header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Authentication required")
        token = header.split(" ", 1)[1].strip()
        if token in revoked:
            raise HTTPException(status_code=401, detail="Session invalidated")
        user = tokens.get(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        return user

    studio_router = importlib.import_module("app.core.nova.creative_studio.router")
    monkeypatch.setattr(studio_router, "get_service", lambda db=None: service)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_nova_access] = lambda: None
    app.dependency_overrides[get_current_user_context] = current_user
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app), revoked


def _complete_metadata() -> dict:
    return {
        "pipeline": "presenter_30s",
        "presenter_used": True,
        "presenter": True,
        "lip_sync": True,
        "render_mode": "local_walking_commercial_30s",
        "quality_state": "OWNER_REVIEW_READY",
        "visual_mode": "provider_motion",
        "illustrated_fallback": False,
        "commercial_slideshow": False,
        "true_ai_motion_synthesis": True,
        "license_status": "GREEN",
        "provider_clearance": True,
        "narration": {"engine": "nova-neural", "license": "commercial-cleared"},
    }


def test_commercial_complete_requires_motion_lipsync_clean_narration_and_clearance():
    assert commercial_complete_allowed(_complete_metadata()) is True
    blocked = _complete_metadata()
    blocked.update({
        "quality_state": "PREVIEW_ONLY",
        "pipeline": "offline_title_card_fallback",
        "presenter_used": False,
        "presenter": False,
        "lip_sync": False,
        "render_mode": "offline_montage_not_lipsync",
        "true_ai_motion_synthesis": False,
        "provider_clearance": False,
        "license_status": "AMBER",
        "narration": {"engine": "espeak-ng", "license": "GPL-3.0-or-later"},
    })
    assert commercial_complete_allowed(blocked) is False
    for key, value in {
        "true_ai_motion_synthesis": False,
        "lip_sync": False,
        "provider_clearance": False,
        "license_status": "AMBER",
        "pipeline": "offline_title_card_fallback",
        "quality_state": "PREVIEW_ONLY",
    }.items():
        almost = _complete_metadata()
        almost[key] = value
        assert commercial_complete_allowed(almost) is False
    gpl = _complete_metadata()
    gpl["narration"] = {"engine": "espeak-ng", "license": "GPL-3.0-or-later"}
    assert commercial_complete_allowed(gpl) is False
    assert providers_cleared(provider_statuses()) is False


def test_brand_save_persists_on_the_project_and_click_verification_is_not_false_green():
    service = CreativeStudioService(CreativeStudioStore())
    project = service.create_project(
        "owner-a",
        {"title": "Validation 350", "project_type": "short_video", "platform": "TikTok", "duration_target": 30},
    )
    assert service.get_project("owner-a", project["id"])["brand"] is None
    brand = service.create_brand("owner-a", {"business_name": "AMICOR Nova", "tagline": "AI help"})
    service.attach_brand_to_project("owner-a", project["id"], brand["id"])
    saved = service.get_project("owner-a", project["id"])
    assert saved["brand"]["id"] == brand["id"]
    assert saved["brand"]["business_name"] == "AMICOR Nova"
    assert saved["project"]["brand_profile_id"] == brand["id"]

    def ok_fetch(url: str):
        assert url == NOVA_URL
        return 200, None

    verified = service.record_click_destination("owner-a", project["id"], "TikTok", fetch=ok_fetch)
    assert verified["verified"] is True
    assert verified["classification"] == "first_party_nova"
    assert verified["http_status"] == 200
    assert verified["commercial_complete"] is False
    assert verified["publish"] is False
    stored = service.get_project("owner-a", project["id"])["project"]["metadata"]["click_destination"]
    assert stored["verified"] is True
    assert stored["website_field_url"] == NOVA_URL

    def divert(url: str):
        if "nova-today" in url:
            return 302, "https://www.tiktok.com/"
        return 200, None

    diverted = service.record_click_destination("owner-a", project["id"], "TikTok", fetch=divert)
    assert diverted["verified"] is False
    assert diverted["classification"] == "platform_home"
    assert diverted["commercial_complete"] is False
    reread = service.get_project("owner-a", project["id"])["project"]["metadata"]["click_destination"]
    assert reread["verified"] is False

    def offline(url: str):
        return 503, None

    unreachable = service.record_click_destination("owner-a", project["id"], "TikTok", fetch=offline)
    assert unreachable["classification"] == "first_party_nova"
    assert unreachable["verified"] is False


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required to build a playable mp4")
def test_signed_in_download_caption_tenant_revocation_and_relogin(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(media))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    mp4 = media / "clip.mp4"
    ffmpeg = shutil.which("ffmpeg")
    encoded = subprocess.run(
        [
            ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-movflags", "+faststart", str(mp4),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if encoded.returncode != 0 or not mp4.is_file():
        pytest.skip("ffmpeg could not encode a playable H.264/AAC file")
    (media / "clip.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nVisit getamicor.com/nova-today\n",
        encoding="utf-8",
    )
    service = CreativeStudioService(CreativeStudioStore())
    project = service.create_project(
        "owner-a",
        {"title": "Validation 350", "project_type": "short_video", "platform": "TikTok", "duration_target": 30},
    )
    asset = CreativeAsset(
        id="asset-1",
        project_id=project["id"],
        owner_id="owner-a",
        kind="video",
        title="Offline 30s AMICOR Nova montage",
        content="PREVIEW_ONLY title cards",
        status="GENERATED",
        url="/media/nova-creative/clip.mp4",
        metadata={
            "final_promo": True,
            "render_mode": "offline_montage_not_lipsync",
            "quality_state": "PREVIEW_ONLY",
            "presenter_used": False,
            "pipeline": "offline_title_card_fallback",
            "lip_sync": False,
            "commercial_complete": False,
            "subtitle_url": "/media/nova-creative/clip.srt",
        },
    )
    service.store.save_asset(asset)
    owner = _owner("owner-a", "org-owner")
    other = _owner("owner-b", "org-other")
    client, revoked = _client(
        monkeypatch,
        service,
        {"owner-token": owner, "relogin-token": owner, "other-token": other},
    )
    path = f"/api/nova/creative/projects/{project['id']}/assets/{asset.id}/file"
    anonymous = client.get(path)
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"] == "Authentication required"

    owner_headers = {"Authorization": "Bearer owner-token"}
    downloaded = client.get(path, headers=owner_headers)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-type"].startswith("video/mp4")
    assert "attachment" in downloaded.headers["content-disposition"].lower()
    assert "Offline-30s-AMICOR-Nova-montage.mp4" in downloaded.headers["content-disposition"]
    assert "private" in downloaded.headers["cache-control"]
    assert b"ftyp" in downloaded.content[:64]
    played = tmp_path / "downloaded.mp4"
    played.write_bytes(downloaded.content)
    probe = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(played), "-f", "null", "-"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr

    captions = client.get(path + "?part=captions", headers=owner_headers)
    assert captions.status_code == 200, captions.text
    assert captions.headers["content-type"].startswith("application/x-subrip")
    assert "captions.srt" in captions.headers["content-disposition"]
    assert "getamicor.com/nova-today" in captions.text
    assert captions.content != downloaded.content

    leaked = client.get(path + "?access_token=owner-token", headers=owner_headers)
    assert leaked.status_code == 400
    assert "owner-token" not in leaked.text
    assert "Authorization header" in leaked.text

    denied = client.get(path, headers={"Authorization": "Bearer other-token"})
    assert denied.status_code in {403, 404}
    assert denied.status_code == 404
    assert b"ftyp" not in denied.content

    revoked.add("owner-token")
    expired = client.get(path, headers=owner_headers)
    assert expired.status_code == 401
    assert expired.json()["detail"] == "Session invalidated"

    relogin = client.get(path, headers={"Authorization": "Bearer relogin-token"})
    assert relogin.status_code == 200
    assert relogin.content == downloaded.content
    script = (ROOT / "static/nova-creative/creative.js").read_text(encoding="utf-8")
    assert "Bearer \" + currentToken" in script or 'headers.Authorization = "Bearer " + currentToken' in script
    assert "access_token=" not in script.split("assertDownloadUrlHasNoToken", 1)[1].split("downloadBrandedImage", 1)[0]
