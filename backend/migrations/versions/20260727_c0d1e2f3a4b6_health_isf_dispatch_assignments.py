"""health_isf_dispatch_assignments baseline table

Revision ID: c0d1e2f3a4b6
Revises: f6e5d4c3b2a1
Create Date: 2026-07-27 00:00:00.000000

Creates dispatch assignment table required by driver_mobile_read_indexes migration.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c0d1e2f3a4b6"
down_revision: Union[str, None] = "f6e5d4c3b2a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "health_isf_dispatch_assignments" in inspector.get_table_names():
        return

    op.create_table(
        "health_isf_dispatch_assignments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("ride_id", sa.String(length=36), nullable=False),
        sa.Column("driver_id", sa.String(length=36), nullable=True),
        sa.Column("assignment_state", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("attempt_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("score_breakdown_json", sa.Text(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("search_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offer_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("en_route_pickup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pickup_complete_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dropoff_complete_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reassignment_pending_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reassignment_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reassignment_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reassignment_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reassignment_reason", sa.String(length=128), nullable=True),
        sa.Column("reassignment_chain_id", sa.String(length=64), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_reason", sa.String(length=128), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["health_isf_organizations.id"],
            name="fk_dispatch_assignments_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ride_id"],
            ["health_isf_rides.id"],
            name="fk_dispatch_assignments_ride",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["health_isf_drivers.id"],
            name="fk_dispatch_assignments_driver",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["platform_users.id"],
            name="fk_dispatch_assignments_created_by",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_health_isf_dispatch_assignments_organization_id", "health_isf_dispatch_assignments", ["organization_id"])
    op.create_index("ix_health_isf_dispatch_assignments_ride_id", "health_isf_dispatch_assignments", ["ride_id"])
    op.create_index("ix_health_isf_dispatch_assignments_driver_id", "health_isf_dispatch_assignments", ["driver_id"])
    op.create_index("ix_health_isf_dispatch_assignments_assignment_state", "health_isf_dispatch_assignments", ["assignment_state"])
    op.create_index("ix_health_isf_dispatch_assignments_attempt_index", "health_isf_dispatch_assignments", ["attempt_index"])
    op.create_index("ix_health_isf_dispatch_assignments_offer_expires_at", "health_isf_dispatch_assignments", ["offer_expires_at"])
    op.create_index("ix_health_isf_dispatch_assignments_reassignment_chain_id", "health_isf_dispatch_assignments", ["reassignment_chain_id"])
    op.create_index("ix_health_isf_dispatch_assignments_created_by_user_id", "health_isf_dispatch_assignments", ["created_by_user_id"])
    op.create_index("ix_health_isf_dispatch_assignments_created_at", "health_isf_dispatch_assignments", ["created_at"])
    op.create_index("idx_dispatch_assign_org_ride", "health_isf_dispatch_assignments", ["organization_id", "ride_id"])
    op.create_index("idx_dispatch_assign_org_state", "health_isf_dispatch_assignments", ["organization_id", "assignment_state"])
    op.create_index("idx_dispatch_assign_ride_attempt", "health_isf_dispatch_assignments", ["ride_id", "attempt_index"])
    op.create_index("idx_dispatch_assign_offer_expiry", "health_isf_dispatch_assignments", ["assignment_state", "offer_expires_at"])

    if bind.dialect.name != "sqlite":
        op.alter_column("health_isf_dispatch_assignments", "assignment_state", server_default=None)
        op.alter_column("health_isf_dispatch_assignments", "attempt_index", server_default=None)
        op.alter_column("health_isf_dispatch_assignments", "timeout_seconds", server_default=None)
        op.alter_column("health_isf_dispatch_assignments", "reassignment_attempt_count", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "health_isf_dispatch_assignments" not in inspector.get_table_names():
        return
    op.drop_table("health_isf_dispatch_assignments")
