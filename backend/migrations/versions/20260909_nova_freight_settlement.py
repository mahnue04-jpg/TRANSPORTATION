"""Nova freight carrier payouts and settlements.

Revision ID: 20260909_nova_freight_settlement
Revises: 20260909_nova_freight_commercial
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260909_nova_freight_settlement"
down_revision = "20260909_nova_freight_commercial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    names = set(inspector.get_table_names())
    if "nova_freight_shipment_events" in names:
        existing = {col["name"] for col in inspector.get_columns("nova_freight_shipment_events")}
        if "payout_id" not in existing:
            op.add_column("nova_freight_shipment_events", sa.Column("payout_id", sa.String(32), nullable=True))
        if "settlement_id" not in existing:
            op.add_column("nova_freight_shipment_events", sa.Column("settlement_id", sa.String(32), nullable=True))
    if "nova_freight_payouts" not in names:
        op.create_table(
            "nova_freight_payouts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("payout_id", sa.String(32), nullable=False),
            sa.Column("shipment_id", sa.String(32), nullable=False),
            sa.Column("carrier_id", sa.String(32), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("invoice_id", sa.String(32), nullable=True),
            sa.Column("customer_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("carrier_payout_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("amicor_margin_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("adjustment_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
            sa.Column("payout_status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("payout_method", sa.String(32), nullable=False, server_default="simulated_test"),
            sa.Column("external_payout_reference", sa.String(128), nullable=True),
            sa.Column("stripe_transfer_id", sa.String(128), nullable=True),
            sa.Column("approved_by", sa.String(36), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("adjusted_by", sa.String(36), nullable=True),
            sa.Column("adjusted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("adjustment_reason", sa.Text(), nullable=True),
            sa.Column("failure_reason", sa.String(512), nullable=True),
            sa.Column("hold_reason", sa.String(512), nullable=True),
            sa.Column("proof_warning", sa.String(240), nullable=True),
            sa.Column("idempotency_key", sa.String(80), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("processing_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_nova_freight_payouts_payout_id", "nova_freight_payouts", ["payout_id"], unique=True)
        op.create_index("ix_nova_freight_payouts_shipment_id", "nova_freight_payouts", ["shipment_id"])
        op.create_index("ix_nova_freight_payouts_carrier_id", "nova_freight_payouts", ["carrier_id"])
        op.create_index("ix_nova_freight_payouts_org_id", "nova_freight_payouts", ["organization_id"])
        op.create_index("ix_nova_freight_payouts_idem", "nova_freight_payouts", ["idempotency_key"], unique=True)
    if "nova_freight_settlements" not in names:
        op.create_table(
            "nova_freight_settlements",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("settlement_id", sa.String(32), nullable=False),
            sa.Column("payout_id", sa.String(32), nullable=False),
            sa.Column("shipment_id", sa.String(32), nullable=False),
            sa.Column("carrier_id", sa.String(32), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("gross_carrier_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("adjustments", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("net_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
            sa.Column("settlement_status", sa.String(32), nullable=False, server_default="created"),
            sa.Column("settlement_period", sa.String(32), nullable=True),
            sa.Column("remittance_reference", sa.String(64), nullable=True),
            sa.Column("remittance_text", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_nova_freight_settlements_settlement_id", "nova_freight_settlements", ["settlement_id"], unique=True)
        op.create_index("ix_nova_freight_settlements_payout_id", "nova_freight_settlements", ["payout_id"], unique=True)
        op.create_index("ix_nova_freight_settlements_carrier_id", "nova_freight_settlements", ["carrier_id"])
        op.create_index("ix_nova_freight_settlements_org_id", "nova_freight_settlements", ["organization_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    names = set(inspector.get_table_names())
    if "nova_freight_settlements" in names:
        op.drop_table("nova_freight_settlements")
    if "nova_freight_payouts" in names:
        op.drop_table("nova_freight_payouts")
