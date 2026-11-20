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


# A durable order binding is required before a signed payment can be accepted.
# Never reconstruct a payable order from Stripe metadata alone.
order_table = Table(
    "starter_test_orders", _metadata,
    Column("lead_id", String(36), primary_key=True),
    Column("session_id", String(128), nullable=False),
    Column("customer_id", String(128), nullable=False),
    Column("plan", String(32), nullable=False),
    Column("amount_cents", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False),
    UniqueConstraint("session_id", name="uq_ops_sandbox_order_session"),
    CheckConstraint("plan = 'starter_49'", name="ck_ops_sandbox_order_plan"),
    CheckConstraint("amount_cents = 4900", name="ck_ops_sandbox_order_amount"),
    CheckConstraint("currency = 'usd'", name="ck_ops_sandbox_order_currency"),
    schema=SCHEMA,
)


def validated_checkout_event(event, order):
    """Validate a previously signature-verified Stripe event against a saved order.

    The caller MUST call verify_agent_webhook(raw_body, stripe_signature)
    first. Never use a browser redirect query or unsigned event object.
    """
    if not isinstance(event, dict) or not isinstance(order, dict):
        raise ValueError("Valid Stripe event and saved order required")
    obj = event.get("data", {}).get("object", {}) if isinstance(event.get("data"), dict) else {}
    metadata = obj.get("metadata") if isinstance(obj, dict) else None
    if not isinstance(obj, dict) or not isinstance(metadata, dict):
        raise ValueError("Malformed checkout event")
    if (
        event.get("type") not in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}
        or event.get("livemode") is not False
        or obj.get("livemode") is not False
        or obj.get("payment_status") != "paid"
        or obj.get("mode") != "payment"
        or obj.get("amount_total") != 4900
        or obj.get("currency") != "usd"
        or metadata.get("nova_product") != "nova_anonymous_operations_agent"
        or metadata.get("nova_agent_plan") != "starter_49"
        or metadata.get("nova_agent_lead_id") != order.get("lead_id")
        or obj.get("client_reference_id") != order.get("lead_id")
        or obj.get("id") != order.get("session_id")
        or obj.get("customer") != order.get("customer_id")
        or order.get("plan") != "starter_49"
        or order.get("amount_cents") != 4900
        or order.get("currency") != "usd"
    ):
        raise ValueError("Checkout event does not match the durable synthetic order")
    event_id = str(event.get("id") or "")
    if not event_id.startswith("evt_") or len(event_id) > 128:
        raise ValueError("Missing Stripe event identity")
    return dict(
        lead_id=order["lead_id"],
        session_id=order["session_id"],
        customer_id=order["customer_id"],
        event_id=event_id,
        amount_cents=4900,
        currency="usd",
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
    for expected in (TABLE_NAME, order_table.name):
        if not inspector.has_table(expected, schema=SCHEMA):
            raise RuntimeError("Durable checkout table missing: reviewed migration required")


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



def record_checkout_order(engine, *, lead_id, session_id, customer_id):
    """Register one synthetic order BEFORE issuing its checkout link.

    Does not contact Stripe or create a payment. Duplicate identical order
    is idempotent; conflicting identities are rejected without updates.
    """
    verify_store_ready(engine)
    values = dict(
        lead_id=str(lead_id), session_id=str(session_id),
        customer_id=str(customer_id), plan="starter_49",
        amount_cents=4900, currency="usd",
    )
    if (not values["lead_id"] or len(values["lead_id"]) > 36
        or not values["session_id"].startswith("cs_test_")
        or not values["customer_id"].startswith("cus_")):
        raise ValueError("Invalid synthetic order binding")
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    with engine.begin() as conn:
        conn.execute(pg_insert(order_table).values(**values).on_conflict_do_nothing())
        saved = conn.execute(select(order_table).where(
            order_table.c.lead_id == values["lead_id"]
        )).mappings().first()
        compared = ("lead_id", "session_id", "customer_id", "plan", "amount_cents", "currency")
        if saved is None or any(saved[k] != values[k] for k in compared):
            raise ValueError("Order binding conflict")
    return {"result": "registered", "lead_id": values["lead_id"]}


def process_verified_checkout_event(engine, event):
    """Record an authentic paid event only when a durable order already exists.

    Caller verifies the Stripe signature before passing the event here.
    """
    verify_store_ready(engine)
    data = event.get("data") if isinstance(event, dict) else None
    obj = data.get("object") if isinstance(data, dict) else None
    metadata = obj.get("metadata") if isinstance(obj, dict) else None
    lead_id = str(metadata.get("nova_agent_lead_id") or "") if isinstance(metadata, dict) else ""
    if not lead_id:
        raise ValueError("Event has no durable order reference")
    with engine.connect() as conn:
        order = conn.execute(select(order_table).where(
            order_table.c.lead_id == lead_id
        )).mappings().first()
    if order is None:
        raise ValueError("Signed event has no registered order")
    values = validated_checkout_event(event, dict(order))
    return record_confirmed_event(engine, **values)


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
    # Defense in depth: the order binding must exist and match, even if the
    # caller invokes this helper directly rather than the webhook adapter.
    with engine.begin() as conn:
        order = conn.execute(select(order_table).where(
            order_table.c.lead_id == values["lead_id"]
        )).mappings().first()
        if order is None or any((
            order["session_id"] != values["session_id"],
            order["customer_id"] != values["customer_id"],
            order["plan"] != "starter_49",
            order["amount_cents"] != 4900,
            order["currency"] != "usd",
        )):
            raise ValueError("No matching durable order binding")
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


def process_signed_test_webhook(engine, raw_body: bytes, stripe_signature: str | None):
    """Staging-only adapter connecting signature verification to durable receipt.

    Does not create an HTTP route or enable customer work. The caller must
    provision a restricted store and explicitly wire this after a staging
    migration, never in the running disposable SQLite sandbox.
    """
    require_staging_config()
    if not raw_body or not stripe_signature:
        raise ValueError("Signed Stripe webhook body and header required")
    from app.modules.marketing.operations_billing import verify_agent_webhook
    event = verify_agent_webhook(raw_body, stripe_signature)
    return process_verified_checkout_event(engine, event)


def _dedicated_staging_engine():
    """Construct only an explicitly named staging receipt database connection.

    Never use the app's general DATABASE_URL (which may be an existing
    shared or production database). No DDL or migrations happen here.
    """
    require_staging_config()
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    raw = os.getenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DATABASE_URL", "").strip()
    expected_name = os.getenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DB_NAME", "").strip()
    expected_user = os.getenv("NOVA_OPERATIONS_DURABLE_RECEIPT_DB_USER", "").strip()
    if not raw or not expected_name or not expected_user:
        raise RuntimeError("Dedicated staging receipt database settings required")
    url = make_url(raw)
    if (
        url.get_backend_name() != "postgresql"
        or url.database != expected_name
        or url.username != expected_user
        or not url.password
        or not url.host
        or expected_user.lower() in {"postgres", "amicor", "render", "root"}
    ):
        raise RuntimeError("Dedicated staging receipt connection identity mismatch")
    return create_engine(url, pool_pre_ping=True)


def register_staging_checkout_binding(*, lead_id, session_id, customer_id):
    """Optional route hook: register synthetic checkout BEFORE URL is returned."""
    engine = _dedicated_staging_engine()
    try:
        return record_checkout_order(
            engine, lead_id=lead_id, session_id=session_id,
            customer_id=customer_id,
        )
    finally:
        engine.dispose()


def record_staging_signed_webhook(*, raw_body, stripe_signature):
    """Optional webhook route hook: verify Stripe signature then store receipt."""
    engine = _dedicated_staging_engine()
    try:
        return process_signed_test_webhook(engine, raw_body, stripe_signature)
    finally:
        engine.dispose()


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
