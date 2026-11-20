"""Ephemeral PostgreSQL integration for durable synthetic $49 orders.

Runs only in GitHub Actions against disposable PostgreSQL; no Render connections,
no real Stripe calls, no customer data, and no app deployment.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from operations_checkout_durable_receipts import (
    SCHEMA, _metadata, find_receipt, process_verified_checkout_event,
    record_checkout_order, validated_checkout_event,
)

CI_DB = "NOVA_OPS_RECEIPTS_CI_DATABASE_URL"


def _paid_event(lead="ci-order-1", session="cs_test_ci_session_1",
                customer="cus_ci_customer_1", event_id="evt_ci_paid_1"):
    return {
        "id": event_id, "livemode": False,
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": session, "livemode": False, "client_reference_id": lead,
            "customer": customer, "mode": "payment", "currency": "usd",
            "amount_total": 4900, "payment_status": "paid",
            "metadata": {
                "nova_product": "nova_anonymous_operations_agent",
                "nova_agent_plan": "starter_49",
                "nova_agent_lead_id": lead,
            },
        }},
    }


@pytest.fixture()
def staging_ledger(monkeypatch):
    url = os.environ.get(CI_DB, "")
    if not url or "127.0.0.1" not in url or "nova_ops_receipts_ci" not in url:
        pytest.skip("Dedicated disposable local PostgreSQL CI database required")
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_RECEIPT_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DB_NAME", "nova_ops_receipts_ci")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "rk_test_ephemeral_ci")
    for name in (
        "NOVA_STRIPE_LIVE_ENABLED", "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED", "NOVA_OPERATIONS_OWNER_CSV_ENABLED",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED", "NOVA_OPERATIONS_LEASE_WORKER_ENABLED",
        "NOVA_OPERATIONS_STARTER_BINDING_ENABLED", "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED",
        "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED",
    ):
        monkeypatch.setenv(name, "false")
    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    # Explicit DDL is confined to this disposable database within the test fixture.
    _metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        _metadata.drop_all(bind=engine)
        with engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA}"))
        engine.dispose()


def test_signed_paid_event_persists_across_connections(staging_ledger):
    engine = staging_ledger
    record_checkout_order(engine, lead_id="ci-order-1", session_id="cs_test_ci_session_1",
                          customer_id="cus_ci_customer_1")
    event = _paid_event()
    assert process_verified_checkout_event(engine, event)["result"] == "paid"
    assert process_verified_checkout_event(engine, event)["result"] == "already_paid"

    # Re-create a completely separate engine to simulate app process restart.
    # SQLAlchemy renders passwords as *** by default; retain the original
    # disposable CI URL instead of serializing an engine URL.
    url = os.environ[CI_DB]
    engine.dispose()
    restarted = create_engine(url, pool_pre_ping=True)
    try:
        row = find_receipt(restarted, lead_id="ci-order-1")
        assert row is not None
        assert row["payment_status"] == "paid"
        assert row["amount_cents"] == 4900
        assert row["session_id"] == "cs_test_ci_session_1"
        assert row["stripe_event_id"] == "evt_ci_paid_1"
    finally:
        restarted.dispose()


def test_receipt_rejects_unregistered_and_mismatched_payments(staging_ledger):
    engine = staging_ledger
    with pytest.raises(ValueError, match="no registered order"):
        process_verified_checkout_event(engine, _paid_event())
    record_checkout_order(engine, lead_id="ci-order-1", session_id="cs_test_ci_session_1",
                          customer_id="cus_ci_customer_1")
    wrong = _paid_event(session="cs_test_other")
    with pytest.raises(ValueError, match="does not match"):
        process_verified_checkout_event(engine, wrong)
    assert find_receipt(engine, lead_id="ci-order-1") is None


def test_receipt_rejects_conflicting_order_binding(staging_ledger):
    engine = staging_ledger
    original = dict(lead_id="ci-order-1", session_id="cs_test_ci_session_1",
                    customer_id="cus_ci_customer_1")
    assert record_checkout_order(engine, **original)["result"] == "registered"
    assert record_checkout_order(engine, **original)["result"] == "registered"
    with pytest.raises(ValueError, match="conflict"):
        record_checkout_order(engine, **{**original, "customer_id": "cus_other"})
