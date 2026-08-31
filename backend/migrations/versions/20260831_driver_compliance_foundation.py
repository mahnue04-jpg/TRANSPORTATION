"""Driver 001 compliance foundation columns.

Revision ID: 20260831_driver_compliance
Revises: 20260823_customer_payment_webhook
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260831_driver_compliance"
down_revision = "20260823_customer_payment_webhook"
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns(table)}
    if column.name not in existing:
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_missing(
        "platform_driver_onboarding_applications",
        sa.Column("internal_driver_number", sa.String(32), nullable=True),
    )
    _add_column_if_missing(
        "platform_driver_onboarding_applications",
        sa.Column("background_consent_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "platform_driver_onboarding_applications",
        sa.Column("vehicle_color", sa.String(32), nullable=True),
    )
    _add_column_if_missing(
        "platform_driver_onboarding_applications",
        sa.Column("vehicle_plate_state", sa.String(32), nullable=True),
    )
    _add_column_if_missing(
        "platform_driver_onboarding_applications",
        sa.Column("vehicle_registration_expiration", sa.Date(), nullable=True),
    )
    _add_column_if_missing(
        "approval_engine_cases",
        sa.Column("fingerprint_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing(
        "approval_engine_cases",
        sa.Column("fingerprint_instructions", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "approval_engine_cases",
        sa.Column("fingerprint_appointment_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "approval_engine_cases",
        sa.Column("fingerprint_completion_ref", sa.String(256), nullable=True),
    )
    _add_column_if_missing(
        "approval_engine_cases",
        sa.Column("fingerprint_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "approval_engine_cases",
        sa.Column("fingerprint_notes", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "approval_engine_training_modules",
        sa.Column("description", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "approval_engine_training_modules",
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing(
        "approval_engine_training_modules",
        sa.Column("acknowledgment", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    pass
