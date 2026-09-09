"""Add missing Nova V2 Today columns on existing databases. No V1/Health/Delivery tables."""
from __future__ import annotations

from sqlalchemy import inspect, text


def ensure_nova_today_schema(engine) -> None:
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    if "nova_v2_command_actions" not in names:
        return
    existing = {col["name"] for col in inspector.get_columns("nova_v2_command_actions")}
    statements = []
    if "snoozed_until" not in existing:
        statements.append("ALTER TABLE nova_v2_command_actions ADD COLUMN snoozed_until DATETIME")
    if not statements:
        return
    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))
