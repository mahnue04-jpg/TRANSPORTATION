"""Operations webhook routes stay distinct and never publish signing secrets."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.core.nova.work_revenue.operations_webhook_contract import (
    EXCLUDED_WEBHOOK_PATHS,
    MARKETING_REQUIRED_EVENTS,
    MARKETING_WEBHOOK_PATH,
    PAYMENT_INTAKE_WEBHOOK_PATH,
    SAAS_REQUIRED_EVENTS,
    SAAS_WEBHOOK_PATH,
    operations_webhook_contract,
)
from app.main import app
from app.modules.marketing.starter_reversal import REVERSALS
import operations_payment_intake as intake


def test_contract_lists_package_events_without_secrets(monkeypatch):
    secret = "whsec_operations_contract_probe"
    monkeypatch.setenv("STRIPE_NOVA_AGENT_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("STRIPE_NOVA_BILLING_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("NOVA_OPERATIONS_LIVE_WEBHOOK_SECRET", secret)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    report = operations_webhook_contract()
    dumped = json.dumps(report)
    assert secret not in dumped
    assert report["marketing"]["path"] == MARKETING_WEBHOOK_PATH
    assert report["saas"]["path"] == SAAS_WEBHOOK_PATH
    assert report["marketing"]["secret_configured"] is True
    assert report["saas"]["secret_configured"] is True
    assert report["payment_intake_not_fulfillment"]["secret_configured"] is True
    assert report["payment_intake_not_fulfillment"]["fulfills_package"] is False
    assert report["marketing"]["fulfills_package"] is False
    assert report["saas"]["fulfills_package"] is False
    assert set(REVERSALS) <= set(MARKETING_REQUIRED_EVENTS)
    assert "invoice.paid" in MARKETING_REQUIRED_EVENTS
    assert "checkout.session.completed" in SAAS_REQUIRED_EVENTS
    assert "customer.subscription.deleted" in SAAS_REQUIRED_EVENTS
    for path in EXCLUDED_WEBHOOK_PATHS:
        assert path not in {MARKETING_WEBHOOK_PATH, SAAS_WEBHOOK_PATH, PAYMENT_INTAKE_WEBHOOK_PATH}


def test_hosted_app_registers_the_three_operations_webhook_routes():
    paths = app.openapi()["paths"]
    for path in (MARKETING_WEBHOOK_PATH, SAAS_WEBHOOK_PATH, PAYMENT_INTAKE_WEBHOOK_PATH):
        assert "post" in paths[path]
    assert paths[MARKETING_WEBHOOK_PATH] is not paths[PAYMENT_INTAKE_WEBHOOK_PATH]


def test_readiness_publishes_webhook_contract_without_secret_values(monkeypatch):
    secret = "whsec_readiness_contract_probe"
    monkeypatch.setenv("NOVA_OPERATIONS_LIVE_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("STRIPE_NOVA_AGENT_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("STRIPE_NOVA_BILLING_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false")
    report = intake.operations_production_readiness(probe_database=False)
    dumped = json.dumps(report)
    assert secret not in dumped
    assert report["live_sales_enabled"] is False
    assert report["stripe_webhooks"]["saas"]["packages"] == ["starter"]
    assert report["stripe_webhooks"]["marketing"]["packages"] == [
        "starter_49", "launch_99", "business_299",
    ]
    client = TestClient(app)
    response = client.get("/payments/operations/readiness")
    assert response.status_code == 200
    assert secret not in response.text
    assert response.json()["stripe_webhooks"]["payment_intake_not_fulfillment"]["records_ledger_only"] is True
