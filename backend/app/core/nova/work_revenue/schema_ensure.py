"""Additive Work & Revenue tables/columns. Does not alter payment, Health, or Lifesaver tables."""
from __future__ import annotations

import os

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.nova.work_revenue.models import (
    NovaWorkApplication,
    NovaWorkAuditEvent,
    NovaWorkBusinessFact,
    NovaWorkDeliverable,
    NovaWorkDisclosurePolicy,
    NovaWorkEngagement,
    NovaWorkHistoricalCorrection,
    NovaWorkInvoiceSupport,
    NovaWorkInput,
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
    NovaWorkInput.__table__,
    NovaWorkBusinessFact.__table__,
    NovaWorkDisclosurePolicy.__table__,
    NovaWorkPlatformPolicy.__table__,
    NovaWorkLiveActionAudit.__table__,
    NovaWorkSupervisedAction.__table__,
    NovaWorkSchedulerJob.__table__,
    NovaWorkPaymentEvent.__table__,
    NovaWorkHistoricalCorrection.__table__,
)

V2_TABLE_NAMES = frozenset(
    {
        "nova_work_live_action_audits",
        "nova_work_supervised_actions",
        "nova_work_scheduler_jobs",
        "nova_work_payment_events",
        "nova_work_historical_corrections",
    }
)
V2_TABLES = tuple(table for table in WORK_TABLES if table.name in V2_TABLE_NAMES)
V1_TABLES = tuple(table for table in WORK_TABLES if table.name not in V2_TABLE_NAMES)

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
        "idempotency_key": "VARCHAR(120)",
        "approval_ref": "VARCHAR(32)",
        "reason": "VARCHAR(400)",
        "source": "VARCHAR(80)",
    },
    "nova_work_revenue_entries": {
        "remaining_amount": "FLOAT",
    },
    "nova_work_supervised_actions": {
        "approval_status": "VARCHAR(24)",
        "approval_fingerprint": "VARCHAR(64)",
        "expires_at": "DATETIME",
        "consumed_at": "DATETIME",
        "revoked_at": "DATETIME",
        "rejected_at": "DATETIME",
    },
    "nova_work_payment_events": {
        "historical": "BOOLEAN",
    },
}


def _column_sql(sql_type: str, dialect: str) -> str:
    if dialect.startswith("postgres") and sql_type == "DATETIME":
        return "TIMESTAMPTZ"
    return sql_type


def _env_on(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def lazy_v2_schema_allowed() -> bool:
    """Production must not create V2 tables before owner-authorized Alembic.

    Pytest and explicit NOVA_WR_LAZY_V2_SCHEMA=1 remain the local/test path.
    Never set that override on Render.
    """
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    if _env_on("NOVA_WR_LAZY_V2_SCHEMA"):
        return True
    from app.core.nova.work_revenue.config import is_production_runtime

    return not is_production_runtime()


def v2_schema_ready(engine: Engine | None = None) -> bool:
    bind = engine or default_engine
    names = set(inspect(bind).get_table_names())
    return V2_TABLE_NAMES.issubset(names)


def ensure_work_revenue_schema(engine: Engine | None = None, *, include_v2: bool | None = None) -> None:
    bind = engine or default_engine
    create_v2 = lazy_v2_schema_allowed() if include_v2 is None else include_v2
    tables = list(WORK_TABLES) if create_v2 else list(V1_TABLES)
    Base.metadata.create_all(bind=bind, tables=tables)
    inspector = inspect(bind)
    names = set(inspector.get_table_names())
    dialect = str(getattr(bind.dialect, "name", "") or "")
    statements: list[str] = []
    for table_name, columns in _EXTRA_COLUMNS.items():
        if table_name not in names:
            continue
        if table_name in V2_TABLE_NAMES and not create_v2:
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
    with bind.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))
        if create_v2:
            _repair_v2_indexes(conn, dialect, inspect(bind))


def _repair_v2_indexes(conn, dialect: str, inspector) -> None:
    """Replace org-only V2 unique indexes with owner-scoped unique indexes."""
    names = set(inspector.get_table_names())
    repairs = (
        (
            "nova_work_supervised_actions",
            "ix_nova_work_sup_idem",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_nova_work_sup_idem ON nova_work_supervised_actions (organization_id, owner_user_id, idempotency_key)",
        ),
        (
            "nova_work_payment_events",
            "ix_nova_work_payevt_idem",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_nova_work_payevt_idem ON nova_work_payment_events (organization_id, owner_user_id, idempotency_key)",
        ),
        (
            "nova_work_scheduler_jobs",
            "ix_nova_work_sched_period",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_nova_work_sched_period ON nova_work_scheduler_jobs (organization_id, owner_user_id, job_kind, period_key)",
        ),
    )
    for table, index_name, create_sql in repairs:
        if table not in names:
            continue
        conn.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
        conn.execute(text(create_sql))
