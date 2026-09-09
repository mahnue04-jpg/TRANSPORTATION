"""Nova freight carriers, offers, and assignment columns.

Revision ID: 20260909_nova_freight_dispatch
Revises: 20260908_nova_freight_shipments

Does not alter Health ride or Delivery tables.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260909_nova_freight_dispatch"
down_revision = "20260908_nova_freight_shipments"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table)}
    if column.name not in existing:
        op.add_column(table, column)


def upgrade() -> None:
    names = _table_names()
    if "nova_freight_shipments" in names:
        _add_column_if_missing(
            "nova_freight_shipments",
            sa.Column("assigned_carrier_id", sa.String(32), nullable=True),
        )
        _add_column_if_missing(
            "nova_freight_shipments",
            sa.Column("assigned_offer_id", sa.String(32), nullable=True),
        )

    if "nova_freight_carriers" not in names:
        op.create_table(
            "nova_freight_carriers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("carrier_id", sa.String(32), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.String(36), nullable=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("contact_name", sa.String(160), nullable=True),
            sa.Column("contact_phone", sa.String(40), nullable=True),
            sa.Column("contact_email", sa.String(320), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("equipment_type", sa.String(32), nullable=False, server_default="cargo_van"),
            sa.Column("service_area", sa.String(240), nullable=True),
            sa.Column("availability", sa.String(32), nullable=False, server_default="available"),
            sa.Column("authority_status", sa.String(32), nullable=False, server_default="placeholder"),
            sa.Column("insurance_status", sa.String(32), nullable=False, server_default="placeholder"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_nova_freight_carriers_carrier_id", "nova_freight_carriers", ["carrier_id"], unique=True)
        op.create_index("ix_nova_freight_carriers_org_id", "nova_freight_carriers", ["organization_id"])
        op.create_index("ix_nova_freight_carriers_user_id", "nova_freight_carriers", ["user_id"])
        op.create_index("ix_nova_freight_carriers_active", "nova_freight_carriers", ["organization_id", "active"])

    if "nova_freight_offers" not in names:
        op.create_table(
            "nova_freight_offers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("offer_id", sa.String(32), nullable=False),
            sa.Column("shipment_id", sa.String(32), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("carrier_id", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("offered_rate", sa.Numeric(12, 2), nullable=True),
            sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
            sa.Column("offered_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_user_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_nova_freight_offers_offer_id", "nova_freight_offers", ["offer_id"], unique=True)
        op.create_index("ix_nova_freight_offers_shipment_id", "nova_freight_offers", ["shipment_id"])
        op.create_index("ix_nova_freight_offers_carrier_id", "nova_freight_offers", ["carrier_id"])
        op.create_index("ix_nova_freight_offers_org_status", "nova_freight_offers", ["organization_id", "status"])
        op.create_index("ix_nova_freight_offers_shipment_status", "nova_freight_offers", ["shipment_id", "status"])


def downgrade() -> None:
    names = _table_names()
    if "nova_freight_offers" in names:
        op.drop_index("ix_nova_freight_offers_shipment_status", table_name="nova_freight_offers")
        op.drop_index("ix_nova_freight_offers_org_status", table_name="nova_freight_offers")
        op.drop_index("ix_nova_freight_offers_carrier_id", table_name="nova_freight_offers")
        op.drop_index("ix_nova_freight_offers_shipment_id", table_name="nova_freight_offers")
        op.drop_index("ix_nova_freight_offers_offer_id", table_name="nova_freight_offers")
        op.drop_table("nova_freight_offers")
    if "nova_freight_carriers" in names:
        op.drop_index("ix_nova_freight_carriers_active", table_name="nova_freight_carriers")
        op.drop_index("ix_nova_freight_carriers_user_id", table_name="nova_freight_carriers")
        op.drop_index("ix_nova_freight_carriers_org_id", table_name="nova_freight_carriers")
        op.drop_index("ix_nova_freight_carriers_carrier_id", table_name="nova_freight_carriers")
        op.drop_table("nova_freight_carriers")
    if "nova_freight_shipments" in names:
        inspector = sa.inspect(op.get_bind())
        existing = {col["name"] for col in inspector.get_columns("nova_freight_shipments")}
        if "assigned_offer_id" in existing:
            op.drop_column("nova_freight_shipments", "assigned_offer_id")
        if "assigned_carrier_id" in existing:
            op.drop_column("nova_freight_shipments", "assigned_carrier_id")
