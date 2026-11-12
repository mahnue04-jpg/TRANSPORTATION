"""Phase 2 synthetic scheduler: leases, retry, DLQ, isolation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.kernel import NovaV3Kernel
from app.core.nova.v3.persistence import V3Store
from app.core.nova.v3.worker import JOB_KINDS, backoff_seconds, lease_job, next_run, recover_stale


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
    assert ran and ran[0].status == "PREPARED"
    assert ran[0].next_run_at is not None and ran[0].next_run_at > kernel.now


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


def test_hourly_and_two_hour_cadence_waits_and_does_not_send() -> None:
    kernel = NovaV3Kernel()
    started = kernel.now
    hourly = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="opportunity_refresh",
        timezone_name="America/Chicago",
        frequency="hourly",
    )
    two_hour = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="application_followup",
        timezone_name="America/Chicago",
        frequency="every_two_hours",
    )
    first = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert {item.job_id for item in first} == {hourly.job_id, two_hour.job_id}
    assert hourly.run_count == 1 and two_hour.run_count == 1
    assert hourly.status == "PREPARED" and two_hour.status == "PREPARED"
    assert hourly.next_run_at == next_run("hourly", "America/Chicago", started)
    assert two_hour.next_run_at == next_run("every_two_hours", "America/Chicago", started)
    assert kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a") == []

    kernel.now = hourly.next_run_at
    second = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert [item.job_id for item in second] == [hourly.job_id]
    assert hourly.run_count == 2
    assert two_hour.run_count == 1
    assert kernel.messages == {} or all(item.sent_externally is False for item in kernel.messages.values())

    manual = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="work_deadline",
        timezone_name="America/Chicago",
        frequency="manual",
    )
    kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert manual.status == "EXECUTED"
    assert manual.next_run_at is None
    assert kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a") == []
    again = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="work_deadline",
        timezone_name="America/Chicago",
        frequency="manual",
    )
    assert again.job_id == manual.job_id
    assert manual.status == "PREPARED"
    with pytest.raises(V3Error) as bad:
        kernel.schedule_job(
            organization_id="org-a",
            owner_user_id="owner-a",
            kind="work_deadline",
            timezone_name="America/Chicago",
            frequency="every_five_minutes",
        )
    assert bad.value.code == "INVALID_CADENCE"


def test_cadence_and_next_run_survive_restart_without_a_duplicate_tick(tmp_path) -> None:
    store = V3Store(f"sqlite:///{tmp_path / 'scheduler.db'}")
    kernel = NovaV3Kernel()
    kernel.store = store
    hourly = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="opportunity_refresh",
        timezone_name="America/Chicago",
        frequency="hourly",
    )
    two_hour = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="application_followup",
        timezone_name="America/Chicago",
        frequency="every_two_hours",
    )
    first = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert {item.job_id for item in first} == {hourly.job_id, two_hour.job_id}

    restarted = NovaV3Kernel()
    assert restarted.restore_scheduler(store) == 2
    restarted.now = kernel.now
    assert restarted.tick_worker(organization_id="org-a", owner_user_id="owner-a") == []
    restored_hourly = restarted.jobs[hourly.job_id]
    restored_two_hour = restarted.jobs[two_hour.job_id]
    assert restored_hourly.frequency == "hourly"
    assert restored_two_hour.frequency == "every_two_hours"
    assert restored_hourly.run_count == 1
    assert restored_two_hour.run_count == 1
    assert restored_hourly.next_run_at == hourly.next_run_at
    assert restored_two_hour.next_run_at == two_hour.next_run_at
    assert restored_hourly.next_run_at == next_run("hourly", "America/Chicago", kernel.now)
    assert restored_two_hour.next_run_at == next_run("every_two_hours", "America/Chicago", kernel.now)

    restarted.now = restored_hourly.next_run_at
    second = restarted.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert [item.job_id for item in second] == [restored_hourly.job_id]
    assert restored_hourly.run_count == 2
    assert restored_two_hour.run_count == 1

    again = NovaV3Kernel()
    assert again.restore_scheduler(store) == 2
    again.now = restarted.now
    assert again.tick_worker(organization_id="org-a", owner_user_id="owner-a") == []
    manual = again.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="work_deadline",
        timezone_name="America/Chicago",
        frequency="manual",
    )
    manual_run = again.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert [item.job_id for item in manual_run] == [manual.job_id]
    assert manual.status == "EXECUTED"
    assert manual.next_run_at is None
    assert again.tick_worker(organization_id="org-a", owner_user_id="owner-a") == []
    assert again.messages == {}

    saved = {
        row["job_id"]: row
        for row in store.fetch("nova_v3_scheduler_jobs", organization_id="org-a", owner_user_id="owner-a")
    }
    assert saved[hourly.job_id]["frequency"] == "hourly"
    assert saved[hourly.job_id]["next_run_at"]
    assert saved[two_hour.job_id]["frequency"] == "every_two_hours"
    assert saved[manual.job_id]["frequency"] == "manual"
    assert saved[manual.job_id]["next_run_at"] is None
    assert saved[manual.job_id]["status"] == "EXECUTED"


def test_reregister_after_period_change_and_restart_does_not_duplicate(tmp_path) -> None:
    """Re-saving a repeating job after the clock period changes must not start a second job.

    The durable row keeps the period key from when it was created. A restart in
    the next hour, followed by the same schedule request, used to insert another
    prepared job that could tick before the saved next_run_at.
    """
    store = V3Store(f"sqlite:///{tmp_path / 'scheduler-reregister.db'}")
    kernel = NovaV3Kernel()
    kernel.store = store
    kernel.now = datetime(2026, 10, 19, 15, 30, tzinfo=timezone.utc)
    hourly = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="opportunity_refresh",
        timezone_name="America/Chicago",
        frequency="hourly",
    )
    two_hour = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="application_followup",
        timezone_name="America/Chicago",
        frequency="every_two_hours",
    )
    first = kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a")
    assert {item.job_id for item in first} == {hourly.job_id, two_hour.job_id}
    assert hourly.run_count == 1 and two_hour.run_count == 1
    hourly_due = hourly.next_run_at
    two_hour_due = two_hour.next_run_at
    assert hourly_due == datetime(2026, 10, 19, 16, 30, tzinfo=timezone.utc)
    assert two_hour_due == datetime(2026, 10, 19, 17, 30, tzinfo=timezone.utc)

    kernel.now = datetime(2026, 10, 19, 16, 5, tzinfo=timezone.utc)
    again_hourly = kernel.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="opportunity_refresh",
        timezone_name="America/Chicago",
        frequency="hourly",
    )
    assert again_hourly.job_id == hourly.job_id
    assert hourly.run_count == 1
    assert hourly.next_run_at == hourly_due
    assert hourly.status == "PREPARED"
    assert len(kernel.jobs) == 2
    assert kernel.tick_worker(organization_id="org-a", owner_user_id="owner-a") == []

    restarted = NovaV3Kernel()
    restarted.now = datetime(2026, 10, 19, 16, 5, tzinfo=timezone.utc)
    assert restarted.restore_scheduler(store) == 2
    restored_hourly = restarted.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="opportunity_refresh",
        timezone_name="America/Chicago",
        frequency="hourly",
    )
    restored_two_hour = restarted.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="application_followup",
        timezone_name="America/Chicago",
        frequency="every_two_hours",
    )
    assert restored_hourly.job_id == hourly.job_id
    assert restored_two_hour.job_id == two_hour.job_id
    assert len(restarted.jobs) == 2
    assert restarted.tick_worker(organization_id="org-a", owner_user_id="owner-a") == []
    assert restored_hourly.run_count == 1
    assert restored_two_hour.run_count == 1
    assert restored_hourly.next_run_at == hourly_due
    assert restored_two_hour.next_run_at == two_hour_due
    assert restarted.messages == {}

    later = NovaV3Kernel()
    later.now = datetime(2026, 10, 19, 15, 30, tzinfo=timezone.utc)
    only_two_hour = later.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="application_followup",
        timezone_name="America/Chicago",
        frequency="every_two_hours",
    )
    assert later.tick_worker(organization_id="org-a", owner_user_id="owner-a")[0].job_id == only_two_hour.job_id
    later.now = datetime(2026, 10, 19, 17, 5, tzinfo=timezone.utc)
    again_two_hour = later.schedule_job(
        organization_id="org-a",
        owner_user_id="owner-a",
        kind="application_followup",
        timezone_name="America/Chicago",
        frequency="every_two_hours",
    )
    assert again_two_hour.job_id == only_two_hour.job_id
    assert only_two_hour.run_count == 1
    assert only_two_hour.next_run_at == two_hour_due
    assert len(later.jobs) == 1
    assert later.tick_worker(organization_id="org-a", owner_user_id="owner-a") == []
