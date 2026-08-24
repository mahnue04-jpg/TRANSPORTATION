"""Stripe Connect hosted onboarding status fields

Revision ID: 20260818_stripe_connect_onboarding
Revises: 20260809_simple_driver_application
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_stripe_connect_onboarding"
down_revision = "20260809_simple_driver_application"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_driver_onboarding_applications",
        sa.Column("stripe_account_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "platform_driver_onboarding_applications",
        sa.Column("stripe_payouts_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "platform_driver_onboarding_applications",
        sa.Column("stripe_details_submitted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "platform_driver_onboarding_applications",
        sa.Column("stripe_onboarding_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "platform_driver_onboarding_applications",
        sa.Column("stripe_connect_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_platform_driver_onboarding_stripe_account_id",
        "platform_driver_onboarding_applications",
        ["stripe_account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_platform_driver_onboarding_stripe_account_id",
        table_name="platform_driver_onboarding_applications",
    )
    for col in (
        "stripe_connect_updated_at",
        "stripe_onboarding_status",
        "stripe_details_submitted",
        "stripe_payouts_enabled",
        "stripe_account_id",
    ):
        op.drop_column("platform_driver_onboarding_applications", col)
