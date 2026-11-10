"""Synthetic, isolated recoverable CSV queue tests. No customer records or S3."""
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_recoverable_csv as recovery
from app.core.nova.work_revenue.operations_customer_csv_jobs import CustomerCSVBlocked


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
