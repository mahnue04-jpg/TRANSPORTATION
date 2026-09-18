"""Additive Work & Revenue tables/columns. Does not alter payment, Health, or Lifesaver tables."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.nova.work_revenue.models import (
    NovaWorkApplication,
    NovaWorkAuditEvent,
    NovaWorkBusinessFact,
    NovaWorkDeliverable,
    NovaWorkDisclosurePolicy,
    NovaWorkEngagement,
    NovaWorkInvoiceSupport,
    NovaWorkLiveActionAudit,
    NovaWorkMaterial,
    NovaWorkOpportunity,
    NovaWorkOwnerAction,
    NovaWorkPaymentEvent,
    NovaWorkPlatformPolicy,
    NovaWorkRecurringOccurrence,
    NovaWorkRecurringSeries,
    NovaWorkRevenueEntry,
    NovaWorkSchedulerJob,
    NovaWorkStatusHistory,
    NovaWorkSupervisedAction,
    NovaWorkTask,
    NovaWorkWeeklyReport,
)
from app.db.session import Base, engine as default_engine

WORK_TABLES = (
    NovaWorkOpportunity.__table__,
    NovaWorkApplication.__table__,
    NovaWorkMaterial.__table__,
    NovaWorkOwnerAction.__table__,
    NovaWorkStatusHistory.__table__,
    NovaWorkAuditEvent.__table__,
    NovaWorkEngagement.__table__,
    NovaWorkTask.__table__,
    NovaWorkDeliverable.__table__,
    NovaWorkRevenueEntry.__table__,
    NovaWorkRecurringSeries.__table__,
    NovaWorkRecurringOccurrence.__table__,
    NovaWorkWeeklyReport.__table__,
    NovaWorkInvoiceSupport.__table__,
    NovaWorkBusinessFact.__table__,
    NovaWorkDisclosurePolicy.__table__,
    NovaWorkPlatformPolicy.__table__,
    NovaWorkLiveActionAudit.__table__,
    NovaWorkSupervisedAction.__table__,
    NovaWorkSchedulerJob.__table__,
    NovaWorkPaymentEvent.__table__,
)

_EXTRA_COLUMNS: dict[str, dict[str, str]] = {
    "nova_work_opportunities": {
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
        "invoice_value": "FLOAT",
        "amount_received": "FLOAT",
        "expenses": "FLOAT",
        "estimated_net": "FLOAT",
        "confirmed_net": "FLOAT",
        "payment_status": "VARCHAR(40)",
        "category": "VARCHAR(40)",
        "priority": "VARCHAR(16)",
        "tags_json": "TEXT",
        "blocked_reason": "TEXT",
        "archive_reason": "TEXT",
        "qualification_reason": "TEXT",
    },
    "nova_work_applications": {
        "owner_notes": "TEXT",
        "decided_at": "DATETIME",
        "expires_at": "DATETIME",
    },
    "nova_work_materials": {
        "revision": "INTEGER",
        "parent_material_id": "VARCHAR(32)",
    },
    "nova_work_owner_actions": {
        "category": "VARCHAR(48)",
        "owner_notes": "TEXT",
        "engagement_id": "VARCHAR(32)",
        "ref_type": "VARCHAR(32)",
        "ref_id": "VARCHAR(32)",
    },
    "nova_work_engagements": {
        "title": "VARCHAR(220)",
        "service_type": "VARCHAR(80)",
        "agreed_value": "FLOAT",
        "estimated_revenue": "FLOAT",
        "quoted_revenue": "FLOAT",
        "contracted_revenue": "FLOAT",
        "received_revenue": "FLOAT",
        "risks": "TEXT",
        "blockers": "TEXT",
        "priority": "VARCHAR(16)",
        "source": "VARCHAR(80)",
        "due_date": "DATETIME",
    },
    "nova_work_tasks": {
        "description": "TEXT",
        "depends_on_task_id": "VARCHAR(32)",
        "blocked_reason": "TEXT",
        "completed_at": "DATETIME",
        "owner_notes": "TEXT",
    },
    "nova_work_audit_events": {
        "actor_category": "VARCHAR(24)",
        "entity_type": "VARCHAR(32)",
        "previous_state": "VARCHAR(40)",
        "new_state": "VARCHAR(40)",
    },
    "nova_work_revenue_entries": {
        "remaining_amount": "FLOAT",
    },
}


def _column_sql(sql_type: str, dialect: str) -> str:
    if dialect.startswith("postgres") and sql_type == "DATETIME":
        return "TIMESTAMPTZ"
    return sql_type


def ensure_work_revenue_schema(engine: Engine | None = None) -> None:
    bind = engine or default_engine
    Base.metadata.create_all(bind=bind, tables=list(WORK_TABLES))
    inspector = inspect(bind)
    names = set(inspector.get_table_names())
    dialect = str(getattr(bind.dialect, "name", "") or "")
    statements: list[str] = []
    for table_name, columns in _EXTRA_COLUMNS.items():
        if table_name not in names:
            continue
        existing = {col["name"] for col in inspector.get_columns(table_name)}
        for name, sql_type in columns.items():
            if name in existing:
                continue
            col_type = _column_sql(sql_type, dialect)
            if dialect.startswith("postgres"):
                statements.append(
                    f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {name} {col_type}"
                )
            else:
                statements.append(f"ALTER TABLE {table_name} ADD COLUMN {name} {col_type}")
    if not statements:
        return
    with bind.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))
