"""Nova freight execution events and last_status_at.

Revision ID: 20260909_nova_freight_lifecycle
Revises: 20260909_nova_freight_dispatch
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260909_nova_freight_lifecycle"
down_revision = "20260909_nova_freight_dispatch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    names = set(inspector.get_table_names())
    if "nova_freight_shipments" in names:
        existing = {col["name"] for col in inspector.get_columns("nova_freight_shipments")}
        if "last_status_at" not in existing:
            op.add_column("nova_freight_shipments", sa.Column("last_status_at", sa.DateTime(timezone=True), nullable=True))
    if "nova_freight_shipment_events" not in names:
        op.create_table(
            "nova_freight_shipment_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("event_id", sa.String(32), nullable=False),
            sa.Column("shipment_id", sa.String(32), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("status_before", sa.String(32), nullable=False),
            sa.Column("status_after", sa.String(32), nullable=False),
            sa.Column("event_type", sa.String(48), nullable=False, server_default="status_transition"),
            sa.Column("actor_user_id", sa.String(36), nullable=True),
            sa.Column("actor_carrier_id", sa.String(32), nullable=True),
            sa.Column("actor_role", sa.String(32), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("latitude", sa.Numeric(10, 6), nullable=True),
            sa.Column("longitude", sa.Numeric(10, 6), nullable=True),
            sa.Column("source", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_nova_freight_events_event_id", "nova_freight_shipment_events", ["event_id"], unique=True)
        op.create_index("ix_nova_freight_events_shipment_id", "nova_freight_shipment_events", ["shipment_id"])
        op.create_index("ix_nova_freight_events_org_id", "nova_freight_shipment_events", ["organization_id"])
        op.create_index("ix_nova_freight_events_created_at", "nova_freight_shipment_events", ["created_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    names = set(inspector.get_table_names())
    if "nova_freight_shipment_events" in names:
        op.drop_index("ix_nova_freight_events_created_at", table_name="nova_freight_shipment_events")
        op.drop_index("ix_nova_freight_events_org_id", table_name="nova_freight_shipment_events")
        op.drop_index("ix_nova_freight_events_shipment_id", table_name="nova_freight_shipment_events")
        op.drop_index("ix_nova_freight_events_event_id", table_name="nova_freight_shipment_events")
        op.drop_table("nova_freight_shipment_events")
    if "nova_freight_shipments" in names:
        existing = {col["name"] for col in inspector.get_columns("nova_freight_shipments")}
        if "last_status_at" in existing:
            op.drop_column("nova_freight_shipments", "last_status_at")
