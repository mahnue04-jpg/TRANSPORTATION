"""Add missing Nova freight columns on existing SQLite files. No Health/Delivery tables."""
from __future__ import annotations

from sqlalchemy import inspect, text


def ensure_nova_freight_schema(engine) -> None:
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    if "nova_freight_shipments" not in names:
        return
    existing = {col["name"] for col in inspector.get_columns("nova_freight_shipments")}
    statements = []
    if "assigned_carrier_id" not in existing:
        statements.append("ALTER TABLE nova_freight_shipments ADD COLUMN assigned_carrier_id VARCHAR(32)")
    if "assigned_offer_id" not in existing:
        statements.append("ALTER TABLE nova_freight_shipments ADD COLUMN assigned_offer_id VARCHAR(32)")
    if "last_status_at" not in existing:
        statements.append("ALTER TABLE nova_freight_shipments ADD COLUMN last_status_at DATETIME")
    if "nova_freight_shipment_events" in names:
        event_cols = {col["name"] for col in inspector.get_columns("nova_freight_shipment_events")}
        if "proof_id" not in event_cols:
            statements.append("ALTER TABLE nova_freight_shipment_events ADD COLUMN proof_id VARCHAR(32)")
        if "quote_id" not in event_cols:
            statements.append("ALTER TABLE nova_freight_shipment_events ADD COLUMN quote_id VARCHAR(32)")
        if "invoice_id" not in event_cols:
            statements.append("ALTER TABLE nova_freight_shipment_events ADD COLUMN invoice_id VARCHAR(32)")
        if "payout_id" not in event_cols:
            statements.append("ALTER TABLE nova_freight_shipment_events ADD COLUMN payout_id VARCHAR(32)")
        if "settlement_id" not in event_cols:
            statements.append("ALTER TABLE nova_freight_shipment_events ADD COLUMN settlement_id VARCHAR(32)")
    if not statements:
        return
    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))
