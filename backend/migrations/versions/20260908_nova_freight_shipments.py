"""Nova freight shipments table.

Revision ID: 20260908_nova_freight_shipments
Revises: 20260831_driver_compliance

Creates nova_freight_shipments only. Does not alter Health ride or Delivery tables.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260908_nova_freight_shipments"
down_revision = "20260831_driver_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "nova_freight_shipments" in inspector.get_table_names():
        return

    op.create_table(
        "nova_freight_shipments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("shipment_id", sa.String(32), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("shipper_user_id", sa.String(36), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready_for_dispatch"),
        sa.Column("customer_name", sa.String(160), nullable=False),
        sa.Column("contact_name", sa.String(160), nullable=True),
        sa.Column("contact_phone", sa.String(40), nullable=True),
        sa.Column("contact_email", sa.String(320), nullable=True),
        sa.Column("pickup_address", sa.String(300), nullable=False),
        sa.Column("pickup_city", sa.String(120), nullable=False),
        sa.Column("pickup_state", sa.String(32), nullable=False),
        sa.Column("pickup_zip", sa.String(16), nullable=False),
        sa.Column("pickup_contact", sa.String(160), nullable=True),
        sa.Column("pickup_phone", sa.String(40), nullable=True),
        sa.Column("pickup_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pickup_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_address", sa.String(300), nullable=False),
        sa.Column("delivery_city", sa.String(120), nullable=False),
        sa.Column("delivery_state", sa.String(32), nullable=False),
        sa.Column("delivery_zip", sa.String(16), nullable=False),
        sa.Column("delivery_contact", sa.String(160), nullable=True),
        sa.Column("delivery_phone", sa.String(40), nullable=True),
        sa.Column("delivery_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commodity", sa.String(240), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=True),
        sa.Column("weight", sa.Numeric(12, 2), nullable=True),
        sa.Column("weight_unit", sa.String(8), nullable=False, server_default="lb"),
        sa.Column("piece_count", sa.Integer(), nullable=True),
        sa.Column("pallet_count", sa.Integer(), nullable=True),
        sa.Column("length_in", sa.Numeric(10, 2), nullable=True),
        sa.Column("width_in", sa.Numeric(10, 2), nullable=True),
        sa.Column("height_in", sa.Numeric(10, 2), nullable=True),
        sa.Column("special_handling_notes", sa.Text(), nullable=True),
        sa.Column("hazardous", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("temperature_controlled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fragile", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("equipment_type", sa.String(32), nullable=False, server_default="cargo_van"),
        sa.Column("quoted_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("carrier_payout_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("amicor_margin", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("proof_of_pickup_ref", sa.String(128), nullable=True),
        sa.Column("proof_of_delivery_ref", sa.String(128), nullable=True),
        sa.Column("document_refs_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_nova_freight_shipments_shipment_id",
        "nova_freight_shipments",
        ["shipment_id"],
        unique=True,
    )
    op.create_index("ix_nova_freight_shipments_org_id", "nova_freight_shipments", ["organization_id"])
    op.create_index("ix_nova_freight_shipments_status", "nova_freight_shipments", ["status"])
    op.create_index("ix_nova_freight_shipments_created_at", "nova_freight_shipments", ["created_at"])
    op.create_index(
        "ix_nova_freight_shipments_org_status",
        "nova_freight_shipments",
        ["organization_id", "status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "nova_freight_shipments" not in inspector.get_table_names():
        return
    op.drop_index("ix_nova_freight_shipments_org_status", table_name="nova_freight_shipments")
    op.drop_index("ix_nova_freight_shipments_created_at", table_name="nova_freight_shipments")
    op.drop_index("ix_nova_freight_shipments_status", table_name="nova_freight_shipments")
    op.drop_index("ix_nova_freight_shipments_org_id", table_name="nova_freight_shipments")
    op.drop_index("ix_nova_freight_shipments_shipment_id", table_name="nova_freight_shipments")
    op.drop_table("nova_freight_shipments")
