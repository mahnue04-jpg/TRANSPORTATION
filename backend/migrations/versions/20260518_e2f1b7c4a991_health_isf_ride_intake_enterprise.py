"""health_isf_ride_intake_enterprise

Revision ID: e2f1b7c4a991
Revises: d5c4e8a1c901
Create Date: 2026-05-18 00:20:00.000000

Adds enterprise intake and dispatch-prep fields to rides.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e2f1b7c4a991"
down_revision: Union[str, None] = "d5c4e8a1c901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("health_isf_rides", sa.Column("priority_score", sa.Float(), nullable=True))
    op.add_column("health_isf_rides", sa.Column("priority_tag", sa.String(length=32), nullable=True))
    op.add_column("health_isf_rides", sa.Column("is_emergency", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("health_isf_rides", sa.Column("appointment_time", sa.DateTime(timezone=True), nullable=True))
    op.add_column("health_isf_rides", sa.Column("recurring_trip_pattern", sa.Text(), nullable=True))
    op.add_column("health_isf_rides", sa.Column("ai_dispatch_context", sa.Text(), nullable=True))
    op.add_column("health_isf_rides", sa.Column("intake_fingerprint", sa.String(length=128), nullable=True))

    op.create_index("ix_health_isf_rides_priority_tag", "health_isf_rides", ["priority_tag"])
    op.create_index("ix_health_isf_rides_is_emergency", "health_isf_rides", ["is_emergency"])
    op.create_index("ix_health_isf_rides_appointment_time", "health_isf_rides", ["appointment_time"])
    op.create_index("ix_health_isf_rides_intake_fingerprint", "health_isf_rides", ["intake_fingerprint"])

    if bind.dialect.name != "sqlite":
        op.alter_column("health_isf_rides", "is_emergency", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_health_isf_rides_intake_fingerprint", table_name="health_isf_rides")
    op.drop_index("ix_health_isf_rides_appointment_time", table_name="health_isf_rides")
    op.drop_index("ix_health_isf_rides_is_emergency", table_name="health_isf_rides")
    op.drop_index("ix_health_isf_rides_priority_tag", table_name="health_isf_rides")

    op.drop_column("health_isf_rides", "intake_fingerprint")
    op.drop_column("health_isf_rides", "ai_dispatch_context")
    op.drop_column("health_isf_rides", "recurring_trip_pattern")
    op.drop_column("health_isf_rides", "appointment_time")
    op.drop_column("health_isf_rides", "is_emergency")
    op.drop_column("health_isf_rides", "priority_tag")
    op.drop_column("health_isf_rides", "priority_score")
