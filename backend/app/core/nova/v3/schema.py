"""Canonical V3 schema registry. Alembic is the production path. No lazy prod create."""
from __future__ import annotations

import os

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.core.nova.v3.db_models import APPEND_ONLY_TABLES, V3_MODEL_BY_TABLE, V3_ORM_TABLES, V3_TABLES
from app.core.nova.v3.errors import V3Error
from app.db.session import Base

_FORBIDDEN = ("DROP TABLE", "DROP COLUMN", "TRUNCATE", "STRIPE")
REVISION = "20260918_nova_v3_live_infra"
DOWN_REVISION = "20260918_work_rev_owner_sched"


def live_flags_hard_off_names() -> tuple[str, ...]:
    return (
        "LIVE_LEAD_DISCOVERY",
        "REAL_OUTREACH_SEND",
        "REAL_EMAIL_SEND",
        "REAL_SMS_SEND",
        "REAL_SOCIAL_POST",
        "REAL_AD_SPEND",
        "REAL_CALENDAR_WRITE",
        "REAL_CLIENT_CONTACT",
        "REAL_PROPOSAL_SEND",
        "REAL_CONTRACT_ACCEPTANCE",
        "REAL_PAYMENT_EXECUTION",
        "REAL_BACKGROUND_WORKER",
        "REAL_CONNECTORS",
        "REAL_WEBHOOK_PUBLIC_ENDPOINT",
    )


def assert_additive_sql(sql: str) -> None:
    upper = sql.upper()
    for token in _FORBIDDEN:
        if token in upper:
            raise V3Error("UNSAFE_DDL", f"forbidden SQL token {token}")


def assert_store_url(url: str) -> str:
    token = (url or "").strip().lower()
    if any(word in token for word in ("stripe", "sk_live", "whsec")):
        raise V3Error("PERSISTENCE_REFUSED", "Stripe/production secret URLs are forbidden")
    return url


def lazy_v3_schema_allowed() -> bool:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    if (os.getenv("NOVA_V3_LAZY_SCHEMA") or "").strip() == "1":
        return True
    try:
        from app.core.nova.work_revenue.config import is_production_runtime

        return not is_production_runtime()
    except Exception:
        env = (os.getenv("AMICOR_ENVIRONMENT") or os.getenv("RUNTIME_ENVIRONMENT") or os.getenv("APP_ENV") or "").lower()
        return env not in {"production", "prod"}


def v3_schema_ready(engine: Engine) -> bool:
    names = set(inspect(engine).get_table_names())
    return set(V3_TABLES).issubset(names)


def ensure_v3_schema(engine: Engine) -> None:
    assert_store_url(str(engine.url))
    if v3_schema_ready(engine):
        return
    if not lazy_v3_schema_allowed():
        raise V3Error(
            "SCHEMA_MIGRATION_REQUIRED",
            "V3 tables are missing. Apply Alembic revision 20260918_nova_v3_live_infra.",
            http_status=503,
        )
    Base.metadata.create_all(bind=engine, tables=list(V3_ORM_TABLES))


def rollback_plan() -> dict[str, str]:
    return {
        "strategy": "leave nova_v3_* tables in place in production; keep live flags off; local downgrade drops only nova_v3_*",
        "local_test": "alembic upgrade/downgrade against an isolated sqlite or local database",
        "alembic": f"{REVISION} revises canonical V2 head {DOWN_REVISION}",
        "production_apply": "not applied; Render Auto-Deploy remains off",
        "future_alembic": f"canonical revision {REVISION} chained after {DOWN_REVISION}",
    }


__all__ = [
    "APPEND_ONLY_TABLES",
    "DOWN_REVISION",
    "REVISION",
    "V3_MODEL_BY_TABLE",
    "V3_ORM_TABLES",
    "V3_TABLES",
    "assert_additive_sql",
    "assert_store_url",
    "ensure_v3_schema",
    "lazy_v3_schema_allowed",
    "live_flags_hard_off_names",
    "rollback_plan",
    "v3_schema_ready",
]
