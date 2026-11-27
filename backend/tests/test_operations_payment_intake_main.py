"""Hosted Render entry (app.main:app) must expose Operations payment intake.

Preserves exact POST /payments/stripe/webhook, signature verification, live-only
enforcement, and idempotent recording. Distinct from Ride/Deliver
POST /api/payments/stripe/webhook. Does not enable live sales.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
import operations_payment_intake as intake


@pytest.fixture
def clear_ops_env(monkeypatch):
    for key in (
        "NOVA_OPERATIONS_LIVE_WEBHOOK_SECRET",
        "NOVA_OPERATIONS_DATABASE_URL",
        "NOVA_STRIPE_LIVE_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED",
        "APP_ENV",
        "AMICOR_ENVIRONMENT",
    ):
        monkeypatch.delenv(key, raising=False)


def _signed(secret: str, event: dict):
    data = json.dumps(event).encode()
    stamp = str(int(time.time()))
    digest = hmac.new(secret.encode(), stamp.encode() + b"." + data, hashlib.sha256).hexdigest()
    return data, {"stripe-signature": f"t={stamp},v1={digest}"}


def test_main_app_registers_exact_operations_webhook_path(clear_ops_env):
    paths = set(app.openapi().get("paths", {}))
    assert "/payments/stripe/webhook" in paths
    assert "/payments/operations/readiness" in paths
    # Customer Ride/Deliver webhook remains a different path (no collision).
    assert "/api/payments/stripe/webhook" in paths
    assert "/payments/stripe/webhook" != "/api/payments/stripe/webhook"


def test_main_app_webhook_signature_live_and_idempotency(clear_ops_env, monkeypatch):
    secret = "whsec_main_entry_receiver"
    event = {
        "id": "evt_main", "object": "event", "type": "invoice.paid",
        "livemode": True, "data": {"object": {"id": "in_main", "object": "invoice"}},
    }
    recorded = []

    def fake_record(database_url, event_id, event_type, object_id):
        recorded.append((event_id, event_type, object_id))

    monkeypatch.setenv("NOVA_OPERATIONS_LIVE_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("NOVA_OPERATIONS_DATABASE_URL", "postgresql://synthetic")
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false")

    with patch.object(intake, "record_event", side_effect=fake_record):
        client = TestClient(app)
        data, headers = _signed(secret, event)
        assert client.post("/payments/stripe/webhook", content=data, headers=headers).status_code == 200
        assert client.post("/payments/stripe/webhook", content=data, headers=headers).status_code == 200
        assert client.post("/payments/stripe/webhook").status_code == 400
        event["livemode"] = False
        data_test, headers_test = _signed(secret, event)
        assert client.post(
            "/payments/stripe/webhook", content=data_test, headers=headers_test,
        ).status_code == 400
    assert recorded == [
        ("evt_main", "invoice.paid", "in_main"),
        ("evt_main", "invoice.paid", "in_main"),
    ]


def test_main_app_readiness_exposes_no_secrets(clear_ops_env, monkeypatch):
    monkeypatch.setenv("NOVA_OPERATIONS_LIVE_WEBHOOK_SECRET", "whsec_readiness_probe")
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false")
    with patch.object(intake, "operations_production_readiness") as readiness:
        readiness.return_value = {
            "service": "nova-operations",
            "live_sales_enabled": False,
            "payment_receiver": {
                "webhook_path": "/payments/stripe/webhook",
                "webhook_secret_configured": True,
                "database_url_configured": False,
                "writer_permissions_ok": None,
                "writer_probe_error": False,
            },
            "private_storage": {
                "production_runtime_markers": False,
                "dedicated_credentials_configured": False,
                "settings_ok": None,
                "separate_from_document_bucket": None,
            },
            "authentication_gates": {
                "starter_access_mode": None,
                "starter_binding_mode": None,
                "customer_delivery_mode": None,
                "revenue_recording_mode": None,
            },
            "required_configuration": {
                "app_env_production": False,
                "amicor_environment_production": False,
                "stripe_live_flag": False,
                "customer_sales_flag": False,
                "starter_price_matches_catalog": False,
                "billing_trial_disabled": False,
            },
        }
        client = TestClient(app)
        response = client.get("/payments/operations/readiness")
    assert response.status_code == 200
    body = response.json()
    dumped = json.dumps(body)
    assert "whsec_" not in dumped
    assert "sk_live" not in dumped
    assert "postgresql://" not in dumped
    assert body["live_sales_enabled"] is False
    assert body["payment_receiver"]["webhook_path"] == "/payments/stripe/webhook"
    assert body["payment_receiver"]["webhook_secret_configured"] is True


def test_operations_production_readiness_booleans_without_secret_values(clear_ops_env, monkeypatch):
    monkeypatch.setenv("NOVA_OPERATIONS_LIVE_WEBHOOK_SECRET", "whsec_synthetic_only")
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false")
    report = intake.operations_production_readiness(probe_database=False)
    text = json.dumps(report)
    assert "whsec_synthetic_only" not in text
    assert report["live_sales_enabled"] is False
    assert report["payment_receiver"]["webhook_secret_configured"] is True
    assert report["payment_receiver"]["database_url_configured"] is False
    assert report["authentication_gates"]["starter_access_mode"] is None
