"""Offline SQLite queue tests. No external calls or provider activation."""
import sqlite3

import pytest

from app.core.nova.work_revenue.operations_job_queue import (
    JobConflict, claim_job, complete_job, enqueue_job, ensure_schema,
    fail_job, get_job_state,
)


@pytest.fixture
def db(tmp_path):
    connection = sqlite3.connect(tmp_path / "operations.sqlite")
    ensure_schema(connection)
    yield connection
    connection.close()


def put(db, tenant="a", key="one", fingerprint="a" * 64, retries=3):
    return enqueue_job(db, tenant_id=tenant, idempotency_key=key,
                       kind="spreadsheet", input_sha256=fingerprint, max_attempts=retries)


def test_deduplication_and_conflict(db):
    assert put(db) == put(db)
    with pytest.raises(JobConflict):
        put(db, fingerprint="b" * 64)


def test_tenant_isolation(db):
    job_id = put(db)
    assert get_job_state(db, tenant_id="b", job_id=job_id) is None
    assert claim_job(db, tenant_id="b", now=0) is None


def test_restart_preserves_job_and_completion(tmp_path):
    path = tmp_path / "restart.sqlite"
    first = sqlite3.connect(path)
    ensure_schema(first)
    job_id = put(first)
    first.close()
    second = sqlite3.connect(path)
    job = claim_job(second, tenant_id="a", now=100)
    assert job.job_id == job_id
    complete_job(second, job=job, output_sha256="b" * 64, now=110)
    assert get_job_state(second, tenant_id="a", job_id=job_id) == "completed"
    assert claim_job(second, tenant_id="a", now=200) is None
    second.close()


def test_expired_lease_reclaimed_and_old_worker_fenced(db):
    job_id = put(db)
    old = claim_job(db, tenant_id="a", now=100, lease_seconds=10)
    new = claim_job(db, tenant_id="a", now=110, lease_seconds=10)
    assert new.job_id == job_id
    assert new.lease_token != old.lease_token
    with pytest.raises(JobConflict):
        complete_job(db, job=old, output_sha256="b" * 64, now=111)
    complete_job(db, job=new, output_sha256="b" * 64, now=112)


def test_bounded_retries(db):
    job_id = put(db, retries=2)
    first = claim_job(db, tenant_id="a", now=0)
    fail_job(db, job=first, error_code="TEMPORARY", now=1, retry_delay_seconds=10)
    assert claim_job(db, tenant_id="a", now=5) is None
    second = claim_job(db, tenant_id="a", now=11)
    assert second.attempts == 2
    fail_job(db, job=second, error_code="FINAL", now=12)
    assert get_job_state(db, tenant_id="a", job_id=job_id) == "failed"
    assert claim_job(db, tenant_id="a", now=100) is None


def test_expired_lease_cannot_complete(db):
    put(db)
    job = claim_job(db, tenant_id="a", now=0, lease_seconds=5)
    with pytest.raises(JobConflict):
        complete_job(db, job=job, output_sha256="b" * 64, now=5)



@pytest.mark.parametrize("invalid", [None, 123, "", " ", "bad\nidentity", "bad\x00identity", "x" * 257])
def test_enqueue_rejects_invalid_identity(db, invalid):
    with pytest.raises(JobConflict, match="Invalid job identity"):
        enqueue_job(
            db, tenant_id=invalid, idempotency_key="key",
            kind="spreadsheet", input_sha256="a" * 64,
        )


@pytest.mark.parametrize("retries", [None, "3", True, 0, 11])
def test_enqueue_rejects_invalid_retry_limits(db, retries):
    with pytest.raises(JobConflict, match="Invalid fingerprint or retry limit"):
        enqueue_job(
            db, tenant_id="tenant-a", idempotency_key="key",
            kind="spreadsheet", input_sha256="a" * 64,
            max_attempts=retries,
        )


def test_invalid_enqueue_does_not_store_job(db):
    with pytest.raises(JobConflict):
        enqueue_job(
            db, tenant_id="tenant-a", idempotency_key="bad\nkey",
            kind="spreadsheet", input_sha256="a" * 64,
        )
    assert db.execute("SELECT COUNT(*) FROM nova_operations_offline_jobs").fetchone()[0] == 0



@pytest.mark.parametrize("tenant", [None, 123, "", " ", "bad\nidentity", "x" * 257])
def test_claim_rejects_invalid_tenant_without_claiming_job(db, tenant):
    job_id = put(db)
    with pytest.raises(JobConflict, match="Invalid tenant"):
        claim_job(db, tenant_id=tenant, now=100)
    assert get_job_state(db, tenant_id="a", job_id=job_id) == "queued"


@pytest.mark.parametrize("clock", [None, "100", True, -1])
def test_claim_rejects_invalid_clock(db, clock):
    put(db)
    with pytest.raises(JobConflict, match="clock"):
        claim_job(db, tenant_id="a", now=clock)


@pytest.mark.parametrize("duration", [None, "60", True, 0, 3601])
def test_claim_rejects_invalid_lease_duration(db, duration):
    put(db)
    with pytest.raises(JobConflict, match="lease duration"):
        claim_job(db, tenant_id="a", now=100, lease_seconds=duration)


@pytest.mark.parametrize("requested_id", [True, "1", 0, -1])
def test_claim_rejects_invalid_job_id(db, requested_id):
    put(db)
    with pytest.raises(JobConflict, match="job ID"):
        claim_job(db, tenant_id="a", now=100, job_id=requested_id)



@pytest.mark.parametrize("error_code", [None, 7, "", " ", "bad\ncode", "bad\x00code", "x" * 81])
def test_fail_rejects_invalid_error_code_without_releasing_claim(db, error_code):
    put(db)
    claim = claim_job(db, tenant_id="a", now=10, lease_seconds=60)
    with pytest.raises(JobConflict, match="Invalid error code"):
        fail_job(db, job=claim, error_code=error_code, now=11)
    assert get_job_state(db, tenant_id="a", job_id=claim.job_id) == "running"


@pytest.mark.parametrize("delay", [None, "30", True, -1, 86401])
def test_fail_rejects_invalid_retry_delay(db, delay):
    put(db)
    claim = claim_job(db, tenant_id="a", now=10)
    with pytest.raises(JobConflict, match="retry delay"):
        fail_job(db, job=claim, error_code="RETRY", now=11, retry_delay_seconds=delay)
    assert get_job_state(db, tenant_id="a", job_id=claim.job_id) == "running"


@pytest.mark.parametrize("clock", [None, True, -1, "11"])
def test_fail_rejects_invalid_clock(db, clock):
    put(db)
    claim = claim_job(db, tenant_id="a", now=10)
    with pytest.raises(JobConflict, match="clock"):
        fail_job(db, job=claim, error_code="RETRY", now=clock)
    assert get_job_state(db, tenant_id="a", job_id=claim.job_id) == "running"


@pytest.mark.parametrize("bad_time", [None, True, -1, "101"])
def test_complete_rejects_invalid_clock_without_changing_job(db, bad_time):
    job_id = put(db)
    claim = claim_job(db, tenant_id="a", now=100, lease_seconds=60)
    with pytest.raises(JobConflict, match="completion timestamp"):
        complete_job(db, job=claim, output_sha256="b" * 64, now=bad_time)
    assert get_job_state(db, tenant_id="a", job_id=job_id) == "running"
