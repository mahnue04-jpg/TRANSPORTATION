"""Additive Growth Agent table ensure for local/test SQLite. No production DDL."""

from __future__ import annotations

import os

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.core.nova.growth_agent.models import GROWTH_AGENT_TABLES
from app.db.session import Base, engine as default_engine


def _production_locked() -> bool:
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        if os.getenv(name, "").strip().lower() in {"production", "prod"}:
            return True
    return False


def ensure_growth_agent_schema(bind: Engine | None = None) -> dict[str, object]:
    """Create missing Growth Agent tables. Skips when production-locked."""
    if _production_locked():
        return {"skipped": True, "reason": "production_schema_locked"}
    engine = bind or default_engine
    existing = set(inspect(engine).get_table_names())
    missing = [table for table in GROWTH_AGENT_TABLES if table.name not in existing]
    if missing:
        Base.metadata.create_all(bind=engine, tables=missing)
    return {
        "skipped": False,
        "created": [table.name for table in missing],
        "present": [table.name for table in GROWTH_AGENT_TABLES],
    }
