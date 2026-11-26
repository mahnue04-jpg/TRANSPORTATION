"""Regression tests for exact-id claims and expired-lease recovery."""
import hashlib
import sqlite3

import pytest

from app.core.nova.work_revenue.operations_job_queue import (
    JobConflict, claim_job, enqueue_job, ensure_schema, get_job_state,
)
from app.core.nova.work_revenue.operations_csv_runner import prepare_csv_job


def test_requested_job_does_not_lease_older_tenant_job():
    db = sqlite3.connect(":memory:")
    ensure_schema(db)
    older = enqueue_job(
        db, tenant_id="tenant-a", idempotency_key="older",
        kind="csv_cleanup", input_sha256=hashlib.sha256(b"old").hexdigest(),
    )
    result = prepare_csv_job(
        db, tenant_id="tenant-a", request_id="new",
        raw_csv="name\nnew\n", now=100,
    )
    assert result.job_id != older
    assert get_job_state(db, tenant_id="tenant-a", job_id=older) == "queued"
    assert get_job_state(db, tenant_id="tenant-a", job_id=result.job_id) == "completed"


def test_expired_lease_is_reclaimed_for_same_idempotent_request(tmp_path):
    path = tmp_path / "queue.db"
    raw = "name\nAna\n"
    db = sqlite3.connect(path)
    ensure_schema(db)
    job_id = enqueue_job(
        db, tenant_id="tenant-a", idempotency_key="req-1",
        kind="csv_cleanup", input_sha256=hashlib.sha256(raw.encode()).hexdigest(),
    )
    first = claim_job(db, tenant_id="tenant-a", now=100, lease_seconds=60, job_id=job_id)
    assert first is not None
    db.close()
    restarted = sqlite3.connect(path)
    with pytest.raises(JobConflict):
        prepare_csv_job(restarted, tenant_id="tenant-a", request_id="req-1", raw_csv=raw, now=120)
    result = prepare_csv_job(
        restarted, tenant_id="tenant-a", request_id="req-1", raw_csv=raw, now=161,
    )
    assert result.job_id == job_id
    assert get_job_state(restarted, tenant_id="tenant-a", job_id=job_id) == "completed"
    restarted.close()
