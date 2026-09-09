"""Add missing Nova freight columns on existing SQLite files. No Health/Delivery tables."""
from __future__ import annotations

from sqlalchemy import inspect, text


def ensure_nova_freight_schema(engine) -> None:
    inspector = inspect(engine)
    if "nova_freight_shipments" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("nova_freight_shipments")}
    statements = []
    if "assigned_carrier_id" not in existing:
        statements.append("ALTER TABLE nova_freight_shipments ADD COLUMN assigned_carrier_id VARCHAR(32)")
    if "assigned_offer_id" not in existing:
        statements.append("ALTER TABLE nova_freight_shipments ADD COLUMN assigned_offer_id VARCHAR(32)")
    if not statements:
        return
    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))
