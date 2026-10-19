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
    queued = rendered.json()
    assert queued["ready"] is False
    assert queued["mobile_download_ready"] is False
    assert queued["paid_provider_charges"] is False
    assert queued["job"]["status"] == "RUNNING"
    job_id = queued["job"]["id"]

    body = None
    for _ in range(180):
        polled = client.get(f"/api/nova/creative/projects/{project_id}/jobs/{job_id}")
        assert polled.status_code == 200, polled.text
        body = polled.json()
        if body.get("ready") is True:
            break
    assert body is not None and body["ready"] is True
    assert body["job"]["status"] == "GENERATED"
    assert body["paid_provider_charges"] is False
    assert body["url"]
    assert body["download_url"]
    validation = body["validation"]
    assert 28.0 <= float(validation["duration_seconds"]) <= 32.0
    assert validation["checks"]["has_audio"] is True
    assert validation["checks"]["audio_aac"] is True

    asset_id = body["asset"]["id"]
    download = client.get(f"/api/nova/creative/projects/{project_id}/assets/{asset_id}/file")
    assert download.status_code == 200
    assert download.headers.get("content-type", "").startswith("video/")
    assert len(download.content) > 1000
    video = tmp_path / Path(body["url"]).name
    assert video.is_file()
    captions = video.with_suffix(".srt")
    assert captions.is_file()
    assert captions.read_text(encoding="utf-8").strip()
    refreshed = client.get(f"/api/nova/creative/projects/{project_id}")
    assert refreshed.status_code == 200
    saved = [row for row in refreshed.json()["assets"] if row["id"] == asset_id]
    assert saved and saved[0]["url"] == body["url"]
    replay = client.get(f"/api/nova/creative/projects/{project_id}/assets/{asset_id}/file")
    assert replay.status_code == 200
    assert replay.content == download.content

    playwright_sync = pytest.importorskip("playwright.sync_api")
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
        )
        page = context.new_page()
        try:
            page.goto(video.as_uri())
            played = page.evaluate(
                """() => {
                  const v = document.querySelector('video');
                  if (!v) return {ok: false, reason: 'no video element'};
                  return new Promise((resolve) => {
                    const finish = () => resolve({
                      ok: Number.isFinite(v.duration) && v.duration >= 28 && v.duration <= 32 && v.readyState >= 1,
                      duration: v.duration,
                      width: v.videoWidth,
                      height: v.videoHeight
                    });
                    if (v.readyState >= 1) finish();
                    else v.onloadedmetadata = finish;
                    v.onerror = () => resolve({ok: false, reason: 'decode error'});
                  });
                }"""
            )
            assert played["ok"] is True, played
            page.goto((Path(__file__).resolve().parents[1] / "static/nova-creative/index.html").as_uri())
            assert page.locator("#build-walking-commercial-30s").is_visible()
            assert page.get_by_text("60-second full-body demo").is_visible()
            fits = page.evaluate(
                "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
            )
            assert fits
        finally:
            browser.close()
