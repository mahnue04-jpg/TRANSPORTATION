"""Actual PostgreSQL recovery migration and claim tests, CI ephemeral only."""
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import os

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_recoverable_csv as recovery
from app.core.nova.work_revenue.operations_customer_csv_jobs import CustomerCSVBlocked


class FakePrivateStore:
    def __init__(self):
        self.items = {}
        self.n = 0

    def store(self, *, organization_id, application_id, category, filename,
              content_type, stream):
        self.n += 1
        ref = f"{organization_id}/{application_id}/{category}/{self.n}"
        value = stream.read()
        self.items[ref] = value
        return "fake-private", ref, len(value)

    def retrieve(self, *, storage_ref):
        return self.items[storage_ref], "text/csv"

    def delete(self, *, storage_ref):
        self.items.pop(storage_ref, None)


@pytest.fixture
def postgres(monkeypatch):
    url = os.getenv("NOVA_CSV_CI_DATABASE_URL", "")
    if "postgresql" not in url or "127.0.0.1" not in url:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail("Ephemeral loopback PostgreSQL is required in CI")
        pytest.skip("Ephemeral loopback PostgreSQL not configured")
    engine = sa.create_engine(url, pool_size=4, max_overflow=4)
    file = (Path(__file__).resolve().parents[1] / "migrations" / "versions"
            / "20261110_nova_csv_recovery_jobs.py")
    spec = spec_from_file_location("nova_recovery_migration_ci", file)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("NOVA_OPERATIONS_CSV_SCHEMA_APPROVED", "staging-only")
    with engine.begin() as connection:
        ctx = MigrationContext.configure(connection)
        monkeypatch.setattr(migration, "op", Operations(ctx))
        migration.upgrade()
    assert recovery.recovery_jobs.name in sa.inspect(engine).get_table_names()
    monkeypatch.setenv("NOVA_OPERATIONS_RECOVERABLE_CSV_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    store = FakePrivateStore()
    monkeypatch.setattr(recovery, "_store", lambda: store)
    yield engine, store
    recovery.metadata.drop_all(engine)
    engine.dispose()


def test_postgres_recovery_migration_queue_and_review(postgres):
    engine, store = postgres
    with Session(engine) as db:
        job = recovery.enqueue(
            db, org="org-a", owner="owner-a", engagement_id="eng-a",
            task_id="task-a", request_key="pg-recovery-1",
            raw=b"Name\nAda\nAda\n",
        )
        assert job["status"] == "QUEUED"
        result = recovery.process_job(
            db, org="org-a", owner="owner-a", job_id=job["job_id"],
            authorization_check=lambda eng, task: None,
        )
        assert result["status"] == "AWAITING_REVIEW"
        assert recovery.review_download(
            db, org="org-a", owner="owner-a", job_id=job["job_id"],
        ) == b"Name\nAda\n"
        with pytest.raises(CustomerCSVBlocked) as denied:
            recovery.status(db, org="org-b", owner="owner-a", job_id=job["job_id"])
        assert denied.value.code == 404
        assert len(store.items) == 2


def test_postgres_fences_expired_worker(postgres):
    engine, _ = postgres
    with Session(engine) as db:
        job = recovery.enqueue(
            db, org="org-a", owner="owner-a", engagement_id="eng-a",
            task_id="task-a", request_key="pg-recovery-lease",
            raw=b"Name\nAda\n",
        )
        t0 = datetime.now(timezone.utc)
        a = recovery.claim(db, org="org-a", owner="owner-a",
                           job_id=job["job_id"], now=t0, lease_seconds=60)
        b = recovery.claim(db, org="org-a", owner="owner-a",
                           job_id=job["job_id"], now=t0 + timedelta(seconds=61),
                           lease_seconds=60)
        with pytest.raises(CustomerCSVBlocked, match="Stale worker"):
            recovery.complete(
                db, org="org-a", owner="owner-a", job_id=job["job_id"],
                token=a["token"], output_ref="old", output_sha256="a" * 64,
                now=t0 + timedelta(seconds=62),
            )
        recovery.complete(
            db, org="org-a", owner="owner-a", job_id=job["job_id"],
            token=b["token"], output_ref="new", output_sha256="b" * 64,
            now=t0 + timedelta(seconds=62),
        )
        assert recovery.status(
            db, org="org-a", owner="owner-a", job_id=job["job_id"],
        )["status"] == "AWAITING_REVIEW"


def test_postgres_two_connections_cannot_claim_same_active_lease(postgres):
    """Separate DB sessions must never both obtain a valid claim."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    engine, _ = postgres
    with Session(engine) as db:
        job_id = recovery.enqueue(
            db, org="org-a", owner="owner-a",
            engagement_id="eng-a", task_id="task-a",
            request_key="concurrent-pg-claim", raw=b"Name\nAda\n",
        )["job_id"]
    gate = Barrier(2)
    timestamp = datetime.now(timezone.utc)

    def take_claim():
        with Session(engine) as session:
            gate.wait(timeout=10)
            try:
                return recovery.claim(
                    session, org="org-a", owner="owner-a",
                    job_id=job_id, now=timestamp, lease_seconds=60,
                )["token"]
            except CustomerCSVBlocked as exc:
                assert exc.code == 409
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(lambda _: take_claim(), range(2)))
    assert sum(token is not None for token in tokens) == 1
    with Session(engine) as db:
        row = recovery.status(db, org="org-a", owner="owner-a", job_id=job_id)
        assert row["status"] == "RUNNING"
        assert row["attempts"] == 1
