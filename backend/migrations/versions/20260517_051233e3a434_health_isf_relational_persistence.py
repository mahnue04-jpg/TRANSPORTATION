"""health_isf_relational_persistence

Revision ID: 051233e3a434
Revises: 0002
Create Date: 2026-05-17 19:41:34.383187
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "051233e3a434"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ORG_ID = "00000000-0000-0000-0000-00000000a1c0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _insert_default_org(bind) -> None:
    bind.execute(
        sa.text(
            """
            INSERT INTO health_isf_organizations (
              id, name, code, address, phone, is_active, created_at, updated_at
            ) VALUES (
              :id, :name, :code, :address, :phone, 1, :created_at, :updated_at
            )
            """
        ),
        {
            "id": DEFAULT_ORG_ID,
            "name": "Amicor Health ISF",
            "code": "AMICOR-ISF",
            "address": "100 Operations Ave, New York, NY 10001",
            "phone": "212-555-0000",
            "created_at": _now(),
            "updated_at": _now(),
        },
    )


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "health_isf_organizations"):
        op.create_table(
            "health_isf_organizations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=256), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("address", sa.String(length=512), nullable=True),
            sa.Column("phone", sa.String(length=20), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_health_isf_organizations_code ON health_isf_organizations (code)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_organizations_is_active ON health_isf_organizations (is_active)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_organizations_name ON health_isf_organizations (name)"))
    existing_org = bind.execute(sa.text("SELECT id FROM health_isf_organizations WHERE code = :code"), {"code": "AMICOR-ISF"}).fetchone()
    if not existing_org:
        _insert_default_org(bind)

    # Bootstrap legacy base entities when migrating a truly empty database.
    # Earlier runtime paths created these tables via metadata.create_all; clean Alembic
    # runs must create them explicitly so downstream revisions can ALTER them.
    if not _table_exists(bind, "health_isf_providers"):
        op.create_table(
            "health_isf_providers",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=256), nullable=False),
            sa.Column("address", sa.String(length=512), nullable=False),
            sa.Column("phone", sa.String(length=20), nullable=False),
            sa.Column("service_type", sa.String(length=128), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_providers_is_active ON health_isf_providers (is_active)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_providers_name ON health_isf_providers (name)"))

    if not _table_exists(bind, "health_isf_drivers"):
        op.create_table(
            "health_isf_drivers",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=256), nullable=False),
            sa.Column("phone", sa.String(length=20), nullable=False),
            sa.Column("vehicle_type", sa.String(length=128), nullable=False),
            sa.Column("vehicle_plate", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="offline"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("total_trips", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rating", sa.Float(), nullable=False, server_default="5.0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_health_isf_drivers_phone ON health_isf_drivers (phone)"))
    bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_health_isf_drivers_vehicle_plate ON health_isf_drivers (vehicle_plate)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_drivers_name ON health_isf_drivers (name)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_drivers_status ON health_isf_drivers (status)"))

    if not _table_exists(bind, "health_isf_rides"):
        op.create_table(
            "health_isf_rides",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("provider_id", sa.String(length=36), nullable=False),
            sa.Column("driver_id", sa.String(length=36), nullable=True),
            sa.Column("passenger_name", sa.String(length=256), nullable=False),
            sa.Column("passenger_phone", sa.String(length=20), nullable=False),
            sa.Column("pickup_address", sa.String(length=512), nullable=False),
            sa.Column("dropoff_address", sa.String(length=512), nullable=False),
            sa.Column("service_type", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("estimated_distance_miles", sa.Float(), nullable=True),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["provider_id"], ["health_isf_providers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["driver_id"], ["health_isf_drivers.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_rides_provider_id ON health_isf_rides (provider_id)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_rides_driver_id ON health_isf_rides (driver_id)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_rides_status ON health_isf_rides (status)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_rides_requested_at ON health_isf_rides (requested_at)"))

    if not _table_exists(bind, "health_isf_vehicles"):
        op.create_table(
            "health_isf_vehicles",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("vehicle_type", sa.String(length=128), nullable=False),
            sa.Column("vehicle_plate", sa.String(length=50), nullable=False),
            sa.Column("capacity", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["health_isf_organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_vehicles_is_active ON health_isf_vehicles (is_active)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_vehicles_organization_id ON health_isf_vehicles (organization_id)"))
    bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_health_isf_vehicles_vehicle_plate ON health_isf_vehicles (vehicle_plate)"))

    if not _table_exists(bind, "health_isf_dispatch_logs"):
        op.create_table(
            "health_isf_dispatch_logs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("ride_id", sa.String(length=36), nullable=False),
            sa.Column("driver_id", sa.String(length=36), nullable=True),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("note", sa.String(length=1024), nullable=True),
            sa.Column("acted_by_user_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["acted_by_user_id"], ["platform_users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["driver_id"], ["health_isf_drivers.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["ride_id"], ["health_isf_rides.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_dispatch_logs_acted_by_user_id ON health_isf_dispatch_logs (acted_by_user_id)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_dispatch_logs_action ON health_isf_dispatch_logs (action)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_dispatch_logs_driver_id ON health_isf_dispatch_logs (driver_id)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_dispatch_logs_ride_id ON health_isf_dispatch_logs (ride_id)"))

    if not _table_exists(bind, "health_isf_ride_status_history"):
        op.create_table(
            "health_isf_ride_status_history",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("ride_id", sa.String(length=36), nullable=False),
            sa.Column("from_status", sa.String(length=32), nullable=True),
            sa.Column("to_status", sa.String(length=32), nullable=False),
            sa.Column("note", sa.String(length=1024), nullable=True),
            sa.Column("changed_by_user_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["changed_by_user_id"], ["platform_users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["ride_id"], ["health_isf_rides.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_ride_status_history_changed_by_user_id ON health_isf_ride_status_history (changed_by_user_id)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_health_isf_ride_status_history_ride_id ON health_isf_ride_status_history (ride_id)"))

    if _table_exists(bind, "health_isf_drivers"):
        with op.batch_alter_table("health_isf_drivers", recreate="always") as batch_op:
            if not _column_exists(bind, "health_isf_drivers", "organization_id"):
                batch_op.add_column(sa.Column("organization_id", sa.String(length=36), nullable=True))
            if not _column_exists(bind, "health_isf_drivers", "vehicle_id"):
                batch_op.add_column(sa.Column("vehicle_id", sa.String(length=36), nullable=True))
            batch_op.create_index(op.f("ix_health_isf_drivers_organization_id"), ["organization_id"], unique=False)
            batch_op.create_index(op.f("ix_health_isf_drivers_vehicle_id"), ["vehicle_id"], unique=True)
            batch_op.create_foreign_key("fk_health_isf_drivers_organization_id", "health_isf_organizations", ["organization_id"], ["id"], ondelete="CASCADE")
            batch_op.create_foreign_key("fk_health_isf_drivers_vehicle_id", "health_isf_vehicles", ["vehicle_id"], ["id"], ondelete="SET NULL")

        bind.execute(sa.text("UPDATE health_isf_drivers SET organization_id = :org_id WHERE organization_id IS NULL"), {"org_id": DEFAULT_ORG_ID})
        rows = bind.execute(sa.text("SELECT id, vehicle_type, vehicle_plate FROM health_isf_drivers")).mappings().all()
        for row in rows:
            existing = bind.execute(
                sa.text("SELECT id FROM health_isf_vehicles WHERE vehicle_plate = :plate"),
                {"plate": row["vehicle_plate"]},
            ).fetchone()
            vehicle_id = existing[0] if existing else str(uuid.uuid4())
            if not existing:
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO health_isf_vehicles (
                          id, organization_id, vehicle_type, vehicle_plate, capacity, is_active, created_at, updated_at
                        ) VALUES (
                          :id, :organization_id, :vehicle_type, :vehicle_plate, 4, 1, :created_at, :updated_at
                        )
                        """
                    ),
                    {
                        "id": vehicle_id,
                        "organization_id": DEFAULT_ORG_ID,
                        "vehicle_type": row["vehicle_type"] or "sedan",
                        "vehicle_plate": row["vehicle_plate"],
                        "created_at": _now(),
                        "updated_at": _now(),
                    },
                )
            bind.execute(
                sa.text("UPDATE health_isf_drivers SET vehicle_id = :vehicle_id WHERE id = :driver_id"),
                {"vehicle_id": vehicle_id, "driver_id": row["id"]},
            )

    if _table_exists(bind, "health_isf_providers"):
        with op.batch_alter_table("health_isf_providers", recreate="always") as batch_op:
            if not _column_exists(bind, "health_isf_providers", "organization_id"):
                batch_op.add_column(sa.Column("organization_id", sa.String(length=36), nullable=True))
            batch_op.create_index(op.f("ix_health_isf_providers_organization_id"), ["organization_id"], unique=False)
            batch_op.create_foreign_key("fk_health_isf_providers_organization_id", "health_isf_organizations", ["organization_id"], ["id"], ondelete="CASCADE")
        bind.execute(sa.text("UPDATE health_isf_providers SET organization_id = :org_id WHERE organization_id IS NULL"), {"org_id": DEFAULT_ORG_ID})

    if _table_exists(bind, "health_isf_rides"):
        with op.batch_alter_table("health_isf_rides", recreate="always") as batch_op:
            if not _column_exists(bind, "health_isf_rides", "organization_id"):
                batch_op.add_column(sa.Column("organization_id", sa.String(length=36), nullable=True))
            if not _column_exists(bind, "health_isf_rides", "created_by_user_id"):
                batch_op.add_column(sa.Column("created_by_user_id", sa.String(length=36), nullable=True))
            if not _column_exists(bind, "health_isf_rides", "assigned_by_user_id"):
                batch_op.add_column(sa.Column("assigned_by_user_id", sa.String(length=36), nullable=True))
            if not _column_exists(bind, "health_isf_rides", "last_status_changed_by_user_id"):
                batch_op.add_column(sa.Column("last_status_changed_by_user_id", sa.String(length=36), nullable=True))
            if not _column_exists(bind, "health_isf_rides", "created_at"):
                batch_op.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
            if not _column_exists(bind, "health_isf_rides", "updated_at"):
                batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
            batch_op.create_index("idx_rides_org_status", ["organization_id", "status"], unique=False)
            batch_op.create_index(op.f("ix_health_isf_rides_assigned_by_user_id"), ["assigned_by_user_id"], unique=False)
            batch_op.create_index(op.f("ix_health_isf_rides_created_by_user_id"), ["created_by_user_id"], unique=False)
            batch_op.create_index(op.f("ix_health_isf_rides_last_status_changed_by_user_id"), ["last_status_changed_by_user_id"], unique=False)
            batch_op.create_index(op.f("ix_health_isf_rides_organization_id"), ["organization_id"], unique=False)
            batch_op.create_foreign_key("fk_health_isf_rides_organization_id", "health_isf_organizations", ["organization_id"], ["id"], ondelete="CASCADE")
            batch_op.create_foreign_key("fk_health_isf_rides_created_by_user_id", "platform_users", ["created_by_user_id"], ["id"], ondelete="SET NULL")
            batch_op.create_foreign_key("fk_health_isf_rides_assigned_by_user_id", "platform_users", ["assigned_by_user_id"], ["id"], ondelete="SET NULL")
            batch_op.create_foreign_key("fk_health_isf_rides_last_status_changed_by_user_id", "platform_users", ["last_status_changed_by_user_id"], ["id"], ondelete="SET NULL")

        bind.execute(sa.text("UPDATE health_isf_rides SET organization_id = :org_id WHERE organization_id IS NULL"), {"org_id": DEFAULT_ORG_ID})
        bind.execute(sa.text("UPDATE health_isf_rides SET created_at = COALESCE(created_at, requested_at, :ts)"), {"ts": _now()})
        bind.execute(sa.text("UPDATE health_isf_rides SET updated_at = COALESCE(updated_at, requested_at, :ts)"), {"ts": _now()})

        rides = bind.execute(sa.text("SELECT id, status FROM health_isf_rides")).mappings().all()
        for ride in rides:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO health_isf_dispatch_logs (
                      id, ride_id, driver_id, action, note, acted_by_user_id, created_at
                    ) VALUES (
                      :id, :ride_id, NULL, 'migration_backfill', :note, NULL, :created_at
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "ride_id": ride["id"],
                    "note": "Backfilled by migration",
                    "created_at": _now(),
                },
            )
            bind.execute(
                sa.text(
                    """
                    INSERT INTO health_isf_ride_status_history (
                      id, ride_id, from_status, to_status, note, changed_by_user_id, created_at
                    ) VALUES (
                      :id, :ride_id, NULL, :to_status, :note, NULL, :created_at
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "ride_id": ride["id"],
                    "to_status": str(ride["status"]),
                    "note": "Backfilled from current ride status",
                    "created_at": _now(),
                },
            )

    if _table_exists(bind, "health_isf_trips"):
        with op.batch_alter_table("health_isf_trips", recreate="always") as batch_op:
            if not _column_exists(bind, "health_isf_trips", "updated_at"):
                batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        bind.execute(sa.text("UPDATE health_isf_trips SET updated_at = COALESCE(updated_at, created_at, :ts)"), {"ts": _now()})

    if _table_exists(bind, "health_isf_payouts"):
        with op.batch_alter_table("health_isf_payouts", recreate="always") as batch_op:
            if not _column_exists(bind, "health_isf_payouts", "updated_at"):
                batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        bind.execute(sa.text("UPDATE health_isf_payouts SET updated_at = COALESCE(updated_at, created_at, :ts)"), {"ts": _now()})

    if _table_exists(bind, "platform_users") and _column_exists(bind, "platform_users", "role"):
        bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_platform_users_role ON platform_users (role)"))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_platform_users_role")

    op.drop_table("health_isf_ride_status_history")
    op.drop_table("health_isf_dispatch_logs")
    op.drop_table("health_isf_vehicles")
    op.drop_table("health_isf_organizations")
