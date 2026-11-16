"""Durable Google Calendar sync outbox — enqueue, lease, stale suppression."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.nova.growth_agent.models import GaAppointment, GaCalendarConnection, GaCalendarSyncJob
from app.core.nova.growth_agent.providers.google_calendar_requests import (
    CalendarBinding,
    event_id_for,
)
from app.core.nova.growth_agent.providers.google_calendar_transport import (
    CalendarTransportResult,
    GoogleCalendarTransport,
)

logger = logging.getLogger("amicor.nova.growth_agent.calendar_sync")

DEFAULT_LEASE_SECONDS = 30
DEFAULT_MAX_ATTEMPTS = 8
TERMINAL_STATUSES = frozenset({"confirmed", "failed", "suppressed", "stale"})
ACTIVE_BOOKING = frozenset({"confirmed", "rescheduled"})


def _utcnow() -> datetime:
    return datetime.utcnow()


def _backoff_seconds(attempt_number: int) -> int:
    return min(300, 2 ** max(1, int(attempt_number)))


def _job_dict(job: GaCalendarSyncJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "organization_id": job.organization_id,
        "appointment_id": job.appointment_id,
        "event_id": job.event_id,
        "action": job.action,
        "operation_version": job.operation_version,
        "status": job.status,
        "attempt_number": job.attempt_number,
        "last_error_code": job.last_error_code,
        "starts_at_utc": job.starts_at_utc.isoformat() + "Z" if job.starts_at_utc else None,
        "ends_at_utc": job.ends_at_utc.isoformat() + "Z" if job.ends_at_utc else None,
    }


def _next_operation_version(db: Session, *, org_id: str, appointment_id: str) -> int:
    current = (
        db.query(func.max(GaCalendarSyncJob.operation_version))
        .filter(
            GaCalendarSyncJob.organization_id == org_id,
            GaCalendarSyncJob.appointment_id == appointment_id,
        )
        .scalar()
    )
    return int(current or 0) + 1


def _connection_ok(connection: GaCalendarConnection | None) -> bool:
    if connection is None:
        return False
    return (connection.status or "").lower() == "connected" and bool(connection.calendar_id)


def mark_suppressed(
    db: Session,
    *,
    org_id: str,
    appointment_id: str,
    action: str,
    connection: GaCalendarConnection | None,
    reason: str,
) -> dict[str, Any]:
    """Record a suppressed sync job when calendar is not wired."""
    version = _next_operation_version(db, org_id=org_id, appointment_id=appointment_id)
    event_id = event_id_for(org_id, appointment_id)
    job = GaCalendarSyncJob(
        id=str(uuid4()),
        organization_id=org_id,
        appointment_id=appointment_id,
        connection_id=connection.id if connection else "none",
        calendar_id=(connection.calendar_id if connection and connection.calendar_id else "none"),
        event_id=event_id,
        action=action,
        operation_version=version,
        status="suppressed",
        last_error_code=reason,
        payload_json={"reason": reason},
        result_json={"suppressed": True},
    )
    db.add(job)
    db.flush()
    return _job_dict(job)


def enqueue_sync(
    db: Session,
    *,
    org_id: str,
    appointment_id: str,
    action: str,
    starts_at: datetime | None,
    ends_at: datetime | None,
    connection: GaCalendarConnection | None,
) -> dict[str, Any]:
    """Enqueue create/reschedule/cancel; stable event_id, monotonic operation_version."""
    if action not in {"create", "reschedule", "cancel"}:
        raise ValueError("INVALID_ACTION")
    if not _connection_ok(connection):
        return mark_suppressed(
            db,
            org_id=org_id,
            appointment_id=appointment_id,
            action=action,
            connection=connection,
            reason="NOT_CONNECTED" if connection else "NO_CONNECTION",
        )

    assert connection is not None
    version = _next_operation_version(db, org_id=org_id, appointment_id=appointment_id)
    event_id = event_id_for(org_id, appointment_id)
    start_naive = starts_at.replace(tzinfo=None) if starts_at and starts_at.tzinfo else starts_at
    end_naive = ends_at.replace(tzinfo=None) if ends_at and ends_at.tzinfo else ends_at

    existing = (
        db.query(GaCalendarSyncJob)
        .filter_by(
            organization_id=org_id,
            appointment_id=appointment_id,
            operation_version=version,
        )
        .one_or_none()
    )
    if existing:
        return {**_job_dict(existing), "idempotent": True}

    job = GaCalendarSyncJob(
        id=str(uuid4()),
        organization_id=org_id,
        appointment_id=appointment_id,
        connection_id=connection.id,
        calendar_id=connection.calendar_id or "",
        event_id=event_id,
        action=action,
        operation_version=version,
        status="pending",
        starts_at_utc=start_naive,
        ends_at_utc=end_naive,
        payload_json={"action": action},
    )
    db.add(job)
    try:
        # Nested savepoint — never wipe sibling appointment work on conflict.
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        row = (
            db.query(GaCalendarSyncJob)
            .filter_by(
                organization_id=org_id,
                appointment_id=appointment_id,
                operation_version=version,
            )
            .one()
        )
        return {**_job_dict(row), "idempotent": True}
    return _job_dict(job)


def _latest_version(db: Session, org_id: str, appointment_id: str) -> int:
    return int(
        db.query(func.max(GaCalendarSyncJob.operation_version))
        .filter(
            GaCalendarSyncJob.organization_id == org_id,
            GaCalendarSyncJob.appointment_id == appointment_id,
        )
        .scalar()
        or 0
    )


def _appointment(db: Session, org_id: str, appointment_id: str) -> GaAppointment | None:
    return (
        db.query(GaAppointment)
        .filter_by(organization_id=org_id, id=appointment_id)
        .one_or_none()
    )


def _mark_stale(job: GaCalendarSyncJob, *, reason: str) -> dict[str, Any]:
    job.status = "stale"
    job.last_error_code = reason
    job.claimed_by = None
    job.claimed_at = None
    job.lease_expires_at = None
    job.result_json = {**(job.result_json or {}), "stale_reason": reason}
    return _job_dict(job)


def _mark_confirmed(job: GaCalendarSyncJob, result: CalendarTransportResult) -> dict[str, Any]:
    job.status = "confirmed"
    job.confirmed_at = _utcnow()
    job.last_error_code = None
    job.provider_etag = result.etag
    job.claimed_by = None
    job.claimed_at = None
    job.lease_expires_at = None
    job.available_at = None
    job.result_json = {
        "outcome": result.outcome,
        "http_status": result.http_status,
        "verified": True,
    }
    return _job_dict(job)


def _should_apply(job: GaCalendarSyncJob, appt: GaAppointment | None, latest: int) -> str | None:
    if job.operation_version < latest:
        return "NEWER_VERSION_EXISTS"
    if job.action in {"create", "reschedule"} and appt and appt.status == "cancelled":
        return "APPOINTMENT_CANCELLED"
    if job.action == "cancel" and appt and appt.status in ACTIVE_BOOKING:
        return "CANCEL_SUPERSEDED_BY_REBOOK"
    return None


def _process_one(
    db: Session,
    job: GaCalendarSyncJob,
    transport: GoogleCalendarTransport,
) -> dict[str, Any]:
    if job.status in TERMINAL_STATUSES:
        return _job_dict(job)

    latest = _latest_version(db, job.organization_id, job.appointment_id)
    appt = _appointment(db, job.organization_id, job.appointment_id)
    stale_reason = _should_apply(job, appt, latest)
    if stale_reason:
        return _mark_stale(job, reason=stale_reason)

    if job.action == "cancel" and appt and appt.status in ACTIVE_BOOKING:
        newer_create = (
            db.query(GaCalendarSyncJob)
            .filter(
                GaCalendarSyncJob.organization_id == job.organization_id,
                GaCalendarSyncJob.appointment_id == job.appointment_id,
                GaCalendarSyncJob.operation_version > job.operation_version,
                GaCalendarSyncJob.action.in_(["create", "reschedule"]),
                GaCalendarSyncJob.status.in_(["pending", "running", "retrying", "confirmed"]),
            )
            .count()
        )
        if newer_create:
            return _mark_stale(job, reason="CANCEL_SUPERSEDED_BY_REBOOK")

    binding = CalendarBinding(job.organization_id, job.calendar_id)

    def _aware(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        from datetime import timezone

        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    start = _aware(job.starts_at_utc)
    end = _aware(job.ends_at_utc)

    result: CalendarTransportResult
    if job.action == "create":
        if start is None or end is None:
            job.status = "failed"
            job.last_error_code = "MISSING_TIMES"
            return _job_dict(job)
        result = transport.create_event(
            binding=binding,
            organization_id=job.organization_id,
            appointment_id=job.appointment_id,
            starts_at=start,
            ends_at=end,
        )
    elif job.action == "reschedule":
        if start is None or end is None:
            job.status = "failed"
            job.last_error_code = "MISSING_TIMES"
            return _job_dict(job)
        result = transport.patch_event(
            binding=binding,
            organization_id=job.organization_id,
            appointment_id=job.appointment_id,
            starts_at=start,
            ends_at=end,
        )
    else:
        result = transport.delete_event(
            binding=binding,
            organization_id=job.organization_id,
            appointment_id=job.appointment_id,
        )

    if result.outcome == "timeout_after_write" and job.action == "create":
        verified = transport.get_event(
            binding=binding,
            organization_id=job.organization_id,
            event_id=job.event_id,
        )
        if verified.ok and verified.event_id == job.event_id:
            from app.core.nova.growth_agent.providers.google_calendar_transport import _times_match

            if _times_match(start, end, verified.starts_at_utc, verified.ends_at_utc):
                return _mark_confirmed(job, verified)

    if result.ok:
        return _mark_confirmed(job, result)

    if result.error_code == "CREDENTIALS_EXPIRED":
        job.status = "failed"
        job.last_error_code = "CREDENTIALS_EXPIRED"
        job.claimed_by = None
        job.lease_expires_at = None
        return _job_dict(job)

    if result.outcome == "suppressed":
        job.status = "suppressed"
        job.last_error_code = result.error_code
        job.claimed_by = None
        job.lease_expires_at = None
        return _job_dict(job)

    job.attempt_number = int(job.attempt_number or 0) + 1
    job.last_error_code = result.error_code
    job.claimed_by = None
    job.claimed_at = None
    job.lease_expires_at = None

    if job.attempt_number >= int(job.max_attempts or DEFAULT_MAX_ATTEMPTS):
        job.status = "failed"
        return _job_dict(job)

    delay = _backoff_seconds(job.attempt_number)
    if result.error_code == "RATE_LIMITED":
        delay = max(delay, 60)
    job.status = "retrying" if result.outcome in {"retryable", "timeout_after_write"} else "retrying"
    job.available_at = _utcnow() + timedelta(seconds=delay)
    return _job_dict(job)


def claim_sync_jobs(
    db: Session,
    *,
    worker_id: str,
    limit: int,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    organization_id: str | None = None,
) -> list[GaCalendarSyncJob]:
    now = _utcnow()
    batch = max(1, min(int(limit), 100))
    claim_token = f"{worker_id}:{uuid4().hex[:8]}"
    lease_until = now + timedelta(seconds=max(5, lease_seconds))

    available = (GaCalendarSyncJob.available_at.is_(None)) | (GaCalendarSyncJob.available_at <= now)
    lease_free = (
        (GaCalendarSyncJob.claimed_by.is_(None))
        | (GaCalendarSyncJob.lease_expires_at.is_(None))
        | (GaCalendarSyncJob.lease_expires_at < now)
    )
    q = db.query(GaCalendarSyncJob.id).filter(
        GaCalendarSyncJob.status.in_(["pending", "retrying", "running"]),
        available,
        lease_free,
    )
    if organization_id:
        q = q.filter(GaCalendarSyncJob.organization_id == organization_id)
    candidate_ids = [
        r[0] for r in q.order_by(GaCalendarSyncJob.created_at.asc()).limit(batch).all()
    ]
    if not candidate_ids:
        return []

    claimed_ids: list[str] = []
    for job_id in candidate_ids:
        row = (
            db.query(GaCalendarSyncJob)
            .filter(
                GaCalendarSyncJob.id == job_id,
                GaCalendarSyncJob.status.in_(["pending", "retrying", "running"]),
                available,
                lease_free,
            )
            .with_for_update(of=GaCalendarSyncJob)
            .one_or_none()
        )
        if row is None:
            continue
        row.status = "running"
        row.claimed_by = claim_token
        row.claimed_at = now
        row.lease_expires_at = lease_until
        claimed_ids.append(row.id)
    db.flush()
    if not claimed_ids:
        return []
    return (
        db.query(GaCalendarSyncJob)
        .filter(GaCalendarSyncJob.id.in_(claimed_ids), GaCalendarSyncJob.claimed_by == claim_token)
        .all()
    )


def process_sync_batch(
    db: Session,
    *,
    worker_id: str,
    limit: int,
    transport: GoogleCalendarTransport,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    organization_id: str | None = None,
) -> dict[str, Any]:
    claimed = claim_sync_jobs(
        db,
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
        organization_id=organization_id,
    )
    results = [_process_one(db, job, transport) for job in claimed]
    return {
        "worker_id": worker_id,
        "claimed": len(claimed),
        "processed": len(results),
        "results": results,
    }