"""Signed-in API path for Issue #351 TEST feature: license, checkout, walking commercial."""

from __future__ import annotations

import importlib
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
    assert body["lip_sync"] is True
    assert body["mobile_download_ready"] is True
    assert body["license_status"] == "GREEN"
    assert body["paid_provider_charges"] is False
    assert 28.0 <= float(body["validation"]["duration_seconds"]) <= 32.0

    asset_id = body["asset"]["id"]
    download = client.get(f"/api/nova/creative/projects/{project_id}/assets/{asset_id}/file")
    assert download.status_code == 200
    assert download.headers.get("content-type", "").startswith("video/")
    assert len(download.content) > 1000
    video = tmp_path / Path(body["url"]).name
    assert video.is_file()
