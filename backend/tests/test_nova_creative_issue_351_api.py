"""Signed-in API path for Issue #351 TEST feature: license, checkout, walking commercial."""

from __future__ import annotations

import importlib
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user_context
from app.core.nova.creative_studio.router import router
from app.core.nova.creative_studio.service import CreativeStudioService
from app.core.nova.creative_studio.store import CreativeStudioStore
from app.core.nova.creative_studio.studio_checkout import (
    FakeStudioStripeClient,
    reset_studio_orders_for_tests,
    set_studio_stripe_override,
)
from app.core.nova.router import require_nova_access
from app.db.session import get_db


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


def test_guardrails_expose_studio_test_feature(monkeypatch):
    reset_studio_orders_for_tests()
    set_studio_stripe_override(FakeStudioStripeClient())
    service = CreativeStudioService(CreativeStudioStore())
    client, _holder = _client(monkeypatch, service, "owner-351-api")
    try:
        response = client.get("/api/nova/creative/guardrails")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["WALKING_COMMERCIAL_TEST_READY"] is True
        assert body["LIVE_STRIPE_BLOCKED"] is True
        assert body["studio_test_feature"]["walking_commercial_ready"] is True
        assert body["studio_test_feature"]["live_billing"] is False
        assert body["studio_test_feature"]["pricing"]["customer_price_usd"] == 49.0
    finally:
        set_studio_stripe_override(None)
        reset_studio_orders_for_tests()


def test_signed_in_test_checkout_and_license_flow(monkeypatch, tmp_path):
    reset_studio_orders_for_tests()
    set_studio_stripe_override(FakeStudioStripeClient())
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    service = CreativeStudioService(CreativeStudioStore())
    client, _holder = _client(monkeypatch, service, "owner-351-api")
    try:
        created = client.post(
            "/api/nova/creative/projects",
            json={
                "title": "TEST walking commercial",
                "project_type": "short_video",
                "platform": "TikTok",
                "duration_target": 30,
            },
        )
        assert created.status_code == 200, created.text
        project_id = created.json()["id"]

        pricing = client.get("/api/nova/creative/pricing")
        assert pricing.status_code == 200
        assert pricing.json()["customer_price_usd"] == 49.0

        license_resp = client.post(
            f"/api/nova/creative/projects/{project_id}/voice-license",
            json={"accepted": True, "note": "TEST accept"},
        )
        assert license_resp.status_code == 200, license_resp.text
        assert license_resp.json()["license_status"] == "GREEN"

        checkout = client.post(
            f"/api/nova/creative/projects/{project_id}/checkout",
            json={
                "success_url": "https://example.test/success",
                "cancel_url": "https://example.test/cancel",
            },
        )
        assert checkout.status_code == 200, checkout.text
        order_id = checkout.json()["order"]["id"]
        assert checkout.json()["order"]["auto_billing"] is False

        paid = client.post(f"/api/nova/creative/projects/{project_id}/checkout/orders/{order_id}/complete-test")
        assert paid.status_code == 200, paid.text
        assert paid.json()["order"]["status"] == "paid"
        assert paid.json()["receipt"]["receipt_id"].startswith("rcpt_")
        assert paid.json()["job_status"] == "queued_for_production"

        orders = client.get(f"/api/nova/creative/projects/{project_id}/checkout/orders")
        assert orders.status_code == 200
        assert len(orders.json()["orders"]) == 1
    finally:
        set_studio_stripe_override(None)
        reset_studio_orders_for_tests()


