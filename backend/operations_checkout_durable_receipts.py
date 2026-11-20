"""Isolated staging-only receipt ledger for Operations Starter purchases.

This module is PREPARATION ONLY and is not wired to the running sandbox.
DDL is in operations_checkout_receipts_staging.sql and MUST be applied only
after a reviewed backup and isolated staging database permissions.
No automatic schema creation, no production connections, no fulfillment.
"""
from __future__ import annotations

import os
from sqlalchemy import (
    CheckConstraint, Column, DateTime, Integer, MetaData, String, Table,
    UniqueConstraint, inspect, select, text
)
from sqlalchemy.exc import IntegrityError

SCHEMA = "nova_ops_checkout_sandbox"
TABLE_NAME = "starter_test_receipts"
_metadata = MetaData()
receipt_table = Table(
    TABLE_NAME, _metadata,
    Column("lead_id", String(36), primary_key=True),
    Column("session_id", String(128), nullable=False),
    Column("customer_id", String(128), nullable=False),
    Column("stripe_event_id", String(128), nullable=False),
    Column("amount_cents", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("payment_status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False),
    UniqueConstraint("session_id", name="uq_ops_sandbox_receipt_session"),
    UniqueConstraint("stripe_event_id", name="uq_ops_sandbox_receipt_event"),
    CheckConstraint("amount_cents = 4900", name="ck_ops_sandbox_amount"),
    CheckConstraint("currency = 'usd'", name="ck_ops_sandbox_currency"),
    CheckConstraint("payment_status = 'paid'", name="ck_ops_sandbox_paid"),
    schema=SCHEMA,
)


def require_staging_config() -> None:
    """Fail closed before *any* connection to a persistent database."""
    if os.environ.get("NOVA_OPERATIONS_DURABLE_RECEIPT_ENABLED") != "true":
        raise RuntimeError("Durable receipt ledger not explicitly enabled")
    if os.environ.get("APP_ENV") != "staging" or os.environ.get("AMICOR_ENVIRONMENT") != "staging":
        raise RuntimeError("Staging environment required")
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key.startswith(("rk_test_", "sk_test_")):
        raise RuntimeError("Stripe test key required")
    prohibited = (
        "NOVA_STRIPE_LIVE_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED",
        "NOVA_OPERATIONS_OWNER_CSV_ENABLED",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
        "NOVA_OPERATIONS_LEASE_WORKER_ENABLED",
        "NOVA_OPERATIONS_STARTER_BINDING_ENABLED",
        "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED",
        "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED",
    )
    if any(os.getenv(name, "").lower() == "true" for name in prohibited):
        raise RuntimeError("Live or customer work must remain disabled")


def verify_store_ready(engine) -> None:
    """Require exact preprovisioned namespace; never migrate or create tables."""
    require_staging_config()
    if engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL required for durable staging receipts")
    database = str(engine.url.database or "")
    required_db = os.getenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DB_NAME", "")
    if not required_db or database != required_db:
        raise RuntimeError("Dedicated staging database name mismatch")
    inspector = inspect(engine)
    if not inspector.has_table(TABLE_NAME, schema=SCHEMA):
        raise RuntimeError("Receipt table missing: reviewed migration required")


def _confirmed_values(*, lead_id, session_id, customer_id, event_id, amount_cents, currency):
    """Accept only exact synthetically paid one-time checkout identifiers."""
    values = dict(lead_id=str(lead_id), session_id=str(session_id),
                  customer_id=str(customer_id), stripe_event_id=str(event_id),
                  amount_cents=amount_cents, currency=currency, payment_status="paid")
    if (not values["lead_id"] or len(values["lead_id"]) > 36
        or not values["session_id"].startswith("cs_test_")
        or not values["customer_id"].startswith("cus_")
        or not values["stripe_event_id"].startswith("evt_")
        or values["amount_cents"] != 4900 or values["currency"] != "usd"):
        raise ValueError("Invalid synthetic paid checkout receipt")
    return values


def record_confirmed_event(engine, *, lead_id, session_id, customer_id,
                           event_id, amount_cents, currency):
    """Record ONLY an event already verified via Stripe's signed webhook.

    Never call with browser return parameters. A repeated identical event is
    idempotent; a conflicting session or lead fails closed. Caller authenticates
    the Stripe signature and checks order identity BEFORE this function.
    """
    verify_store_ready(engine)
    values = _confirmed_values(
        lead_id=lead_id, session_id=session_id, customer_id=customer_id,
        event_id=event_id, amount_cents=amount_cents, currency=currency,
    )
    # This operates only on the pre-existing restricted staging schema.
    with engine.begin() as conn:
        existing = conn.execute(
            select(receipt_table).where(receipt_table.c.lead_id == values["lead_id"])
        ).mappings().first()
        if existing:
            compared = ("lead_id", "session_id", "customer_id", "amount_cents", "currency", "payment_status")
            if any(existing[k] != values[k] for k in compared):
                raise ValueError("Conflicting paid receipt for existing lead")
            return {"result": "already_paid", "lead_id": values["lead_id"]}
        try:
            # PostgreSQL ON CONFLICT is intentional: never overwrite another receipt.
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(receipt_table).values(**values).on_conflict_do_nothing()
            outcome = conn.execute(stmt)
            if outcome.rowcount != 1:
                raise ValueError("Stripe event or session belongs to another receipt")
        except IntegrityError as exc:
            raise ValueError("Receipt identity conflict") from exc
    return {"result": "paid", "lead_id": values["lead_id"]}


def find_receipt(engine, *, lead_id):
    verify_store_ready(engine)
    with engine.connect() as conn:
        row = conn.execute(select(receipt_table).where(
            receipt_table.c.lead_id == lead_id
        )).mappings().first()
        if row is None:
            return None
        return {k: row[k] for k in (
            "lead_id", "session_id", "customer_id", "stripe_event_id",
            "amount_cents", "currency", "payment_status",
        )}
