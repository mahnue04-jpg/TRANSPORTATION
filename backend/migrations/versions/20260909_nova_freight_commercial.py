"""Nova freight quotes, invoices, and TEST payment events.

Revision ID: 20260909_nova_freight_commercial
Revises: 20260909_nova_freight_proofs
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260909_nova_freight_commercial"
down_revision = "20260909_nova_freight_proofs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    names = set(inspector.get_table_names())
    if "nova_freight_shipment_events" in names:
        existing = {col["name"] for col in inspector.get_columns("nova_freight_shipment_events")}
        if "quote_id" not in existing:
            op.add_column("nova_freight_shipment_events", sa.Column("quote_id", sa.String(32), nullable=True))
        if "invoice_id" not in existing:
            op.add_column("nova_freight_shipment_events", sa.Column("invoice_id", sa.String(32), nullable=True))
    if "nova_freight_quotes" not in names:
        op.create_table(
            "nova_freight_quotes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("quote_id", sa.String(32), nullable=False),
            sa.Column("shipment_id", sa.String(32), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("pricing_status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("pricing_method", sa.String(32), nullable=False, server_default="rate_engine"),
            sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
            sa.Column("estimated_miles", sa.Numeric(12, 2), nullable=True),
            sa.Column("estimated_hours", sa.Numeric(12, 2), nullable=True),
            sa.Column("base_rate", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("mileage_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("time_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("equipment_surcharge", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("special_handling_surcharge", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("fuel_surcharge", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("other_surcharge", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("suggested_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("quoted_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("total_customer_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("estimated_carrier_cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("estimated_amicor_margin", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("quote_notes", sa.Text(), nullable=True),
            sa.Column("customer_notes", sa.Text(), nullable=True),
            sa.Column("quoted_by_user_id", sa.String(36), nullable=True),
            sa.Column("quoted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finalized_by_user_id", sa.String(36), nullable=True),
            sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_adjusted_by_user_id", sa.String(36), nullable=True),
            sa.Column("last_adjusted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_nova_freight_quotes_quote_id", "nova_freight_quotes", ["quote_id"], unique=True)
        op.create_index("ix_nova_freight_quotes_shipment_id", "nova_freight_quotes", ["shipment_id"], unique=True)
        op.create_index("ix_nova_freight_quotes_org_id", "nova_freight_quotes", ["organization_id"])
    if "nova_freight_invoices" not in names:
        op.create_table(
            "nova_freight_invoices",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("invoice_id", sa.String(32), nullable=False),
            sa.Column("shipment_id", sa.String(32), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("quote_id", sa.String(32), nullable=True),
            sa.Column("customer_user_id", sa.String(36), nullable=True),
            sa.Column("amount_subtotal", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("surcharge_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("discount_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("tax_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("total_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("total_amount_minor", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
            sa.Column("invoice_status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("stripe_payment_intent_id", sa.String(128), nullable=True),
            sa.Column("stripe_checkout_session_id", sa.String(128), nullable=True),
            sa.Column("idempotency_key", sa.String(80), nullable=False),
            sa.Column("failure_reason", sa.String(512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_nova_freight_invoices_invoice_id", "nova_freight_invoices", ["invoice_id"], unique=True)
        op.create_index("ix_nova_freight_invoices_shipment_id", "nova_freight_invoices", ["shipment_id"])
        op.create_index("ix_nova_freight_invoices_org_id", "nova_freight_invoices", ["organization_id"])
        op.create_index("ix_nova_freight_invoices_idem", "nova_freight_invoices", ["idempotency_key"], unique=True)
        op.create_index("ix_nova_freight_invoices_pi", "nova_freight_invoices", ["stripe_payment_intent_id"])
    if "nova_freight_payment_events" not in names:
        op.create_table(
            "nova_freight_payment_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("stripe_event_id", sa.String(128), nullable=False),
            sa.Column("stripe_payment_intent_id", sa.String(128), nullable=True),
            sa.Column("invoice_id", sa.String(32), nullable=True),
            sa.Column("shipment_id", sa.String(32), nullable=True),
            sa.Column("organization_id", sa.String(36), nullable=True),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column("processing_result", sa.String(64), nullable=False),
            sa.Column("amount_minor", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_nova_freight_pay_events_event", "nova_freight_payment_events", ["stripe_event_id"], unique=True)
        op.create_index("ix_nova_freight_pay_events_invoice", "nova_freight_payment_events", ["invoice_id"])
        op.create_index("ix_nova_freight_pay_events_pi", "nova_freight_payment_events", ["stripe_payment_intent_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    names = set(inspector.get_table_names())
    if "nova_freight_payment_events" in names:
        op.drop_table("nova_freight_payment_events")
    if "nova_freight_invoices" in names:
        op.drop_table("nova_freight_invoices")
    if "nova_freight_quotes" in names:
        op.drop_table("nova_freight_quotes")
