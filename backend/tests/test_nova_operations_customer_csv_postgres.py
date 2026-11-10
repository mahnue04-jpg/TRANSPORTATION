"""PostgreSQL-specific customer CSV integration checks (CI ephemeral DB only).

Requires NOVA_CSV_CI_DATABASE_URL explicitly targeting an ephemeral PostgreSQL
instance. This suite never reads an app/production DATABASE_URL and never uses
real object storage or customer data.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import os

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_customer_csv_jobs as csvjobs


class FakePrivateStore:
    def __init__(self):
        self.items = {}
        self.put_count = 0

    def store(self, *, organization_id, application_id, category, filename,
              content_type, stream):
        self.put_count += 1
        key = f"{organization_id}/{application_id}/{category}/{filename}"
        value = stream.read()
        self.items[key] = value
        return "private-test", key, len(value)

    def retrieve(self, *, storage_ref):
        return self.items[storage_ref], "text/csv"

    def delete(self, *, storage_ref):
        self.items.pop(storage_ref, None)


@pytest.fixture
def postgres(monkeypatch):
    url = os.getenv("NOVA_CSV_CI_DATABASE_URL", "")
    if not url or "127.0.0.1" not in url or "postgresql" not in url:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail("CI must provide an isolated loopback PostgreSQL service")
        pytest.skip("explicit loopback ephemeral PostgreSQL required")
    engine = sa.create_engine(url, pool_size=5, max_overflow=5)
    assert engine.dialect.name == "postgresql"
    migration_file = (
        Path(__file__).resolve().parents[1] / "migrations" / "versions"
        / "20261109_nova_operations_csv_jobs.py"
    )
    spec = spec_from_file_location("nova_csv_pg_migration_ci", migration_file)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("NOVA_OPERATIONS_CSV_SCHEMA_APPROVED", "staging-only")
    # Run the ACTUAL Alembic revision against disposable PostgreSQL.
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        monkeypatch.setattr(migration, "op", Operations(context))
        migration.upgrade()
    inspector = sa.inspect(engine)
    assert csvjobs.jobs.name in inspector.get_table_names()
    assert "uq_nova_customer_csv_request" in {
        c["name"] for c in inspector.get_unique_constraints(csvjobs.jobs.name)
    }
    assert "ix_nova_customer_csv_owned" in {
        ix["name"] for ix in inspector.get_indexes(csvjobs.jobs.name)
    }
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_CSV_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    store = FakePrivateStore()
    monkeypatch.setattr(csvjobs, "_store", lambda: store)
    yield engine, store
    csvjobs.metadata.drop_all(engine)
    engine.dispose()


def _submit(engine, request_key, raw=b"Name\nAda\nAda\n"):
    with Session(engine) as db:
        return csvjobs.submit_review_job(
            db, org="synthetic-org", owner="synthetic-owner",
            engagement_id="synthetic-eng", task_id="synthetic-csv-task",
            request_key=request_key, raw=raw,
        )


def test_postgres_real_runtime_and_private_review_round_trip(postgres):
    engine, store = postgres
    created = _submit(engine, "pg-create")
    assert created["status"] == "AWAITING_REVIEW"
    with Session(engine) as db:
        assert csvjobs.job_status(
            db, org="synthetic-org", owner="synthetic-owner",
            job_id=created["job_id"],
        )["status"] == "AWAITING_REVIEW"
        assert csvjobs.download_review(
            db, org="synthetic-org", owner="synthetic-owner",
            job_id=created["job_id"],
        ) == b"Name\nAda\n"
        with pytest.raises(csvjobs.CustomerCSVBlocked) as denied:
            csvjobs.download_review(
                db, org="synthetic-org", owner="another-owner",
                job_id=created["job_id"],
            )
        assert denied.value.code == 404
        reviewed = csvjobs.review_job(
            db, org="synthetic-org", owner="synthetic-owner",
            job_id=created["job_id"], approve=True,
        )
        assert reviewed["status"] == "APPROVED_FOR_DOWNLOAD"
    assert len(store.items) == 1


def test_postgres_two_connection_idempotency_and_scope(postgres):
    engine, store = postgres
    first = _submit(engine, "pg-duplicate")
    replay = _submit(engine, "pg-duplicate")
    assert replay["job_id"] == first["job_id"]
    assert replay["replayed"] is True
    assert store.put_count == 1
    with pytest.raises(csvjobs.CustomerCSVBlocked, match="different work"):
        _submit(engine, "pg-duplicate", b"Name\nDifferent\n")
    with Session(engine) as db:
        count = db.execute(sa.select(sa.func.count()).select_from(csvjobs.jobs)).scalar_one()
        assert count == 1


def test_postgres_concurrent_duplicate_key_creates_one_artifact(postgres):
    engine, store = postgres
    gate = Barrier(2)
    def send():
        gate.wait(timeout=10)
        return _submit(engine, "pg-race")
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(send)
        b = pool.submit(send)
        results = [a.result(timeout=20), b.result(timeout=20)]
    assert results[0]["job_id"] == results[1]["job_id"]
    assert sorted(v["replayed"] for v in results) == [False, True]
    assert store.put_count == 1
    with Session(engine) as db:
        count = db.execute(sa.select(sa.func.count()).select_from(csvjobs.jobs)).scalar_one()
        assert count == 1
