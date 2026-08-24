"""Customer payment records for Amicor Ride and Amicor Deliver.

Existing HealthISFPaymentTransaction stays ride-only (ride_id NOT NULL).
These tables are the shared Ride + Deliver ledger and Stripe event store.
Driver earning / Amicor share / processing fee stay nullable — no invented percentages.
Payout is never started from this webhook.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String
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
    gross_customer_charge_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    driver_earning_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    amicor_share_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    processing_fee_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    refund_amount_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

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


def ensure_payments_schema() -> None:
    """Create customer-payment tables when migrations have not run (dev/test)."""
    from sqlalchemy import inspect

    from app.db.session import engine

    try:
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
            logger.info("payments schema ensured via create_all")
    except Exception as exc:
        logger.warning("payments schema ensure skipped: %s", exc)
