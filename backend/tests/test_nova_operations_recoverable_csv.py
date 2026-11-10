"""Synthetic, isolated recoverable CSV queue tests. No customer records or S3."""
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_recoverable_csv as recovery
from app.core.nova.work_revenue.operations_customer_csv_jobs import CustomerCSVBlocked

ORIGINAL_RUNTIME_GATE = recovery.require_runtime


class MemoryStore:
    def __init__(self):
        self.objects = {}
        self.counter = 0

    def store(self, *, organization_id, application_id, category, filename,
              content_type, stream):
        self.counter += 1
        key = f"{organization_id}/{application_id}/{category}/{self.counter}"
        contents = stream.read()
        self.objects[key] = contents
        return "synthetic-private", key, len(contents)

    def retrieve(self, *, storage_ref):
        return self.objects[storage_ref], "application/octet-stream"

    def delete(self, *, storage_ref):
        self.objects.pop(storage_ref, None)


@pytest.fixture
def harness(monkeypatch):
    engine = sa.create_engine("sqlite://",
                              connect_args={"check_same_thread": False},
                              poolclass=sa.pool.StaticPool)
    recovery.metadata.create_all(engine)
    store = MemoryStore()
    monkeypatch.setattr(recovery, "require_runtime", lambda db: None)
    monkeypatch.setattr(recovery, "_store", lambda: store)
    with Session(engine) as session:
        yield session, store
    engine.dispose()


def submit(db, key="abc", raw=b"Name\nAda\nAda\n"):
    return recovery.enqueue(db, org="org-a", owner="owner-a",
                            engagement_id="eng-1", task_id="task-1",
                            request_key=key, raw=raw)


def scoped(db, method, job_id, **extra):
    return method(db, org="org-a", owner="owner-a", job_id=job_id, **extra)


def test_private_input_persists_and_review_output_is_checked(harness):
    db, store = harness
    job = submit(db)
    assert job["status"] == "QUEUED"
    row = scoped(db, recovery.status, job["job_id"])
    assert row["status"] == "QUEUED"
    assert len(store.objects) == 1
    result = scoped(db, recovery.process_job, job["job_id"],
                    authorization_check=lambda eng, task: None)
    assert result["status"] == "AWAITING_REVIEW"
    assert scoped(db, recovery.review_download, job["job_id"]) == b"Name\nAda\n"
    assert len(store.objects) == 2


def test_idempotent_replay_and_changed_content_rejected(harness):
    db, store = harness
    first = submit(db)
    second = submit(db)
    assert second["job_id"] == first["job_id"]
    assert second["replayed"] is True
    assert len(store.objects) == 1
    with pytest.raises(CustomerCSVBlocked, match="different work"):
        submit(db, raw=b"Name\nDifferent\n")


def test_expired_worker_cannot_publish_after_new_claim(harness):
    db, _ = harness
    job_id = submit(db)["job_id"]
    start = datetime.now(timezone.utc)
    worker_a = scoped(db, recovery.claim, job_id, now=start, lease_seconds=60)
    with pytest.raises(CustomerCSVBlocked):
        scoped(db, recovery.claim, job_id, now=start + timedelta(seconds=20))
    worker_b = scoped(db, recovery.claim, job_id,
                      now=start + timedelta(seconds=61), lease_seconds=60)
    assert worker_a["token"] != worker_b["token"]
    with pytest.raises(CustomerCSVBlocked, match="Stale worker"):
        scoped(db, recovery.complete, job_id, token=worker_a["token"],
               output_ref="obj-old", output_sha256="a" * 64,
               now=start + timedelta(seconds=62))
    scoped(db, recovery.complete, job_id, token=worker_b["token"],
           output_ref="obj-new", output_sha256="b" * 64,
           now=start + timedelta(seconds=62))
    assert scoped(db, recovery.status, job_id)["status"] == "AWAITING_REVIEW"


def test_revoked_scope_blocks_processing_before_claim(harness):
    db, store = harness
    job_id = submit(db)["job_id"]

    def revoked(engagement_id, task_id):
        raise CustomerCSVBlocked("Assignment revoked", 409)

    with pytest.raises(CustomerCSVBlocked, match="revoked"):
        scoped(db, recovery.process_job, job_id, authorization_check=revoked)
    assert scoped(db, recovery.status, job_id)["attempts"] == 0
    assert len(store.objects) == 1


