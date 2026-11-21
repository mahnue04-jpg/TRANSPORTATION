"""Offline guard tests for proposed staging-only durable checkout receipts.

These tests use no Stripe API, PostgreSQL connection, or real credentials.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from operations_checkout_durable_receipts import (
    _confirmed_values, require_staging_config, receipt_table, order_table, validated_checkout_event, SCHEMA,
)

BACKEND = Path(__file__).resolve().parents[1]


def _safe_env(monkeypatch):
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_RECEIPT_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "rk_test_offline_synthetic")
    for flag in (
        "NOVA_STRIPE_LIVE_ENABLED", "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED",
        "NOVA_OPERATIONS_OWNER_CSV_ENABLED", "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
        "NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "NOVA_OPERATIONS_STARTER_BINDING_ENABLED",
        "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED", "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED",
    ):
        monkeypatch.setenv(flag, "false")


def test_staging_requires_all_safety_gates(monkeypatch):
    _safe_env(monkeypatch)
    require_staging_config()
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")
    with pytest.raises(RuntimeError, match="disabled"):
        require_staging_config()


def test_receipt_never_allows_live_key(monkeypatch):
    _safe_env(monkeypatch)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "rk_live_offline_example")
    with pytest.raises(RuntimeError, match="test key"):
        require_staging_config()


def test_receipt_requires_explicit_opt_in(monkeypatch):
    _safe_env(monkeypatch)
    monkeypatch.delenv("NOVA_OPERATIONS_DURABLE_RECEIPT_ENABLED")
    with pytest.raises(RuntimeError, match="explicitly enabled"):
        require_staging_config()


def test_receipt_accepts_only_49_dollar_test_checkout():
    values=dict(lead_id="synthetic-lead",session_id="cs_test_synthetic",
                customer_id="cus_synthetic",event_id="evt_synthetic",
                amount_cents=4900,currency="usd")
    assert _confirmed_values(**values)["payment_status"] == "paid"
    for name, bad in (("amount_cents", 0), ("amount_cents", 9900),
                      ("currency", "eur"), ("session_id", "cs_live_abc"),
                      ("event_id", "bad"), ("customer_id", "bad")):
        modified=dict(values,**{name:bad})
        with pytest.raises(ValueError, match="Invalid"):
            _confirmed_values(**modified)


def test_ledger_is_isolated_and_never_auto_creates_schema():
    assert receipt_table.schema == SCHEMA == "nova_ops_checkout_sandbox"
    sql=(BACKEND / "operations_checkout_receipts_staging.sql").read_text()
    assert "BEGIN;" in sql
    assert "CREATE TABLE IF NOT EXISTS nova_ops_checkout_sandbox.starter_test_receipts" in sql
    source=(BACKEND / "operations_checkout_durable_receipts.py").read_text()
    assert "create_all(" not in source
    assert "DROP TABLE" not in sql

def test_staging_checkout_route_requires_durable_order_before_url():
    routes = (BACKEND / "app/modules/marketing/routes.py").read_text()
    new = routes.index('register_staging_checkout_binding(', routes.index('def create_nova_agent_checkout('))
    assert new < routes.index('    lead.stripe_customer_id = customer_id')
    assert 'NOVA_OPERATIONS_DURABLE_RECEIPT_ENABLED' in routes
    assert 'raise HTTPException(status_code=503, detail="Secure staging checkout unavailable")' in routes

def test_signed_webhook_must_persist_receipt_before_ack():
    routes = (BACKEND / "app/modules/marketing/routes.py").read_text()
    section = routes[routes.index('async def nova_agent_stripe_webhook('):]
    assert section.index('record_staging_signed_webhook(') < section.index('    db.commit()')
    assert "Durable test receipt unavailable" in section

def test_receipt_engine_never_uses_general_database_url(monkeypatch):
    from operations_checkout_durable_receipts import _dedicated_staging_engine
    _safe_env(monkeypatch)
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DB_NAME", "synthetic")
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DB_USER", "staging_receipt_user")
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod.example.invalid/prod")
    with pytest.raises(RuntimeError, match="Dedicated staging receipt database settings required"):
        _dedicated_staging_engine()



def _signed_event_fixture():
    """Already authenticated by the webhook caller in the real integration."""
    lead = "synthetic-lead"
    order = {
        "lead_id": lead,
        "session_id": "cs_test_synthetic",
        "customer_id": "cus_synthetic",
        "plan": "starter_49", "amount_cents": 4900, "currency": "usd",
    }
    event = {
        "id": "evt_synthetic", "type": "checkout.session.completed",
        "livemode": False,
        "data": {"object": {
            "id": "cs_test_synthetic", "livemode": False,
            "client_reference_id": lead, "customer": "cus_synthetic",
            "mode": "payment", "currency": "usd",
            "amount_total": 4900, "payment_status": "paid",
            "metadata": {
                "nova_product": "nova_anonymous_operations_agent",
                "nova_agent_plan": "starter_49",
                "nova_agent_lead_id": lead,
            },
        }},
    }
    return event, order


def test_verified_event_requires_exact_saved_order():
    event, order = _signed_event_fixture()
    assert validated_checkout_event(event, order)["event_id"] == "evt_synthetic"
    for key, wrong in (
        ("session_id", "cs_test_other"), ("customer_id", "cus_other"),
        ("lead_id", "other"), ("plan", "launch_99"), ("amount_cents", 0),
    ):
        altered = dict(order, **{key: wrong})
        with pytest.raises(ValueError, match="does not match"):
            validated_checkout_event(event, altered)


def test_verified_event_rejects_wrong_stripe_payment():
    event, order = _signed_event_fixture()
    for field, wrong in (
        ("payment_status", "unpaid"), ("amount_total", 0),
        ("currency", "eur"), ("livemode", True),
    ):
        altered = dict(event)
        altered["data"] = {"object": dict(event["data"]["object"])}
        altered["data"]["object"][field] = wrong
        with pytest.raises(ValueError, match="does not match"):
            validated_checkout_event(altered, order)
    altered = dict(event, type="checkout.session.expired")
    with pytest.raises(ValueError, match="does not match"):
        validated_checkout_event(altered, order)


def test_order_and_receipt_are_separate_isolated_tables():
    assert order_table.schema == receipt_table.schema == SCHEMA
    assert order_table.name == "starter_test_orders"
    sql = (BACKEND / "operations_checkout_receipts_staging.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS nova_ops_checkout_sandbox.starter_test_orders" in sql


def test_receipt_engine_requires_exact_host_and_refuses_default_render_roles(monkeypatch):
    """Never accept a similarly named DB on another host or a Render owner role."""
    from operations_checkout_durable_receipts import _dedicated_staging_engine

    _safe_env(monkeypatch)
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DB_NAME", "nova_operations_staging_db_541")
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DB_USER", "ops_receipt_writer")
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DB_HOST", "approved.staging.internal")
    monkeypatch.setenv(
        "NOVA_OPERATIONS_DURABLE_RECEIPT_DATABASE_URL",
        "postgresql://ops_receipt_writer:synthetic@unapproved.internal/nova_operations_staging_db_541",
    )
    with pytest.raises(RuntimeError, match="identity mismatch"):
        _dedicated_staging_engine()

    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DB_HOST", "unapproved.internal")
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DB_USER", "nova_operations_staging_rotated")
    monkeypatch.setenv(
        "NOVA_OPERATIONS_DURABLE_RECEIPT_DATABASE_URL",
        "postgresql://nova_operations_staging_rotated:synthetic@unapproved.internal/nova_operations_staging_db_541",
    )
    with pytest.raises(RuntimeError, match="identity mismatch"):
        _dedicated_staging_engine()

    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DB_USER", "nova_operations_staging_db_541_user")
    monkeypatch.setenv(
        "NOVA_OPERATIONS_DURABLE_RECEIPT_DATABASE_URL",
        "postgresql://nova_operations_staging_db_541_user:synthetic@unapproved.internal/nova_operations_staging_db_541",
    )
    with pytest.raises(RuntimeError, match="identity mismatch"):
        _dedicated_staging_engine()
