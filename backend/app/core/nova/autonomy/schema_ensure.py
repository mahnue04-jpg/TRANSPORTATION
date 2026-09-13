"""Additive Autonomy schema ensure. Creates Phase 2A tables and ledger columns only."""
from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.nova.autonomy.models import (
    NovaAutonomyApproval,
    NovaAutonomyExecutionAttempt,
    NovaAutonomyLedger,
    NovaAutonomyOrgFlag,
    NovaAutonomyWorkflow,
    NovaAutonomyWorkflowStep,
)

_LEDGER_COLUMNS = (
    ("workflow_id", "VARCHAR(32)", "VARCHAR(32)"),
    ("step_id", "VARCHAR(32)", "VARCHAR(32)"),
    ("target_module", "VARCHAR(40)", "VARCHAR(40)"),
    ("approver_user_id", "VARCHAR(36)", "VARCHAR(36)"),
    ("attempt_number", "INTEGER", "INTEGER"),
)
_PHASE2_TABLES = (
    NovaAutonomyWorkflow,
    NovaAutonomyWorkflowStep,
    NovaAutonomyApproval,
    NovaAutonomyExecutionAttempt,
    NovaAutonomyOrgFlag,
)


def _add_ledger_column_sql(dialect_name: str, column: str, sqlite_type: str, postgres_type: str) -> str:
    if str(dialect_name or "").startswith("postgres"):
        return (
            f"ALTER TABLE nova_autonomy_ledger "
            f"ADD COLUMN IF NOT EXISTS {column} {postgres_type}"
        )
    return f"ALTER TABLE nova_autonomy_ledger ADD COLUMN {column} {sqlite_type}"


def ensure_autonomy_schema(engine) -> None:
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    if "nova_autonomy_ledger" not in names:
        NovaAutonomyLedger.__table__.create(bind=engine, checkfirst=True)
        inspector = inspect(engine)
        names = set(inspector.get_table_names())
    if "nova_autonomy_ledger" in names:
        existing = {col["name"] for col in inspector.get_columns("nova_autonomy_ledger")}
        statements = []
        for column, sqlite_type, postgres_type in _LEDGER_COLUMNS:
            if column not in existing:
                statements.append(
                    _add_ledger_column_sql(engine.dialect.name, column, sqlite_type, postgres_type)
                )
        if statements:
            with engine.begin() as conn:
                for sql in statements:
                    conn.execute(text(sql))
    for model in _PHASE2_TABLES:
        if model.__tablename__ not in names:
            model.__table__.create(bind=engine, checkfirst=True)
