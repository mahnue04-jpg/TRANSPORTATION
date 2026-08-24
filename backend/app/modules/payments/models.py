"""Customer payment records for Amicor Ride and Amicor Deliver.

Existing HealthISFPaymentTransaction stays ride-only (ride_id NOT NULL).
These tables are the shared Ride + Deliver ledger and Stripe event store.
Driver earning / Amicor share / processing fee stay nullable — no invented percentages.
Payout is never started from this webhook.

Money is stored as integer minor units. Float is not authoritative.
Production schema is applied only by Alembic — never by create_all.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4

logger = logging.getLogger("amicor.payments.models")

SERVICE_RIDE = "RIDE"
SERVICE_DELIVERY = "DELIVERY"
SUPPORTED_SERVICE_TYPES = frozenset({SERVICE_RIDE, SERVICE_DELIVERY})

PAYMENT_PENDING = "pending"
PAYMENT_SUCCEEDED = "succeeded"
PAYMENT_FAILED = "failed"

PAYOUT_NOT_STARTED = "not_started"

PAYMENT_TABLE_NAMES = frozenset({
    "amicor_customer_payments",
    "amicor_customer_payment_events",
})


def payments_autocreate_allowed() -> bool:
    """True only for explicit local/test helpers. Always false on Render/production."""
    if os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes"}:
        return False
    runtime = os.getenv("RUNTIME_ENVIRONMENT", "").strip().lower()
    if runtime in {"production", "prod", "staging"}:
        return False
    if os.getenv("TESTING", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if os.getenv("AMICOR_PAYMENTS_ALLOW_CREATE_ALL", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return False


class AmicorCustomerPayment(Base):
    """One customer PaymentIntent for a ride or delivery. Not a driver payout."""

    __tablename__ = "amicor_customer_payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    service_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    internal_service_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ride_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    delivery_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    driver_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    organization_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    pricing_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    stripe_payment_intent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    last_stripe_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="usd")
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    driver_earning_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amicor_share_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processing_fee_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refund_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    payment_status: Mapped[str] = mapped_column(String(32), nullable=False, default=PAYMENT_PENDING, index=True)
    payout_status: Mapped[str] = mapped_column(String(32), nullable=False, default=PAYOUT_NOT_STARTED, index=True)

    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    health_isf_payment_transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        Index("uq_amicor_customer_payments_pi", "stripe_payment_intent_id", unique=True),
        Index("ix_amicor_customer_payments_service_internal", "service_type", "internal_service_id"),
        Index("ix_amicor_customer_payments_status", "payment_status"),
    )


class AmicorCustomerPaymentEvent(Base):
    """Stripe event ledger for webhook idempotency and audit."""

    __tablename__ = "amicor_customer_payment_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    stripe_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    service_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    internal_service_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    processing_result: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    __table_args__ = (
        Index("uq_amicor_customer_payment_events_event", "stripe_event_id", unique=True),
    )


def payment_schema_tables():
    """SQLAlchemy Table objects for the customer-payment ledger."""
    return (AmicorCustomerPayment.__table__, AmicorCustomerPaymentEvent.__table__)


def tables_excluding_payments(metadata=None):
    """All registered tables except the payment ledger (Alembic-owned in production)."""
    metadata = metadata or Base.metadata
    blocked = set(payment_schema_tables())
    return [table for table in metadata.sorted_tables if table not in blocked]


def _install_create_all_guard() -> None:
    """Prevent generic Base.metadata.create_all from creating payment tables in production.

    Health ISF, platform init, and deferred startup still create their own tables.
    Payment tables are created only by Alembic or ensure_payments_test_schema().
    """
    metadata = Base.metadata
    if getattr(metadata, "_amicor_payments_create_all_guarded", False):
        return
    original = metadata.create_all

    def create_all(bind=None, tables=None, checkfirst=True, **kwargs):
        if payments_autocreate_allowed():
            return original(bind=bind, tables=tables, checkfirst=checkfirst, **kwargs)
        blocked = set(payment_schema_tables())
        if tables is None:
            filtered = [table for table in metadata.sorted_tables if table not in blocked]
        else:
            filtered = [table for table in tables if table not in blocked]
        return original(bind=bind, tables=filtered, checkfirst=checkfirst, **kwargs)

    metadata.create_all = create_all  # type: ignore[method-assign]
    metadata._amicor_payments_create_all_guarded = True


_install_create_all_guard()


def ensure_payments_test_schema() -> None:
    """Create payment tables for local/test fixtures only.

    Production and Render must use Alembic. This helper is a no-op unless
    TESTING or AMICOR_PAYMENTS_ALLOW_CREATE_ALL is set, and is refused on Render.
    """
    if not payments_autocreate_allowed():
        logger.info("payments create_all refused; Alembic is the production schema mechanism")
        return
    from sqlalchemy import inspect

    from app.db.session import engine

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    needed = {
        AmicorCustomerPayment.__tablename__,
        AmicorCustomerPaymentEvent.__tablename__,
    }
    if not needed.issubset(existing):
        Base.metadata.create_all(
            bind=engine,
            tables=[AmicorCustomerPayment.__table__, AmicorCustomerPaymentEvent.__table__],
        )
        logger.info("payments test schema ensured via create_all")
