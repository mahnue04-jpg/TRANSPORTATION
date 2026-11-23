"""Rehearse the observed production Growth worker-schema gap on disposable CI PostgreSQL.

No Render credentials, production connections, live data, or Alembic stamp.
Uses a temporary PostgreSQL schema that is destroyed after this test.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _worker_revision():
    path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "20261112_nova_growth_agent_worker.py"
    spec = importlib.util.spec_from_file_location("growth_worker_rehearsal", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _safe_url():
    url = os.getenv("NOVA_GA_PG_TEST_URL", "")
    parsed = urlparse(url)
    if parsed.hostname not in {"localhost", "127.0.0.1"} or parsed.port != 5432:
        raise RuntimeError("Disposable rehearsal accepts localhost PostgreSQL only")
    if parsed.path != "/nova_ga_ci_dispos":
        raise RuntimeError("Disposable rehearsal requires exact CI database")
    if not parsed.scheme.startswith("postgresql"):
        raise RuntimeError("Disposable rehearsal requires PostgreSQL")
    return url


def test_repair_missing_worker_columns_only_in_isolated_schema(monkeypatch):
    url = _safe_url()
    schema = "growth_rehearsal_" + uuid4().hex[:12]
    admin = sa.create_engine(url)
    # The schema and all contents are synthetic. Never use public or live schemas.
    try:
        with admin.begin() as conn:
            conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        engine = sa.create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        try:
            with engine.begin() as conn:
                conn.execute(sa.text(
                    "CREATE TABLE nova_ga_delivery_attempts "
                    "(id VARCHAR(36) PRIMARY KEY, attempt_number INTEGER NOT NULL)"
                ))
                conn.execute(sa.text(
                    "INSERT INTO nova_ga_delivery_attempts (id, attempt_number) "
                    "VALUES ('synthetic-one', 2)"
                ))
            monkeypatch.setenv("APP_ENV", "test")
            monkeypatch.setenv("AMICOR_ENVIRONMENT", "test")
            monkeypatch.delenv("ENVIRONMENT", raising=False)
            revision = _worker_revision()
            with engine.begin() as conn:
                revision.op = Operations(MigrationContext.configure(conn))
                revision.upgrade()
                revision.upgrade()  # idempotence: no duplicate columns
            inspector = sa.inspect(engine)
            columns = {c["name"]: c for c in inspector.get_columns("nova_ga_delivery_attempts")}
            expected = {"max_attempts", "claimed_by", "claimed_at",
                        "lease_expires_at", "available_at"}
            assert expected <= set(columns)
            assert columns["max_attempts"]["nullable"] is False
            assert isinstance(columns["max_attempts"]["type"], sa.Integer)
            for col in ("claimed_by", "claimed_at", "lease_expires_at", "available_at"):
                assert columns[col]["nullable"] is True
            assert {"nova_ga_rate_limit_counters", "nova_ga_worker_heartbeats"} <= set(inspector.get_table_names())
            with engine.connect() as conn:
                row = conn.execute(sa.text(
                    "SELECT attempt_number, max_attempts, claimed_by "
                    "FROM nova_ga_delivery_attempts WHERE id='synthetic-one'"
                )).one()
            assert tuple(row) == (2, 5, None)

            # Production locks prevent even an otherwise idempotent rerun.
            monkeypatch.setenv("APP_ENV", "production")
            with engine.begin() as conn:
                revision.op = Operations(MigrationContext.configure(conn))
                with pytest.raises(RuntimeError, match="blocked in production"):
                    revision.upgrade()
        finally:
            engine.dispose()
    finally:
        try:
            with admin.begin() as conn:
                conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            admin.dispose()
