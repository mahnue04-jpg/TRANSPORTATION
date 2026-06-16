"""health_isf_operational_reliability

Revision ID: b9f4c2d1a901
Revises: 2a7c8b9d5f12
Create Date: 2026-05-17 22:00:00.000000

Adds retry queue, dead-letter queue, idempotency, and operational alerts tables.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b9f4c2d1a901"
down_revision: Union[str, None] = "2a7c8b9d5f12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "health_isf_dispatch_event_retries",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(1024), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("ride_id", sa.String(36), nullable=True),
        sa.Column("driver_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["health_isf_organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ride_id"], ["health_isf_rides.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["driver_id"], ["health_isf_drivers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_isf_dispatch_event_retries_organization_id", "health_isf_dispatch_event_retries", ["organization_id"])
    op.create_index("ix_health_isf_dispatch_event_retries_event_type", "health_isf_dispatch_event_retries", ["event_type"])
    op.create_index("ix_health_isf_dispatch_event_retries_status", "health_isf_dispatch_event_retries", ["status"])
    op.create_index("ix_health_isf_dispatch_event_retries_next_retry_at", "health_isf_dispatch_event_retries", ["next_retry_at"])
    op.create_index("ix_health_isf_dispatch_event_retries_idempotency_key", "health_isf_dispatch_event_retries", ["idempotency_key"], unique=True)
    op.create_index("idx_dispatch_retries_org_status", "health_isf_dispatch_event_retries", ["organization_id", "status"])
    op.create_index("idx_dispatch_retries_due", "health_isf_dispatch_event_retries", ["status", "next_retry_at"])

    op.create_table(
        "health_isf_dispatch_dead_letters",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("retry_event_id", sa.String(36), nullable=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["retry_event_id"], ["health_isf_dispatch_event_retries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["health_isf_organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_isf_dispatch_dead_letters_retry_event_id", "health_isf_dispatch_dead_letters", ["retry_event_id"])
    op.create_index("ix_health_isf_dispatch_dead_letters_organization_id", "health_isf_dispatch_dead_letters", ["organization_id"])
    op.create_index("ix_health_isf_dispatch_dead_letters_event_type", "health_isf_dispatch_dead_letters", ["event_type"])
    op.create_index("ix_health_isf_dispatch_dead_letters_created_at", "health_isf_dispatch_dead_letters", ["created_at"])

    op.create_table(
        "health_isf_dispatch_idempotency",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_isf_dispatch_idempotency_idempotency_key", "health_isf_dispatch_idempotency", ["idempotency_key"], unique=True)
    op.create_index("ix_health_isf_dispatch_idempotency_scope", "health_isf_dispatch_idempotency", ["scope"])
    op.create_index("ix_health_isf_dispatch_idempotency_resource_id", "health_isf_dispatch_idempotency", ["resource_id"])
    op.create_index("ix_health_isf_dispatch_idempotency_processed_at", "health_isf_dispatch_idempotency", ["processed_at"])
    op.create_index("ix_health_isf_dispatch_idempotency_expires_at", "health_isf_dispatch_idempotency", ["expires_at"])

    op.create_table(
        "health_isf_operational_alerts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("alert_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.String(512), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["health_isf_organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_isf_operational_alerts_organization_id", "health_isf_operational_alerts", ["organization_id"])
    op.create_index("ix_health_isf_operational_alerts_alert_type", "health_isf_operational_alerts", ["alert_type"])
    op.create_index("ix_health_isf_operational_alerts_severity", "health_isf_operational_alerts", ["severity"])
    op.create_index("ix_health_isf_operational_alerts_created_at", "health_isf_operational_alerts", ["created_at"])
    op.create_index("ix_health_isf_operational_alerts_resolved_at", "health_isf_operational_alerts", ["resolved_at"])
    op.create_index("idx_alerts_org_created", "health_isf_operational_alerts", ["organization_id", "created_at"])


def downgrade() -> None:
    op.drop_table("health_isf_operational_alerts")
    op.drop_table("health_isf_dispatch_idempotency")
    op.drop_table("health_isf_dispatch_dead_letters")
    op.drop_table("health_isf_dispatch_event_retries")
