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


def test_lease_renewal_blocks_stale_worker(harness):
    db, _ = harness
    job_id = submit(db, key="lease-renew")["job_id"]
    start = datetime.now(timezone.utc)
    worker_a = scoped(db, recovery.claim, job_id, now=start, lease_seconds=60)
    expiry = scoped(
        db, recovery.renew_lease, job_id, token=worker_a["token"],
        now=start + timedelta(seconds=30), lease_seconds=90,
    )
    assert expiry == start + timedelta(seconds=120)
    with pytest.raises(CustomerCSVBlocked):
        scoped(db, recovery.claim, job_id, now=start + timedelta(seconds=65))
    with pytest.raises(CustomerCSVBlocked, match="Cannot renew"):
        scoped(
            db, recovery.renew_lease, job_id, token=worker_a["token"],
            now=start + timedelta(seconds=121),
        )
    worker_b = scoped(db, recovery.claim, job_id,
                      now=start + timedelta(seconds=121))
    with pytest.raises(CustomerCSVBlocked, match="Cannot renew"):
        scoped(
            db, recovery.renew_lease, job_id, token=worker_a["token"],
            now=start + timedelta(seconds=122),
        )
    scoped(db, recovery.complete, job_id, token=worker_b["token"],
           output_ref="winning-private-object", output_sha256="b" * 64,
           now=start + timedelta(seconds=122))
    assert scoped(db, recovery.status, job_id)["status"] == "AWAITING_REVIEW"


def test_recovery_after_first_process_disappears(harness):
    db, store = harness
    job_id = submit(db, key="crash-restart")["job_id"]
    start = datetime.now(timezone.utc)
    vanished_worker = scoped(db, recovery.claim, job_id, now=start, lease_seconds=60)
    restart = start + timedelta(minutes=7)
    assert recovery.due_job_ids(
        db, org="org-a", owner="owner-a", now=restart,
    ) == [job_id]
    result = recovery.run_due_jobs(
        db, org="org-a", owner="owner-a", now=restart,
        authorization_check=lambda eng, task: None,
    )
    assert result["awaiting_review"] == [job_id]
    with pytest.raises(CustomerCSVBlocked, match="Stale worker"):
        scoped(
            db, recovery.complete, job_id, token=vanished_worker["token"],
            output_ref="stale-private-object", output_sha256="a" * 64,
        )
    assert scoped(db, recovery.status, job_id)["attempts"] == 2
    assert scoped(db, recovery.review_download, job_id) == b"Name\nAda\n"
    assert len(store.objects) == 2


def test_output_delete_failure_is_durably_visible_without_private_keys(harness, monkeypatch):
    db, store = harness
    job_id = submit(db, key="cleanup-debt")["job_id"]
    checked = [0]

    def authorization(eng, task):
        checked[0] += 1
        if checked[0] == 2:
            raise CustomerCSVBlocked("Assignment revoked during processing", 409)

    def deny_delete(*, storage_ref):
        raise OSError("synthetic storage delete outage")

    monkeypatch.setattr(store, "delete", deny_delete)
    with pytest.raises(CustomerCSVBlocked, match="revoked"):
        scoped(db, recovery.process_job, job_id,
               authorization_check=authorization)
    debt = recovery.cleanup_debt_summary(db, org="org-a", owner="owner-a")
    assert debt == {"unresolved_cleanup_failures": 1, "delivered": False}
    assert recovery.cleanup_debt_summary(
        db, org="different", owner="owner-a"
    )["unresolved_cleanup_failures"] == 0
    event = db.execute(sa.select(recovery.cleanup_events)).mappings().one()
    assert event["failure_code"] == "OUTPUT_DELETE_FAILED"
    assert event["job_id"] == job_id
    assert event["storage_ref"] in store.objects
    assert event["resolved_at"] is None


def test_input_delete_failure_is_recorded_after_failed_upload(harness, monkeypatch):
    db, store = harness
    original = store.store

    def inaccurate_store(**kwargs):
        backend, ref, size = original(**kwargs)
        return backend, ref, size + 1

    monkeypatch.setattr(store, "store", inaccurate_store)
    monkeypatch.setattr(
        store, "delete",
        lambda **kwargs: (_ for _ in ()).throw(OSError("synthetic delete outage")),
    )
    with pytest.raises(CustomerCSVBlocked, match="size mismatch"):
        submit(db, key="failed-input")
    debt = recovery.cleanup_debt_summary(db, org="org-a", owner="owner-a")
    assert debt["unresolved_cleanup_failures"] == 1
    event = db.execute(sa.select(recovery.cleanup_events)).mappings().one()
    assert event["failure_code"] == "INPUT_DELETE_FAILED"
    assert event["storage_ref"] in store.objects


