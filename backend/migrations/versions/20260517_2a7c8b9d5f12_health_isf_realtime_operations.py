"""health_isf_realtime_operations

Revision ID: 2a7c8b9d5f12
Revises: 051233e3a434
Create Date: 2026-05-17 20:00:00.000000

Adds real-time event architecture, activity logging, and concurrent assignment protection.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "2a7c8b9d5f12"
down_revision: Union[str, None] = "051233e3a434"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply real-time operations schema changes."""
    
    # Add version columns for optimistic locking
    op.add_column(
        "health_isf_rides",
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "health_isf_drivers",
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    
    # Create RealTimeEvent table
    op.create_table(
        "health_isf_realtime_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("ride_id", sa.String(36), nullable=True),
        sa.Column("driver_id", sa.String(36), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["health_isf_organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ride_id"],
            ["health_isf_rides.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["health_isf_drivers.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["platform_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_events_org_timestamp",
        "health_isf_realtime_events",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "idx_events_ride_type",
        "health_isf_realtime_events",
        ["ride_id", "event_type"],
    )
    op.create_index(
        "idx_events_driver_type",
        "health_isf_realtime_events",
        ["driver_id", "event_type"],
    )
    op.create_index(
        "ix_health_isf_realtime_events_created_at",
        "health_isf_realtime_events",
        ["created_at"],
    )
    op.create_index(
        "ix_health_isf_realtime_events_event_type",
        "health_isf_realtime_events",
        ["event_type"],
    )
    op.create_index(
        "ix_health_isf_realtime_events_organization_id",
        "health_isf_realtime_events",
        ["organization_id"],
    )
    
    # Create DispatcherActivityLog table
    op.create_table(
        "health_isf_dispatcher_activity",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("ride_id", sa.String(36), nullable=True),
        sa.Column("driver_id", sa.String(36), nullable=True),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["health_isf_organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ride_id"],
            ["health_isf_rides.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["health_isf_drivers.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["platform_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_activity_org_timestamp",
        "health_isf_dispatcher_activity",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "idx_activity_ride",
        "health_isf_dispatcher_activity",
        ["ride_id", "created_at"],
    )
    op.create_index(
        "idx_activity_driver",
        "health_isf_dispatcher_activity",
        ["driver_id", "created_at"],
    )
    op.create_index(
        "ix_health_isf_dispatcher_activity_action",
        "health_isf_dispatcher_activity",
        ["action"],
    )
    op.create_index(
        "ix_health_isf_dispatcher_activity_created_at",
        "health_isf_dispatcher_activity",
        ["created_at"],
    )
    op.create_index(
        "ix_health_isf_dispatcher_activity_organization_id",
        "health_isf_dispatcher_activity",
        ["organization_id"],
    )
    
    # Create RideAssignmentLock table
    op.create_table(
        "health_isf_assignment_locks",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("ride_id", sa.String(36), nullable=False, unique=True),
        sa.Column("locked_by_user_id", sa.String(36), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ride_id"],
            ["health_isf_rides.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["locked_by_user_id"],
            ["platform_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_locks_expires_at",
        "health_isf_assignment_locks",
        ["expires_at"],
    )
    op.create_index(
        "ix_health_isf_assignment_locks_ride_id",
        "health_isf_assignment_locks",
        ["ride_id"],
    )


def downgrade() -> None:
    """Revert real-time operations schema changes."""
    
    # Drop tables in reverse order
    op.drop_table("health_isf_assignment_locks")
    op.drop_table("health_isf_dispatcher_activity")
    op.drop_table("health_isf_realtime_events")
    
    # Remove version columns
    op.drop_column("health_isf_drivers", "version")
    op.drop_column("health_isf_rides", "version")
