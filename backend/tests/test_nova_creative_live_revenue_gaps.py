"""LIVE revenue gaps for Creative Studio second commercial (#351).

Covers: durable orders, Stripe webhook fulfill, gated LIVE checkout.
Does not touch the approved 60s commercial or Lifesaver surfaces.
"""

from __future__ import annotations

import importlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.nova.creative_studio.router import webhook_router
from app.core.nova.creative_studio.studio_checkout import (
    FakeStudioStripeClient,
    checkout_readiness,
    create_studio_checkout_order,
    get_studio_order,
    process_studio_webhook,
    reset_studio_orders_for_tests,
    set_studio_stripe_override,
    stripe_runtime_mode,
    verify_studio_webhook,
)
from app.db.session import get_db


def test_live_checkout_blocked_without_owner_flag(monkeypatch):
    reset_studio_orders_for_tests()
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_" + "live_" + "fake_for_mode_only")
    monkeypatch.delenv("NOVA_CREATIVE_STRIPE_LIVE_ENABLED", raising=False)
    set_studio_stripe_override(None)
    try:
        assert stripe_runtime_mode() == "live_blocked"
        readiness = checkout_readiness()
        assert readiness["live_blocked"] is True
        assert readiness["live_checkout_available"] is False
    finally:
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        reset_studio_orders_for_tests()


def test_gated_live_checkout_allowed_when_flag_on(monkeypatch):
    reset_studio_orders_for_tests()
    fake = FakeStudioStripeClient()
    set_studio_stripe_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_" + "live_" + "fake_for_mode_only")
    monkeypatch.setenv("NOVA_CREATIVE_STRIPE_LIVE_ENABLED", "true")
    # Override forces test_fake mode; clear it to exercise live path mode detection,
    # then use LiveStudioStripeClient block via override-free fake by temporarily
    # forcing mode through override after asserting readiness separately.
    set_studio_stripe_override(None)
    try:
        assert stripe_runtime_mode() == "live"
        readiness = checkout_readiness()
        assert readiness["live_checkout_available"] is True
        assert readiness["live_blocked"] is False
    finally:
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        monkeypatch.delenv("NOVA_CREATIVE_STRIPE_LIVE_ENABLED", raising=False)
        set_studio_stripe_override(None)
        reset_studio_orders_for_tests()


def test_create_order_in_gated_live_mode_persists_and_does_not_hard_block(monkeypatch):
    """With LIVE flag on + fake client, checkout creates an order (no hard TEST-only raise)."""
    reset_studio_orders_for_tests()
    fake = FakeStudioStripeClient()
    set_studio_stripe_override(fake)
    # Override makes mode test_fake; explicitly verify the former hard-block is gone
    # by monkeypatching stripe_runtime_mode to live while still using fake client.
    monkeypatch.setattr(
        "app.core.nova.creative_studio.studio_checkout.stripe_runtime_mode",
        lambda: "live",
    )
    try:
        started = create_studio_checkout_order(
            owner_id="owner-live",
            project_id="proj-live",
            success_url="https://example.test/success",
            cancel_url="https://example.test/cancel",
            estimated_render_cost_usd=2.0,
        )
        order = started["order"]
        assert order["payment_mode"] == "live"
        assert started["checkout"]["payment_mode"] == "live"
        assert "LIVE" in started["message"]
        loaded = get_studio_order(order["id"], owner_id="owner-live")
        assert loaded is not None
        assert loaded["id"] == order["id"]
    finally:
        set_studio_stripe_override(None)
        reset_studio_orders_for_tests()