def test_cleanup_retry_dry_run_and_explicit_approval(harness):
    db, store = harness
    job_id = submit(db, key="cleanup-retry")["job_id"]
    orphan_ref = "org-a/recovery-orphan.bin"
    store.objects[orphan_ref] = b"fictional cleanup debris"
    recovery.record_cleanup_failure(
        db, org="org-a", owner="owner-a", job_id=job_id,
        storage_ref=orphan_ref, failure_code="OUTPUT_DELETE_FAILED",
    )
    stamp = datetime.now(timezone.utc) + timedelta(minutes=16)
    dry = recovery.retry_private_cleanup(
        db, org="org-a", owner="owner-a", now=stamp,
    )
    assert dry["reviewed"] == 1 and dry["deleted"] == 0
    assert dry["dry_run"] is True
    assert orphan_ref in store.objects
    with pytest.raises(CustomerCSVBlocked, match="Explicit owner"):
        recovery.retry_private_cleanup(
            db, org="org-a", owner="owner-a", dry_run=False, now=stamp,
        )
    denied = recovery.retry_private_cleanup(
        db, org="different", owner="owner-a", now=stamp,
    )
    assert denied["reviewed"] == 0
    finished = recovery.retry_private_cleanup(
        db, org="org-a", owner="owner-a", dry_run=False, now=stamp,
        approval="owner-approved-staging-cleanup",
    )
    assert finished["deleted"] == 1
    assert orphan_ref not in store.objects
    assert recovery.cleanup_debt_summary(
        db, org="org-a", owner="owner-a",
    )["unresolved_cleanup_failures"] == 0


def test_cleanup_retry_protects_any_job_reference_and_never_deletes(harness):
    db, store = harness
    job = submit(db, key="cleanup-protected")["job_id"]
    input_ref = next(iter(store.objects))
    recovery.record_cleanup_failure(
        db, org="org-a", owner="owner-a", job_id=job,
        storage_ref=input_ref, failure_code="INPUT_DELETE_FAILED",
    )
    result = recovery.retry_private_cleanup(
        db, org="org-a", owner="owner-a", dry_run=False,
        approval="owner-approved-staging-cleanup",
        now=datetime.now(timezone.utc) + timedelta(minutes=16),
    )
    assert result["protected_refs"] == 1
    assert result["deleted"] == 0
    assert input_ref in store.objects
    assert recovery.cleanup_debt_summary(
        db, org="org-a", owner="owner-a",
    )["unresolved_cleanup_failures"] == 1


def test_cleanup_retry_failed_delete_remains_unresolved(harness, monkeypatch):
    db, store = harness
    job = submit(db, key="cleanup-retry-failure")["job_id"]
    orphan_ref = "org-a/still-orphan.bin"
    store.objects[orphan_ref] = b"fictional"
    recovery.record_cleanup_failure(
        db, org="org-a", owner="owner-a", job_id=job,
        storage_ref=orphan_ref, failure_code="OUTPUT_DELETE_FAILED",
    )
    monkeypatch.setattr(
        store, "delete",
        lambda **kw: (_ for _ in ()).throw(OSError("synthetic outage")),
    )
    out = recovery.retry_private_cleanup(
        db, org="org-a", owner="owner-a", dry_run=False,
        approval="owner-approved-staging-cleanup",
        now=datetime.now(timezone.utc) + timedelta(minutes=16),
    )
    assert out["failed_deletions"] == 1
    assert out["deleted"] == 0
    assert recovery.cleanup_debt_summary(
        db, org="org-a", owner="owner-a",
    )["unresolved_cleanup_failures"] == 1


def test_cleanup_retry_never_deletes_another_tenants_referenced_object(harness):
    db, store = harness
    first = submit(db, key="cleanup-owner-a")["job_id"]
    other = recovery.enqueue(
        db, org="org-b", owner="owner-b", engagement_id="eng-b",
        task_id="task-b", request_key="cleanup-owner-b",
        raw=b"Name\nBea\n",
    )["job_id"]
    foreign_ref = db.execute(
        sa.select(recovery.recovery_jobs.c.input_ref).where(
            recovery.recovery_jobs.c.id == other,
        )
    ).scalar_one()
    recovery.record_cleanup_failure(
        db, org="org-a", owner="owner-a", job_id=first,
        storage_ref=foreign_ref, failure_code="INPUT_DELETE_FAILED",
    )
    result = recovery.retry_private_cleanup(
        db, org="org-a", owner="owner-a", dry_run=False,
        approval="owner-approved-staging-cleanup",
        now=datetime.now(timezone.utc) + timedelta(minutes=16),
    )
    assert result["protected_refs"] == 1
    assert result["deleted"] == 0
    assert foreign_ref in store.objects
