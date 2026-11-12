"""Failure-injection regression for atomic Operations job and artifact persistence."""
import sqlite3

import pytest

from app.core.nova.work_revenue.operations_artifact_review import (
    complete_and_store_review_artifact, ensure_artifact_schema, read_review_artifact,
)
from app.core.nova.work_revenue.operations_job_queue import (
    JobConflict, claim_job, enqueue_job, ensure_schema, get_job_state,
)


def test_storage_failure_rolls_back_completion_and_recovers(tmp_path):
    path = tmp_path / "atomic.sqlite"
    db = sqlite3.connect(path)
    ensure_schema(db)
    ensure_artifact_schema(db)
    job_id = enqueue_job(
        db, tenant_id="tenant-a", idempotency_key="one",
        kind="csv_cleanup", input_sha256="a" * 64,
    )
    first = claim_job(db, tenant_id="tenant-a", now=100, lease_seconds=10)
    db.execute(
        """CREATE TRIGGER fail_artifact BEFORE INSERT ON nova_operations_offline_artifacts
           BEGIN SELECT RAISE(ABORT, 'injected storage failure'); END"""
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected storage failure"):
        complete_and_store_review_artifact(
            db, job=first, csv_text="Name\nAna\n",
            output_sha256=__import__("hashlib").sha256(b"Name\nAna\n").hexdigest(), now=101,
        )
    assert get_job_state(db, tenant_id="tenant-a", job_id=job_id) == "running"
    assert read_review_artifact(db, tenant_id="tenant-a", job_id=job_id) is None
    db.execute("DROP TRIGGER fail_artifact")
    db.commit()
    db.close()

    restarted = sqlite3.connect(path)
    second = claim_job(restarted, tenant_id="tenant-a", now=110, lease_seconds=20)
    assert second is not None and second.job_id == job_id
    complete_and_store_review_artifact(
        restarted, job=second, csv_text="Name\nAna\n",
        output_sha256=__import__("hashlib").sha256(b"Name\nAna\n").hexdigest(), now=111,
    )
    assert get_job_state(restarted, tenant_id="tenant-a", job_id=job_id) == "completed"
    assert read_review_artifact(restarted, tenant_id="tenant-a", job_id=job_id) == (
        "awaiting_review", "Name\nAna\n",
    )
    assert read_review_artifact(restarted, tenant_id="tenant-b", job_id=job_id) is None
    restarted.close()


@pytest.mark.parametrize("bad_time", [None, True, -1, "101"])
def test_invalid_completion_time_does_not_change_claim(tmp_path, bad_time):
    db = sqlite3.connect(tmp_path / "completion_time.sqlite")
    ensure_schema(db)
    ensure_artifact_schema(db)
    job_id = enqueue_job(
        db, tenant_id="tenant-a", idempotency_key="time-test",
        kind="csv_cleanup", input_sha256="a" * 64,
    )
    claim = claim_job(db, tenant_id="tenant-a", now=100, lease_seconds=60)
    content = "Name\nAna\n"
    with pytest.raises(JobConflict, match="timestamp"):
        complete_and_store_review_artifact(
            db, job=claim, csv_text=content,
            output_sha256=__import__("hashlib").sha256(content.encode()).hexdigest(),
            now=bad_time,
        )
    assert get_job_state(db, tenant_id="tenant-a", job_id=job_id) == "running"
    assert read_review_artifact(db, tenant_id="tenant-a", job_id=job_id) is None
    db.close()
