"""Nova tenant subscription records. No card numbers, secrets, or Connect payout fields."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


class NovaTenantSubscription(Base):
    __tablename__ = "nova_tenant_subscriptions"
    __table_args__ = (
        Index("ix_nova_tenant_subscriptions_tenant_id", "tenant_id", unique=True),
        Index("ix_nova_tenant_subscriptions_customer", "stripe_customer_id", unique=True),
        Index("ix_nova_tenant_subscriptions_sub", "stripe_subscription_id"),
        Index("ix_nova_tenant_subscriptions_status", "subscription_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_price_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subscription_status: Mapped[str] = mapped_column(String(32), nullable=False, default="incomplete")
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class NovaBillingWebhookEvent(Base):
    __tablename__ = "nova_billing_webhook_events"
    __table_args__ = (Index("ix_nova_billing_webhook_events_event_id", "stripe_event_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    stripe_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    processing_result: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
