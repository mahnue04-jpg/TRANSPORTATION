"""Nova SaaS signup and customer-tenant tables. Isolated from Health/Freight billing."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4

STATUS_FREE = "free"
STATUS_PENDING = "pending"
STATUS_CHECKOUT_OPEN = "checkout_open"
STATUS_TRIALING = "trialing"
STATUS_ACTIVE = "active"
STATUS_PAST_DUE = "past_due"
STATUS_CANCELED = "canceled"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"

HOLD_FOUNDING_STATUSES = (
    STATUS_CHECKOUT_OPEN,
    STATUS_TRIALING,
    STATUS_ACTIVE,
    STATUS_PAST_DUE,
    STATUS_CANCELED,
)
ACTIVATED_STATUSES = (STATUS_FREE, STATUS_TRIALING, STATUS_ACTIVE, STATUS_PAST_DUE)


class NovaSignupAccount(Base):
    __tablename__ = "nova_signup_accounts"
    __table_args__ = (
        Index("ix_nova_signup_accounts_email", "email", unique=True),
        Index("ix_nova_signup_accounts_status", "status"),
        Index("ix_nova_signup_accounts_founding_slot", "founding_slot"),
        Index("ix_nova_signup_accounts_org_id", "organization_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    business_name: Mapped[str] = mapped_column(String(128), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    industry: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    terms_accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=STATUS_PENDING)
    founding_reserved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    founding_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_schedule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    intro_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    intro_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_month_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_unit_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class NovaCustomerTenant(Base):
    __tablename__ = "nova_customer_tenants"
    __table_args__ = (
        Index("ix_nova_customer_tenants_org_id", "organization_id", unique=True),
        Index("ix_nova_customer_tenants_signup_id", "signup_id", unique=True),
        Index("ix_nova_customer_tenants_owner_user_id", "owner_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    signup_id: Mapped[str] = mapped_column(String(36), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    founding_member: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    founding_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscription_status: Mapped[str] = mapped_column(String(32), nullable=False, default=STATUS_TRIALING)
    product_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="nova")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class NovaSignupWebhookEvent(Base):
    __tablename__ = "nova_signup_webhook_events"
    __table_args__ = (Index("ix_nova_signup_webhook_events_event_id", "stripe_event_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    stripe_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    signup_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    processing_result: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class NovaFreeUsage(Base):
    __tablename__ = "nova_free_usage"
    __table_args__ = (
        Index("ix_nova_free_usage_org_date", "organization_id", "usage_date", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    ask_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
