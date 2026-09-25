"""AMICOR marketplace one-time purchase and entitlement tables."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


class MarketplacePurchase(Base):
    __tablename__ = "nova_marketplace_purchases"
    __table_args__ = (
        Index("ix_marketplace_purchase_id", "id", unique=True),
        Index("ix_marketplace_purchase_session", "stripe_checkout_session_id", unique=True),
        Index("ix_marketplace_purchase_email", "email"),
        Index("ix_marketplace_purchase_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    product_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="usd")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class MarketplaceEntitlement(Base):
    __tablename__ = "nova_marketplace_entitlements"
    __table_args__ = (
        Index("ix_marketplace_entitlement_token_hash", "token_hash", unique=True),
        Index("ix_marketplace_entitlement_purchase", "purchase_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    purchase_id: Mapped[str] = mapped_column(String(36), nullable=False)
    product_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MarketplaceWebhookEvent(Base):
    __tablename__ = "nova_marketplace_webhook_events"
    __table_args__ = (
        Index("ix_marketplace_webhook_event_id", "stripe_event_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    stripe_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False)
    purchase_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    processing_result: Mapped[str] = mapped_column(String(48), nullable=False, default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
