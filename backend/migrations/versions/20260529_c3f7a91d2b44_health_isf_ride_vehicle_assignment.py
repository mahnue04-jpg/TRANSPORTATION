"""health_isf_ride_vehicle_assignment

Revision ID: c3f7a91d2b44
Revises: e2f1b7c4a991
Create Date: 2026-05-29 00:00:00.000000

Adds nullable ride.vehicle_id foreign key and index for vehicle assignment contract.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c3f7a91d2b44"
down_revision: Union[str, None] = "e2f1b7c4a991"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("health_isf_rides", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("vehicle_id", sa.String(length=36), nullable=True))
            batch_op.create_foreign_key(
                "fk_health_isf_rides_vehicle_id_health_isf_vehicles",
                "health_isf_vehicles",
                ["vehicle_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index("ix_health_isf_rides_vehicle_id", ["vehicle_id"])
    else:
        op.add_column(
            "health_isf_rides",
            sa.Column("vehicle_id", sa.String(length=36), nullable=True),
        )
        op.create_foreign_key(
            "fk_health_isf_rides_vehicle_id_health_isf_vehicles",
            "health_isf_rides",
            "health_isf_vehicles",
            ["vehicle_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_health_isf_rides_vehicle_id", "health_isf_rides", ["vehicle_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("health_isf_rides", recreate="always") as batch_op:
            batch_op.drop_index("ix_health_isf_rides_vehicle_id")
            batch_op.drop_constraint(
                "fk_health_isf_rides_vehicle_id_health_isf_vehicles",
                type_="foreignkey",
            )
            batch_op.drop_column("vehicle_id")
    else:
        op.drop_index("ix_health_isf_rides_vehicle_id", table_name="health_isf_rides")
        op.drop_constraint(
            "fk_health_isf_rides_vehicle_id_health_isf_vehicles",
            "health_isf_rides",
            type_="foreignkey",
        )
        op.drop_column("health_isf_rides", "vehicle_id")
