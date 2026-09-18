"""Phase 2 synthetic scheduler: leases, retry, DLQ, isolation."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.kernel import NovaV3Kernel
from app.core.nova.v3.worker import JOB_KINDS, backoff_seconds, lease_job, recover_stale


def test_all_job_kinds_timezone_idempotency_pause_cancel() -> None:
    kernel = NovaV3Kernel()
    jobs = []
    for kind in JOB_KINDS:
        job = kernel.schedule_job(
            organization_id="org-a",
            owner_user_id="owner-a",
            kind=kind,
            timezone_name="America/Chicago",
            frequency="daily",
        )
        again = kernel.schedule_job(
            organization_id="org-a",
            owner_user_id="owner-a",
            kind=kind,
            timezone_name="America/Chicago",
            frequency="daily",
        )
        assert again.job_id == job.job_id
        jobs.append(job)
    assert len({item.job_id for item in jobs}) == len(JOB_KINDS)
    paused = kernel.pause_job(jobs[0].job_id, organization_id="org-a", owner_user_id="owner-a")
    assert paused.status == "PAUSED"
    kernel.resume_job(jobs[0].job_id, organization_id="org-a", owner_user_id="owner-a")
    kernel.cancel_job(jobs[1].job_id, organization_id="org-a", owner_user_id="owner-a")
    ran = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert jobs[1].job_id not in {item.job_id for item in ran}
    with pytest.raises(V3Error):
        kernel.schedule_job(
            organization_id="org-a", owner_user_id="owner-a", kind="not_a_job", timezone_name="America/Chicago"
        )
    assert backoff_seconds(1) == 60
    assert backoff_seconds(8) == 3600


def test_stale_lock_recovery_and_concurrency_guard() -> None:
    kernel = NovaV3Kernel()
    job = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="opportunity_refresh",
        timezone_name="America/Chicago",
    )
    lease_job(job, worker_id="worker-a", now=kernel.now, ttl=timedelta(seconds=5))
    with pytest.raises(V3Error) as conflict:
        kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a", worker_id="worker-b")
    assert conflict.value.code == "LEASE_MISMATCH"
    kernel.now = kernel.now + timedelta(seconds=10)
    recover_stale(job, now=kernel.now)
    assert job.status == "PREPARED"
    ran = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a", worker_id="worker-b")
    assert ran[0].job_id == job.job_id
    assert job.run_history


def test_scheduler_crash_then_restart() -> None:
    kernel = NovaV3Kernel()
    job = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="application_followup",
        timezone_name="America/Chicago",
    )
    kernel.crash_before_job_commit = True
    kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a", worker_id="worker-a")
    assert job.status == "LEASED"
    assert job.run_count == 0
    kernel.now = kernel.now + timedelta(seconds=31)
    ran = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a", worker_id="worker-a")
    assert ran[0].run_count == 1
    again = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a", worker_id="worker-a")
    assert again == []


def test_temporary_connector_retry_then_dead_letter() -> None:
    kernel = NovaV3Kernel()
    job = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="connector_health_check",
        timezone_name="America/Chicago",
    )
    kernel.register_connector(
        organization_id="org-a", owner_user_id="owner-a", kind="email", state="TEMPORARY_FAILURE"
    )
    for _ in range(3):
        kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert job.dead_letter is True
    assert job.status == "DEAD_LETTER"
    retried = kernel.retry_job(job.job_id, organization_id="org-a", owner_user_id="owner-a")
    assert retried.dead_letter is False
    kernel.connectors[next(iter(kernel.connectors))].state = "CONNECTED"
    ran = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert ran and ran[0].status == "EXECUTED"


def test_owner_isolation_and_shutdown() -> None:
    kernel = NovaV3Kernel()
    kernel.schedule_job(
        organization_id="org-a", owner_user_id="owner-a", kind="client_followup", timezone_name="America/Chicago"
    )
    kernel.schedule_job(
        organization_id="org-a", owner_user_id="owner-b", kind="client_followup", timezone_name="America/Chicago"
    )
    ran = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert len(ran) == 1
    kernel.worker_shutdown = True
    kernel.schedule_job(
        organization_id="org-a", owner_user_id="owner-a", kind="work_deadline", timezone_name="America/Chicago"
    )
    assert kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a") == []
