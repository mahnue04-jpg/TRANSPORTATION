"""Synthetic V3 scheduler worker. No production cron or daemon."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags
from app.core.nova.v3.models import ScheduledJob

JOB_KINDS = (
    "opportunity_refresh",
    "application_followup",
    "client_followup",
    "work_deadline",
    "recurring_work",
    "invoice_followup",
    "payment_reconciliation",
    "stale_engagement_check",
    "credential_expiry_check",
    "connector_health_check",
)


@dataclass
class JobRun:
    run_id: str
    job_id: str
    organization_id: str
    owner_user_id: str
    status: str
    detail: dict[str, Any] = field(default_factory=dict)


def next_run(frequency: str, timezone_name: str, now: datetime) -> datetime:
    token = str(timezone_name or "").strip()
    if not token:
        raise V3Error("TIMEZONE_REQUIRED", "explicit IANA timezone is required", http_status=400)
    try:
        zone = ZoneInfo(token)
    except ZoneInfoNotFoundError as exc:
        raise V3Error("TIMEZONE_INVALID", "timezone must be an explicit IANA name", http_status=400) from exc
    local = now.astimezone(zone)
    if frequency == "weekly":
        return (local + timedelta(days=7)).astimezone(now.tzinfo)
    if frequency == "monthly":
        return (local + timedelta(days=30)).astimezone(now.tzinfo)
    return (local + timedelta(days=1)).astimezone(now.tzinfo)


def backoff_seconds(attempts: int) -> int:
    return min(60 * (2 ** max(attempts - 1, 0)), 3600)


def ensure_job_fields(job: ScheduledJob) -> ScheduledJob:
    if not hasattr(job, "lease_owner"):
        job.lease_owner = None  # type: ignore[attr-defined]
        job.lease_expires_at = None  # type: ignore[attr-defined]
        job.attempts = 0  # type: ignore[attr-defined]
        job.max_attempts = 3  # type: ignore[attr-defined]
        job.next_run_at = None  # type: ignore[attr-defined]
        job.dead_letter = False  # type: ignore[attr-defined]
        job.run_history = []  # type: ignore[attr-defined]
        job.frequency = "daily"  # type: ignore[attr-defined]
        job.paused_reason = None  # type: ignore[attr-defined]
    return job


def lease_job(job: ScheduledJob, *, worker_id: str, now: datetime, ttl: timedelta) -> ScheduledJob:
    if live_flags()["BACKGROUND_WORKER_ENABLED"]:
        raise V3Error("LIVE_DISABLED", "production background worker cannot start")
    ensure_job_fields(job)
    if job.status in {"PAUSED", "CANCELLED", "ARCHIVED"}:
        raise V3Error("JOB_NOT_ACTIVE", f"cannot lease {job.status}")
    if job.dead_letter:  # type: ignore[attr-defined]
        raise V3Error("DEAD_LETTER", "job is in dead-letter")
    expires = job.lease_expires_at  # type: ignore[attr-defined]
    owner = job.lease_owner  # type: ignore[attr-defined]
    if owner and expires and expires > now and owner != worker_id:
        raise V3Error("LEASE_MISMATCH", "job is leased by another worker")
    job.lease_owner = worker_id  # type: ignore[attr-defined]
    job.lease_expires_at = now + ttl  # type: ignore[attr-defined]
    job.status = "LEASED"
    return job


def apply_retry(job: ScheduledJob, *, now: datetime) -> ScheduledJob:
    ensure_job_fields(job)
    job.attempts += 1  # type: ignore[attr-defined]
    job.retry_count += 1
    job.lease_owner = None  # type: ignore[attr-defined]
    job.status = "PREPARED"
    job.next_run_at = now + timedelta(seconds=backoff_seconds(int(job.attempts)))  # type: ignore[attr-defined]
    if int(job.attempts) >= int(job.max_attempts):  # type: ignore[attr-defined]
        job.dead_letter = True  # type: ignore[attr-defined]
        job.status = "DEAD_LETTER"
    return job


def recover_stale(job: ScheduledJob, *, now: datetime) -> ScheduledJob:
    ensure_job_fields(job)
    expires = job.lease_expires_at  # type: ignore[attr-defined]
    if job.status == "LEASED" and expires is not None and expires <= now:
        job.lease_owner = None  # type: ignore[attr-defined]
        job.status = "PREPARED"
        job.last_error = "stale lock recovered"
    return job
