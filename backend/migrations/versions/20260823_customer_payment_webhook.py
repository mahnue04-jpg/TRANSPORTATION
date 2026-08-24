"""Shared Ride + Deliver customer payment webhook ledger.

Revision ID: 20260823_customer_payment_webhook
Revises: 20260818_stripe_connect_onboarding

Additive only. Does not alter Connect onboarding or Health ISF ride payment tables.
Does not run automatically — apply when operators choose to migrate.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260823_customer_payment_webhook"
down_revision = "20260818_stripe_connect_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "amicor_customer_payments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("service_type", sa.String(length=16), nullable=False),
        sa.Column("internal_service_id", sa.String(length=64), nullable=False),
        sa.Column("ride_id", sa.String(length=36), nullable=True),
        sa.Column("delivery_id", sa.String(length=36), nullable=True),
        sa.Column("customer_id", sa.String(length=64), nullable=True),
        sa.Column("driver_id", sa.String(length=64), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("pricing_version", sa.String(length=64), nullable=True),
        sa.Column("stripe_payment_intent_id", sa.String(length=128), nullable=False),
        sa.Column("last_stripe_event_id", sa.String(length=128), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("driver_earning_minor", sa.Integer(), nullable=True),
        sa.Column("amicor_share_minor", sa.Integer(), nullable=True),
        sa.Column("processing_fee_minor", sa.Integer(), nullable=True),
        sa.Column("refund_amount_minor", sa.Integer(), nullable=False),
        sa.Column("payment_status", sa.String(length=32), nullable=False),
        sa.Column("payout_status", sa.String(length=32), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.String(length=512), nullable=True),
        sa.Column("health_isf_payment_transaction_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_amicor_customer_payments_service_type", "amicor_customer_payments", ["service_type"])
    op.create_index(
        "ix_amicor_customer_payments_internal_service_id",
        "amicor_customer_payments",
        ["internal_service_id"],
    )
    op.create_index("ix_amicor_customer_payments_ride_id", "amicor_customer_payments", ["ride_id"])
    op.create_index("ix_amicor_customer_payments_delivery_id", "amicor_customer_payments", ["delivery_id"])
    op.create_index("ix_amicor_customer_payments_customer_id", "amicor_customer_payments", ["customer_id"])
    op.create_index("ix_amicor_customer_payments_driver_id", "amicor_customer_payments", ["driver_id"])
    op.create_index(
        "ix_amicor_customer_payments_organization_id",
        "amicor_customer_payments",
        ["organization_id"],
    )
    op.create_index("ix_amicor_customer_payments_payment_status", "amicor_customer_payments", ["payment_status"])
    op.create_index("ix_amicor_customer_payments_payout_status", "amicor_customer_payments", ["payout_status"])
    op.create_index("ix_amicor_customer_payments_created_at", "amicor_customer_payments", ["created_at"])
    op.create_index("ix_amicor_customer_payments_paid_at", "amicor_customer_payments", ["paid_at"])
    op.create_index(
        "uq_amicor_customer_payments_pi",
        "amicor_customer_payments",
        ["stripe_payment_intent_id"],
        unique=True,
    )
    op.create_index(
        "ix_amicor_customer_payments_service_internal",
        "amicor_customer_payments",
        ["service_type", "internal_service_id"],
    )
    op.create_index("ix_amicor_customer_payments_status", "amicor_customer_payments", ["payment_status"])

    op.create_table(
        "amicor_customer_payment_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("stripe_event_id", sa.String(length=128), nullable=False),
        sa.Column("stripe_payment_intent_id", sa.String(length=128), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("service_type", sa.String(length=16), nullable=True),
        sa.Column("internal_service_id", sa.String(length=64), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("processing_result", sa.String(length=64), nullable=False),
        sa.Column("payment_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_amicor_customer_payment_events_pi",
        "amicor_customer_payment_events",
        ["stripe_payment_intent_id"],
    )
    op.create_index(
        "ix_amicor_customer_payment_events_event_type",
        "amicor_customer_payment_events",
        ["event_type"],
    )
    op.create_index(
        "ix_amicor_customer_payment_events_result",
        "amicor_customer_payment_events",
        ["processing_result"],
    )
    op.create_index(
        "ix_amicor_customer_payment_events_payment_id",
        "amicor_customer_payment_events",
        ["payment_id"],
    )
    op.create_index(
        "ix_amicor_customer_payment_events_created_at",
        "amicor_customer_payment_events",
        ["created_at"],
    )
    op.create_index(
        "uq_amicor_customer_payment_events_event",
        "amicor_customer_payment_events",
        ["stripe_event_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_amicor_customer_payment_events_event", table_name="amicor_customer_payment_events")
    op.drop_index("ix_amicor_customer_payment_events_created_at", table_name="amicor_customer_payment_events")
    op.drop_index("ix_amicor_customer_payment_events_payment_id", table_name="amicor_customer_payment_events")
    op.drop_index("ix_amicor_customer_payment_events_result", table_name="amicor_customer_payment_events")
    op.drop_index("ix_amicor_customer_payment_events_event_type", table_name="amicor_customer_payment_events")
    op.drop_index("ix_amicor_customer_payment_events_pi", table_name="amicor_customer_payment_events")
    op.drop_table("amicor_customer_payment_events")

    op.drop_index("ix_amicor_customer_payments_status", table_name="amicor_customer_payments")
    op.drop_index("ix_amicor_customer_payments_service_internal", table_name="amicor_customer_payments")
    op.drop_index("uq_amicor_customer_payments_pi", table_name="amicor_customer_payments")
    op.drop_index("ix_amicor_customer_payments_paid_at", table_name="amicor_customer_payments")
    op.drop_index("ix_amicor_customer_payments_created_at", table_name="amicor_customer_payments")
    op.drop_index("ix_amicor_customer_payments_payout_status", table_name="amicor_customer_payments")
    op.drop_index("ix_amicor_customer_payments_payment_status", table_name="amicor_customer_payments")
    op.drop_index("ix_amicor_customer_payments_organization_id", table_name="amicor_customer_payments")
    op.drop_index("ix_amicor_customer_payments_driver_id", table_name="amicor_customer_payments")
    op.drop_index("ix_amicor_customer_payments_customer_id", table_name="amicor_customer_payments")
    op.drop_index("ix_amicor_customer_payments_delivery_id", table_name="amicor_customer_payments")
    op.drop_index("ix_amicor_customer_payments_ride_id", table_name="amicor_customer_payments")
    op.drop_index("ix_amicor_customer_payments_internal_service_id", table_name="amicor_customer_payments")
    op.drop_index("ix_amicor_customer_payments_service_type", table_name="amicor_customer_payments")
    op.drop_table("amicor_customer_payments")
