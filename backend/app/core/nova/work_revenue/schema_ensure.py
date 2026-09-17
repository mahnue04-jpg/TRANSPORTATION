"""Additive Work & Revenue tables/columns. Does not alter payment, Health, or Lifesaver tables."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.nova.work_revenue.models import (
    NovaWorkApplication,
    NovaWorkAuditEvent,
    NovaWorkMaterial,
    NovaWorkOpportunity,
    NovaWorkOwnerAction,
    NovaWorkStatusHistory,
)
from app.db.session import Base, engine as default_engine

WORK_TABLES = (
    NovaWorkOpportunity.__table__,
    NovaWorkApplication.__table__,
    NovaWorkMaterial.__table__,
    NovaWorkOwnerAction.__table__,
    NovaWorkStatusHistory.__table__,
    NovaWorkAuditEvent.__table__,
)

_OPP_COLUMNS = {
    "fingerprint": "VARCHAR(80)",
    "estimated_value": "FLOAT",
    "quoted_amount": "FLOAT",
    "contract_amount": "FLOAT",
    "expected_payment_frequency": "VARCHAR(40)",
    "expected_start_date": "DATETIME",
    "expected_end_date": "DATETIME",
    "revenue_status": "VARCHAR(40)",
    "invoice_required": "BOOLEAN",
    "owner_confirmed_payment_received": "BOOLEAN",
    "archived": "BOOLEAN",
}


def ensure_work_revenue_schema(engine: Engine | None = None) -> None:
    bind = engine or default_engine
    Base.metadata.create_all(bind=bind, tables=list(WORK_TABLES))
    inspector = inspect(bind)
    names = set(inspector.get_table_names())
    if "nova_work_opportunities" not in names:
        return
    existing = {col["name"] for col in inspector.get_columns("nova_work_opportunities")}
    dialect = str(getattr(bind.dialect, "name", "") or "")
    statements = []
    for name, sql_type in _OPP_COLUMNS.items():
        if name in existing:
            continue
        col_type = sql_type
        if dialect.startswith("postgres"):
            if sql_type == "DATETIME":
                col_type = "TIMESTAMPTZ"
            statements.append(
                f"ALTER TABLE nova_work_opportunities ADD COLUMN IF NOT EXISTS {name} {col_type}"
            )
        else:
            statements.append(f"ALTER TABLE nova_work_opportunities ADD COLUMN {name} {col_type}")
    if not statements:
        return
    with bind.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))
