"""Simple driver application vehicle fields

Revision ID: 20260809_simple_driver_application
Revises: 20260809_approval_external_adapters
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260809_simple_driver_application"
down_revision = "20260809_approval_external_adapters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_driver_onboarding_applications",
        sa.Column("vehicle_year", sa.Integer(), nullable=True),
    )
    op.add_column(
        "platform_driver_onboarding_applications",
        sa.Column("vehicle_make", sa.String(64), nullable=True),
    )
    op.add_column(
        "platform_driver_onboarding_applications",
        sa.Column("vehicle_model", sa.String(64), nullable=True),
    )
    op.add_column(
        "platform_driver_onboarding_applications",
        sa.Column("vehicle_license_plate", sa.String(32), nullable=True),
    )
    op.add_column(
        "platform_driver_onboarding_applications",
        sa.Column("vehicle_vin", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    for col in (
        "vehicle_vin",
        "vehicle_license_plate",
        "vehicle_model",
        "vehicle_make",
        "vehicle_year",
    ):
        op.drop_column("platform_driver_onboarding_applications", col)