@pytest.mark.slow
def test_signed_in_walking_commercial_download(monkeypatch, tmp_path):
    pytest.importorskip("edge_tts")
    pytest.importorskip("PIL")
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_PUBLIC_PREFIX", "/media/nova-creative")
    service = CreativeStudioService(CreativeStudioStore())
    client, _holder = _client(monkeypatch, service, "owner-351-api")

    created = client.post(
        "/api/nova/creative/projects",
        json={
            "title": "TEST 30s walking",
            "project_type": "short_video",
            "platform": "TikTok",
            "duration_target": 30,
        },
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    service.generate_storyboard("owner-351-api", project_id)
    client.post(
        f"/api/nova/creative/projects/{project_id}/voice-license",
        json={"accepted": True, "note": "TEST"},
    )

    rendered = client.post(f"/api/nova/creative/projects/{project_id}/assemble/walking-commercial-30s")
    assert rendered.status_code == 200, rendered.text
    body = rendered.json()
    assert body["paid_provider_charges"] is False
    if body.get("ready") is not True:
        job_id = body["job"]["id"]
        assert body["job"]["status"] in {"QUEUED", "RUNNING"}
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            polled = client.get(f"/api/nova/creative/projects/{project_id}/jobs/{job_id}")
            assert polled.status_code == 200, polled.text
            body = polled.json()
            if body.get("ready") and body["job"]["status"] == "GENERATED":
                break
            assert body["job"]["status"] != "ERROR", body["job"].get("message")
            time.sleep(0.5)
    assert body["job"]["status"] == "GENERATED"
    assert body.get("ready") is True
    asset_meta = (body.get("asset") or {}).get("metadata") or {}
    validation = body.get("validation") or asset_meta.get("validation") or {}
    assert body.get("lip_sync") is True or asset_meta.get("lip_sync") is True
    assert body.get("mobile_download_ready") is True or asset_meta.get("mobile_download_ready") is True
    assert body.get("license_status") == "GREEN" or asset_meta.get("license_status") == "GREEN"
    assert body["paid_provider_charges"] is False
    assert 28.0 <= float(validation["duration_seconds"]) <= 32.0

    asset_id = body["asset"]["id"]
    download = client.get(f"/api/nova/creative/projects/{project_id}/assets/{asset_id}/file")
    assert download.status_code == 200
    assert download.headers.get("content-type", "").startswith("video/")
    assert len(download.content) > 1000
    video = tmp_path / Path(body["url"]).name
    assert video.is_file()


def test_walking_commercial_post_returns_job_before_render(monkeypatch, tmp_path):
    """The owner request must return a job id before the MP4 exists."""
    monkeypatch.setenv("NOVA_CREATIVE_MEDIA_DIR", str(tmp_path))
    service = CreativeStudioService(CreativeStudioStore())
    client, _holder = _client(monkeypatch, service, "owner-351-queue")
    created = client.post(
        "/api/nova/creative/projects",
        json={"title": "Queue 30s", "project_type": "short_video", "platform": "TikTok", "duration_target": 30},
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    service.generate_storyboard("owner-351-queue", project_id)
    gate = {"release": False}

    def slow_render(owner_id, project_id_arg, existing_job_id=None):
        job = next(row for row in service.store.list_jobs(project_id_arg, owner_id) if row.id == existing_job_id)
        service._finish_job(
            job,
            status="RUNNING",
            message="still rendering",
            asset_ids=[],
            provider="nova_walking_commercial",
        )
        deadline = time.monotonic() + 2
        while not gate["release"] and time.monotonic() < deadline:
            time.sleep(0.05)
        service._finish_job(
            job,
            status="GENERATED",
            message="saved",
            asset_ids=[],
            provider="nova_walking_commercial",
        )
        return {"job": job.as_dict()}

    service.render_walking_commercial_30s = slow_render
    started = time.monotonic()
    rendered = client.post(f"/api/nova/creative/projects/{project_id}/assemble/walking-commercial-30s")
    elapsed = time.monotonic() - started
    assert rendered.status_code == 200, rendered.text
    body = rendered.json()
    assert elapsed < 0.75, elapsed
    assert body["ready"] is False
    assert body["paid_provider_charges"] is False
    assert body["job"]["status"] in {"QUEUED", "RUNNING"}
    job_id = body["job"]["id"]
    assert job_id
    early = client.get(f"/api/nova/creative/projects/{project_id}/jobs/{job_id}")
    assert early.status_code == 200
    assert early.json()["ready"] is False
    gate["release"] = True
    deadline = time.monotonic() + 3
    final = early.json()
    while time.monotonic() < deadline:
        final = client.get(f"/api/nova/creative/projects/{project_id}/jobs/{job_id}").json()
        if final["job"]["status"] == "GENERATED":
            break
        time.sleep(0.05)
    assert final["job"]["status"] == "GENERATED"
    # No video asset was saved by the stub, so success stays withheld.
    assert final["ready"] is False