def test_webhook_fulfills_paid_order_idempotently():
    reset_studio_orders_for_tests()
    fake = FakeStudioStripeClient()
    set_studio_stripe_override(fake)
    try:
        started = create_studio_checkout_order(
            owner_id="owner-wh",
            project_id="proj-wh",
            success_url="https://example.test/success",
            cancel_url="https://example.test/cancel",
            estimated_render_cost_usd=1.5,
        )
        order_id = started["order"]["id"]
        session_id = started["checkout"]["id"]
        event = {
            "id": "evt_studio_live_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": session_id,
                    "object": "checkout.session",
                    "status": "complete",
                    "payment_status": "paid",
                    "payment_intent": "pi_test_studio_1",
                    "client_reference_id": order_id,
                    "metadata": {
                        "amicor_product": "nova_creative_studio",
                        "order_id": order_id,
                        "owner_id": "owner-wh",
                        "project_id": "proj-wh",
                    },
                }
            },
        }
        first = process_studio_webhook(event)
        assert first["duplicate"] is False
        assert first["order_id"] == order_id
        assert first["result"] in {"queued_for_production", "fulfilled"}
        order = get_studio_order(order_id, owner_id="owner-wh")
        assert order is not None
        assert order["status"] == "paid"
        assert order["receipt"]["receipt_id"].startswith("rcpt_")
        assert order["fulfillment"]["paid_providers_activated"] is False
        assert order["fulfillment"]["approved_60s_commercial_unchanged"] is True
        assert order["job_status"] in {"queued_for_production", "ready_for_download"}

        second = process_studio_webhook(event)
        assert second["duplicate"] is True
        assert second["result"] == "ignored"
    finally:
        set_studio_stripe_override(None)
        reset_studio_orders_for_tests()


def test_webhook_http_route_without_auth():
    reset_studio_orders_for_tests()
    fake = FakeStudioStripeClient()
    set_studio_stripe_override(fake)
    app = FastAPI()
    app.include_router(webhook_router)
    app.dependency_overrides[get_db] = lambda: None
    client = TestClient(app)
    try:
        started = create_studio_checkout_order(
            owner_id="owner-http",
            project_id="proj-http",
            success_url="https://example.test/success",
            cancel_url="https://example.test/cancel",
            estimated_render_cost_usd=1.0,
        )
        order_id = started["order"]["id"]
        payload = {
            "id": "evt_studio_http_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": started["checkout"]["id"],
                    "status": "complete",
                    "payment_status": "paid",
                    "client_reference_id": order_id,
                    "metadata": {"order_id": order_id, "owner_id": "owner-http", "project_id": "proj-http"},
                }
            },
        }
        # Fake override + missing signature is allowed (same pattern as marketplace tests).
        response = client.post("/api/nova/creative/stripe/webhook", content=json.dumps(payload))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["order_id"] == order_id
        order = get_studio_order(order_id, owner_id="owner-http")
        assert order["status"] == "paid"
        assert order["fulfillment"]["production_path"] == "local_walking_commercial_30s"
    finally:
        set_studio_stripe_override(None)
        reset_studio_orders_for_tests()
        app.dependency_overrides.clear()


def test_verify_webhook_requires_secret_without_override(monkeypatch):
    reset_studio_orders_for_tests()
    set_studio_stripe_override(None)
    monkeypatch.delenv("STRIPE_NOVA_CREATIVE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    try:
        from app.core.nova.creative_studio.studio_checkout import StudioCheckoutError

        try:
            verify_studio_webhook(b'{"id":"evt_x"}', "t=1,v1=abc")
            raised = False
        except StudioCheckoutError as exc:
            raised = True
            assert exc.status_code == 503
        assert raised
    finally:
        reset_studio_orders_for_tests()


def test_guardrails_expose_durable_orders_and_webhook_fields(monkeypatch):
    from app.auth import UserContext, get_current_user_context
    from app.core.nova.creative_studio.router import router
    from app.core.nova.creative_studio.service import CreativeStudioService
    from app.core.nova.creative_studio.store import CreativeStudioStore
    from app.core.nova.router import require_nova_access

    reset_studio_orders_for_tests()
    set_studio_stripe_override(FakeStudioStripeClient())
    service = CreativeStudioService(CreativeStudioStore())
    studio_router = importlib.import_module("app.core.nova.creative_studio.router")
    monkeypatch.setattr(studio_router, "get_service", lambda db=None: service)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_nova_access] = lambda: None
    app.dependency_overrides[get_current_user_context] = lambda: UserContext(
        user_id="owner-gaps",
        email="owner-gaps@example.invalid",
        role="staff",
        organization_id="org-a",
    )
    app.dependency_overrides[get_db] = lambda: None
    client = TestClient(app)
    try:
        response = client.get("/api/nova/creative/guardrails")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["STUDIO_DURABLE_ORDERS"] is True
        assert body["studio_test_feature"]["durable_orders"] is True
        assert body["studio_test_feature"]["approved_60s_commercial_unchanged"] is True
        assert "LIVE_STRIPE_CHECKOUT_AVAILABLE" in body
    finally:
        set_studio_stripe_override(None)
        reset_studio_orders_for_tests()
        app.dependency_overrides.clear()
