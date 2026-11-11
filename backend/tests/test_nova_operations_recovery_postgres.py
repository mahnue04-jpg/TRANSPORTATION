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
        cleanup_file = (
            Path(__file__).resolve().parents[1] / "migrations" / "versions"
            / "20261110_nova_csv_cleanup_events.py"
        )
        cleanup_spec = spec_from_file_location("nova_cleanup_migration_ci", cleanup_file)
        cleanup_migration = module_from_spec(cleanup_spec)
        cleanup_spec.loader.exec_module(cleanup_migration)
        monkeypatch.setattr(cleanup_migration, "op", Operations(ctx))
        cleanup_migration.upgrade()
    assert recovery.recovery_jobs.name in sa.inspect(engine).get_table_names()
    assert recovery.cleanup_events.name in sa.inspect(engine).get_table_names()
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


def test_postgres_bounded_worker_pass_recovers_queue(postgres):
    engine, store = postgres
    with Session(engine) as db:
        first = recovery.enqueue(
            db, org="org-a", owner="owner-a", engagement_id="eng-a",
            task_id="task-a", request_key="pg-batch-one", raw=b"Name\nAda\n",
        )
        second = recovery.enqueue(
            db, org="org-a", owner="owner-a", engagement_id="eng-a",
            task_id="task-a", request_key="pg-batch-two", raw=b"Name\nBea\n",
        )
        result = recovery.run_due_jobs(
            db, org="org-a", owner="owner-a", limit=1,
            authorization_check=lambda eng, task: None,
        )
        assert result["attempted"] == 1
        assert result["delivered"] is False
        pending = recovery.due_job_ids(db, org="org-a", owner="owner-a")
        assert len(pending) == 1
        assert pending[0] in {first["job_id"], second["job_id"]}
        second_pass = recovery.run_due_jobs(
            db, org="org-a", owner="owner-a", limit=2,
            authorization_check=lambda eng, task: None,
        )
        assert second_pass["attempted"] == 1
        assert recovery.due_job_ids(db, org="org-a", owner="owner-a") == []
        assert len(store.items) == 4


def test_postgres_fenced_lease_renewal_and_restart_claim(postgres):
    engine, _ = postgres
    with Session(engine) as db:
        job_id = recovery.enqueue(
            db, org="org-a", owner="owner-a", engagement_id="eng-a",
            task_id="task-a", request_key="pg-lease-heartbeat",
            raw=b"Name\nAda\n",
        )["job_id"]
        stamp = datetime.now(timezone.utc)
        original = recovery.claim(
            db, org="org-a", owner="owner-a",
            job_id=job_id, now=stamp, lease_seconds=60,
        )
        renewed_until = recovery.renew_lease(
            db, org="org-a", owner="owner-a", job_id=job_id,
            token=original["token"],
            now=stamp + timedelta(seconds=30), lease_seconds=90,
        )
        assert renewed_until == stamp + timedelta(seconds=120)
        with pytest.raises(CustomerCSVBlocked):
            recovery.claim(
                db, org="org-a", owner="owner-a", job_id=job_id,
                now=stamp + timedelta(seconds=65),
            )
        replacement = recovery.claim(
            db, org="org-a", owner="owner-a", job_id=job_id,
            now=stamp + timedelta(seconds=121),
        )
        with pytest.raises(CustomerCSVBlocked, match="Cannot renew"):
            recovery.renew_lease(
                db, org="org-a", owner="owner-a", job_id=job_id,
                token=original["token"], now=stamp + timedelta(seconds=122),
            )
        recovery.complete(
            db, org="org-a", owner="owner-a", job_id=job_id,
            token=replacement["token"], output_ref="private-stage-output",
            output_sha256="f" * 64, now=stamp + timedelta(seconds=122),
        )
        assert recovery.status(
            db, org="org-a", owner="owner-a", job_id=job_id,
        )["status"] == "AWAITING_REVIEW"


