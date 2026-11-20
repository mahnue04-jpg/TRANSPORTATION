"""Offline guard tests for proposed staging-only durable checkout receipts.

These tests use no Stripe API, PostgreSQL connection, or real credentials.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from operations_checkout_durable_receipts import (
    _confirmed_values, require_staging_config, receipt_table, SCHEMA,
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