def test_corrupted_input_never_generates_review_artifact(harness):
    db, store = harness
    job_id = submit(db)["job_id"]
    ref = next(iter(store.objects))
    store.objects[ref] = b"altered"
    with pytest.raises(CustomerCSVBlocked, match="integrity"):
        scoped(db, recovery.process_job, job_id,
               authorization_check=lambda eng, task: None)
    state = scoped(db, recovery.status, job_id)
    assert state["status"] == "QUEUED"
    assert state["attempts"] == 1


def test_reconcile_exhausted_expired_lease(harness):
    db, _ = harness
    job_id = submit(db, key="exhausted")["job_id"]
    start = datetime.now(timezone.utc)
    first = scoped(db, recovery.claim, job_id, now=start, lease_seconds=60)
    assert first["attempts"] == 1
    second = scoped(db, recovery.claim, job_id,
                    now=start + timedelta(seconds=61), lease_seconds=60)
    assert second["attempts"] == 2
    third = scoped(db, recovery.claim, job_id,
                   now=start + timedelta(seconds=122), lease_seconds=60)
    assert third["attempts"] == 3
    result = recovery.reconcile_stale_jobs(
        db, org="org-a", owner="owner-a",
        now=start + timedelta(seconds=183),
    )
    assert result["exhausted_jobs"] == 1
    assert scoped(db, recovery.status, job_id)["status"] == "FAILED"
    with pytest.raises(CustomerCSVBlocked):
        scoped(db, recovery.claim, job_id, now=start + timedelta(seconds=184))


def test_recovery_preview_fails_closed_in_production(harness, monkeypatch):
    db, _ = harness
    monkeypatch.setenv("NOVA_OPERATIONS_RECOVERABLE_CSV_ENABLED", "true")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(CustomerCSVBlocked, match="staging-only") as blocked:
        ORIGINAL_RUNTIME_GATE(db)
    assert blocked.value.code == 503


def test_due_job_discovery_is_owner_scoped_and_bounded(harness):
    db, _ = harness
    one = submit(db, key="due-one")["job_id"]
    two = submit(db, key="due-two")["job_id"]
    assert set(recovery.due_job_ids(
        db, org="org-a", owner="owner-a",
    )) == {one, two}
    assert recovery.due_job_ids(
        db, org="org-b", owner="owner-b",
    ) == []
    assert len(recovery.due_job_ids(
        db, org="org-a", owner="owner-a", limit=1,
    )) == 1
    with pytest.raises(CustomerCSVBlocked):
        recovery.due_job_ids(db, org="org-a", owner="owner-a", limit=0)


def test_worker_pass_processes_only_authorized_due_jobs(harness):
    db, store = harness
    ids = [submit(db, key=f"worker-{i}")["job_id"] for i in range(2)]
    calls = []
    result = recovery.run_due_jobs(
        db, org="org-a", owner="owner-a", limit=10,
        authorization_check=lambda eng, task: calls.append((eng, task)),
    )
    assert result["attempted"] == 2
    assert set(result["awaiting_review"]) == set(ids)
    assert result["failed_attempts"] == []
    assert result["delivered"] is False
    assert len(calls) == 4
    assert len(store.objects) == 4
    assert recovery.due_job_ids(db, org="org-a", owner="owner-a") == []


def test_worker_pass_fails_closed_on_revoked_scope(harness):
    db, store = harness
    job_id = submit(db, key="worker-revoked")["job_id"]

    def deny(eng, task):
        raise CustomerCSVBlocked("Assignment revoked", 409)

    result = recovery.run_due_jobs(
        db, org="org-a", owner="owner-a", authorization_check=deny,
    )
    assert result["attempted"] == 1
    assert result["failed_attempts"] == [job_id]
    assert recovery.status(
        db, org="org-a", owner="owner-a", job_id=job_id,
    )["status"] == "QUEUED"
    assert len(store.objects) == 1
