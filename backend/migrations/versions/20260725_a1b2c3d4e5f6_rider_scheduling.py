"""rider_scheduling

Revision ID: a1b2c3d4e5f6
Revises: c3f7a91d2b44
Create Date: 2026-07-25 00:00:00.000000

Adds rider scheduling columns for round-trip legs and dispatch windows.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("health_isf_rides", sa.Column("round_trip_group_id", sa.String(length=36), nullable=True))
    op.add_column("health_isf_rides", sa.Column("trip_leg", sa.String(length=16), nullable=True))
    op.add_column("health_isf_rides", sa.Column("pickup_time", sa.DateTime(timezone=True), nullable=True))
    op.add_column("health_isf_rides", sa.Column("return_pickup_type", sa.String(length=32), nullable=True))
    op.add_column(
        "health_isf_rides",
        sa.Column("same_driver_preference", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("health_isf_rides", sa.Column("dispatch_eligible_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "health_isf_rides",
        sa.Column("call_when_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("health_isf_rides", sa.Column("scheduling_series_id", sa.String(length=36), nullable=True))

    op.create_index("ix_health_isf_rides_round_trip_group_id", "health_isf_rides", ["round_trip_group_id"])
    op.create_index("ix_health_isf_rides_trip_leg", "health_isf_rides", ["trip_leg"])
    op.create_index("ix_health_isf_rides_pickup_time", "health_isf_rides", ["pickup_time"])
    op.create_index("ix_health_isf_rides_dispatch_eligible_at", "health_isf_rides", ["dispatch_eligible_at"])
    op.create_index("ix_health_isf_rides_scheduling_series_id", "health_isf_rides", ["scheduling_series_id"])

    op.add_column("health_isf_customer_ride_requests", sa.Column("trip_type", sa.String(length=32), nullable=True))
    op.add_column("health_isf_customer_ride_requests", sa.Column("scheduling_metadata_json", sa.Text(), nullable=True))
    op.add_column("health_isf_customer_ride_requests", sa.Column("linked_ride_ids_json", sa.Text(), nullable=True))

    if bind.dialect.name != "sqlite":
        op.alter_column("health_isf_rides", "same_driver_preference", server_default=None)
        op.alter_column("health_isf_rides", "call_when_ready", server_default=None)


def downgrade() -> None:
    op.drop_column("health_isf_customer_ride_requests", "linked_ride_ids_json")
    op.drop_column("health_isf_customer_ride_requests", "scheduling_metadata_json")
    op.drop_column("health_isf_customer_ride_requests", "trip_type")

    op.drop_index("ix_health_isf_rides_scheduling_series_id", table_name="health_isf_rides")
    op.drop_index("ix_health_isf_rides_dispatch_eligible_at", table_name="health_isf_rides")
    op.drop_index("ix_health_isf_rides_pickup_time", table_name="health_isf_rides")
    op.drop_index("ix_health_isf_rides_trip_leg", table_name="health_isf_rides")
    op.drop_index("ix_health_isf_rides_round_trip_group_id", table_name="health_isf_rides")

    op.drop_column("health_isf_rides", "scheduling_series_id")
    op.drop_column("health_isf_rides", "call_when_ready")
    op.drop_column("health_isf_rides", "dispatch_eligible_at")
    op.drop_column("health_isf_rides", "same_driver_preference")
    op.drop_column("health_isf_rides", "return_pickup_type")
    op.drop_column("health_isf_rides", "pickup_time")
    op.drop_column("health_isf_rides", "trip_leg")
    op.drop_column("health_isf_rides", "round_trip_group_id")
