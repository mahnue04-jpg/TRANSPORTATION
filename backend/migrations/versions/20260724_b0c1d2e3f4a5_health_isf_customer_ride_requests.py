"""health_isf_customer_ride_requests baseline table

Revision ID: b0c1d2e3f4a5
Revises: c3f7a91d2b44
Create Date: 2026-07-24 00:00:00.000000

Creates customer ride request queue table required by rider_scheduling migration.
Previously created only via runtime ensure_health_isf_schema(), which broke clean
alembic upgrade on fresh databases (e.g. Render releaseCommand).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, None] = "c3f7a91d2b44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "health_isf_customer_ride_requests" in inspector.get_table_names():
        return

    op.create_table(
        "health_isf_customer_ride_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("ride_id", sa.String(length=36), nullable=False),
        sa.Column("submitted_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("rider_name", sa.String(length=256), nullable=False),
        sa.Column("rider_phone", sa.String(length=32), nullable=False),
        sa.Column("pickup_address", sa.String(length=512), nullable=False),
        sa.Column("dropoff_address", sa.String(length=512), nullable=False),
        sa.Column("scheduled_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ride_type", sa.String(length=32), nullable=False),
        sa.Column("is_recurring", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recurring_pattern_json", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("dispatch_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("pending_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("broadcasted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("in_progress_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["health_isf_organizations.id"],
            name="fk_customer_ride_requests_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ride_id"],
            ["health_isf_rides.id"],
            name="fk_customer_ride_requests_ride",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"],
            ["platform_users.id"],
            name="fk_customer_ride_requests_submitted_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("ride_id", name="uq_customer_ride_requests_ride_id"),
    )
    op.create_index(
        "ix_health_isf_customer_ride_requests_organization_id",
        "health_isf_customer_ride_requests",
        ["organization_id"],
    )
    op.create_index(
        "ix_health_isf_customer_ride_requests_ride_id",
        "health_isf_customer_ride_requests",
        ["ride_id"],
    )
    op.create_index(
        "ix_health_isf_customer_ride_requests_submitted_by_user_id",
        "health_isf_customer_ride_requests",
        ["submitted_by_user_id"],
    )
    op.create_index(
        "ix_health_isf_customer_ride_requests_scheduled_time",
        "health_isf_customer_ride_requests",
        ["scheduled_time"],
    )
    op.create_index(
        "ix_health_isf_customer_ride_requests_ride_type",
        "health_isf_customer_ride_requests",
        ["ride_type"],
    )
    op.create_index(
        "ix_health_isf_customer_ride_requests_is_recurring",
        "health_isf_customer_ride_requests",
        ["is_recurring"],
    )
    op.create_index(
        "ix_health_isf_customer_ride_requests_dispatch_status",
        "health_isf_customer_ride_requests",
        ["dispatch_status"],
    )
    op.create_index(
        "ix_health_isf_customer_ride_requests_pending_at",
        "health_isf_customer_ride_requests",
        ["pending_at"],
    )
    op.create_index(
        "ix_health_isf_customer_ride_requests_created_at",
        "health_isf_customer_ride_requests",
        ["created_at"],
    )
    op.create_index(
        "idx_customer_requests_org_status",
        "health_isf_customer_ride_requests",
        ["organization_id", "dispatch_status"],
    )
    op.create_index(
        "idx_customer_requests_org_created",
        "health_isf_customer_ride_requests",
        ["organization_id", "created_at"],
    )

    if bind.dialect.name != "sqlite":
        op.alter_column("health_isf_customer_ride_requests", "is_recurring", server_default=None)
        op.alter_column("health_isf_customer_ride_requests", "dispatch_status", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "health_isf_customer_ride_requests" not in inspector.get_table_names():
        return
    op.drop_table("health_isf_customer_ride_requests")
