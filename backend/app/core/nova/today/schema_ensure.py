"""Add missing Nova V2 Today columns/tables on existing databases. No V1/Health/Delivery tables."""
from __future__ import annotations

from sqlalchemy import inspect, text


def snooze_column_sql(dialect_name: str) -> str:
    """Postgres rejects SQLite DATETIME. Use an additive nullable timestamp only."""
    if str(dialect_name or "").startswith("postgres"):
        return (
            "ALTER TABLE nova_v2_command_actions "
            "ADD COLUMN IF NOT EXISTS snoozed_until TIMESTAMPTZ"
        )
    return "ALTER TABLE nova_v2_command_actions ADD COLUMN snoozed_until DATETIME"


def ensure_nova_today_schema(engine) -> None:
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    if "nova_v2_command_actions" in names:
        existing = {col["name"] for col in inspector.get_columns("nova_v2_command_actions")}
        if "snoozed_until" not in existing:
            with engine.begin() as conn:
                conn.execute(text(snooze_column_sql(engine.dialect.name)))
    if "nova_v2_recheck_events" not in names:
        from app.core.nova.today.models import NovaV2RecheckEvent

        NovaV2RecheckEvent.__table__.create(bind=engine, checkfirst=True)