def test_disposable_postgres_recovers_across_real_process_exit(postgres, tmp_path, monkeypatch):
    """Two separate Python interpreters share durable DB and fake private files.

    This simulates an abrupt worker exit after its claim was committed.
    Lease expiry is advanced by test clock, not by sleeping a minute.
    """
    import json
    import subprocess
    import sys

    engine, _ = postgres
    from nova_recovery_process_helper import SharedFakePrivateStore

    shared_storage = SharedFakePrivateStore(tmp_path / "private-synthetic-storage")
    monkeypatch.setattr(recovery, "_store", lambda: shared_storage)
    with Session(engine) as db:
        queued = recovery.enqueue(
            db, org="org-a", owner="owner-a", engagement_id="eng-a",
            task_id="task-a", request_key="subprocess-restart",
            raw=b"Name\nAda\nAda\n",
        )
    job_id = queued["job_id"]
    start = datetime.now(timezone.utc)
    env = os.environ.copy()
    env["NOVA_CSV_PROCESS_TEST"] = "synthetic-only"
    env["NOVA_CSV_CI_FAKE_STORE"] = str(shared_storage.directory)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    helper = str(Path(__file__).with_name("nova_recovery_process_helper.py"))

    def invoke(step, clock):
        done = subprocess.run(
            [sys.executable, helper, job_id, step, clock.isoformat()],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env, capture_output=True, text=True, timeout=20,
            check=False,
        )
        assert done.returncode == 0, done.stderr[-1800:]
        return json.loads(done.stdout.strip())

    vanished = invoke("claim-and-exit", start)
    assert vanished["attempts"] == 1
    with Session(engine) as db:
        assert recovery.status(db, org="org-a", owner="owner-a",
                               job_id=job_id)["status"] == "RUNNING"
    recovered = invoke("resume", start + timedelta(seconds=61))
    assert recovered["status"] == "AWAITING_REVIEW"
    assert recovered["delivered"] is False
    with Session(engine) as db:
        assert recovery.review_download(
            db, org="org-a", owner="owner-a", job_id=job_id,
        ) == b"Name\nAda\n"
        assert recovery.status(db, org="org-a", owner="owner-a",
                               job_id=job_id)["attempts"] == 2
        with pytest.raises(CustomerCSVBlocked, match="Stale worker"):
            recovery.complete(
                db, org="org-a", owner="owner-a", job_id=job_id,
                token=vanished["token"], output_ref="stale-output",
                output_sha256="a" * 64,
            )
    assert len(list(shared_storage.directory.glob("*.bin"))) == 2


def test_postgres_cleanup_debt_survives_separate_database_session(postgres, monkeypatch):
    engine, store = postgres
    with Session(engine) as db:
        job_id = recovery.enqueue(
            db, org="org-a", owner="owner-a", engagement_id="eng-a",
            task_id="task-a", request_key="persist-cleanup-debt",
            raw=b"Name\nAda\nAda\n",
        )["job_id"]

        checks = [0]

        def revoke_after_processing(engagement_id, task_id):
            checks[0] += 1
            if checks[0] == 2:
                raise CustomerCSVBlocked("Revoked during processing", 409)

        monkeypatch.setattr(
            store, "delete",
            lambda **kwargs: (_ for _ in ()).throw(OSError("synthetic delete outage")),
        )
        with pytest.raises(CustomerCSVBlocked, match="Revoked"):
            recovery.process_job(
                db, org="org-a", owner="owner-a", job_id=job_id,
                authorization_check=revoke_after_processing,
            )

    # New independent SQLAlchemy session must see the retained audit evidence.
    with Session(engine) as reopened:
        summary = recovery.cleanup_debt_summary(
            reopened, org="org-a", owner="owner-a",
        )
        assert summary["unresolved_cleanup_failures"] == 1
        assert recovery.cleanup_debt_summary(
            reopened, org="org-b", owner="owner-a",
        )["unresolved_cleanup_failures"] == 0
        records = reopened.execute(sa.select(recovery.cleanup_events)).mappings().all()
        assert len(records) == 1
        assert records[0]["failure_code"] == "OUTPUT_DELETE_FAILED"
        assert records[0]["job_id"] == job_id


def test_postgres_cleanup_retry_dry_run_and_ref_protection(postgres, monkeypatch):
    engine, store = postgres
    stamp = datetime.now(timezone.utc) + timedelta(minutes=16)
    with Session(engine) as db:
        job_id = recovery.enqueue(
            db, org="org-a", owner="owner-a", engagement_id="eng-a",
            task_id="task-a", request_key="pg-retry-cleanup",
            raw=b"Name\nAda\n",
        )["job_id"]
        live_input = next(iter(store.items))
        orphan = "fictional/unattached-private-object"
        store.items[orphan] = b"synthetic"
        recovery.record_cleanup_failure(
            db, org="org-a", owner="owner-a", job_id=job_id,
            storage_ref=live_input, failure_code="INPUT_DELETE_FAILED",
        )
        recovery.record_cleanup_failure(
            db, org="org-a", owner="owner-a", job_id=job_id,
            storage_ref=orphan, failure_code="OUTPUT_DELETE_FAILED",
        )
        preview = recovery.retry_private_cleanup(
            db, org="org-a", owner="owner-a", now=stamp,
        )
        assert preview["reviewed"] == 2
        assert preview["protected_refs"] == 1
        assert preview["deleted"] == 0
        assert orphan in store.items
        completed = recovery.retry_private_cleanup(
            db, org="org-a", owner="owner-a", now=stamp,
            dry_run=False, approval="owner-approved-staging-cleanup",
        )
        assert completed["deleted"] == 1
        assert completed["protected_refs"] == 1
        assert live_input in store.items
        assert orphan not in store.items
    with Session(engine) as db:
        assert recovery.cleanup_debt_summary(
            db, org="org-a", owner="owner-a",
        )["unresolved_cleanup_failures"] == 1
