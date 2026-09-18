"""Supervised scheduler foundation. Prepare/generate only. No send, contact, or pay."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.materials import sanitize_untrusted
from app.core.nova.work_revenue.models import (
    NovaWorkEngagement,
    NovaWorkOpportunity,
    NovaWorkRecurringSeries,
    NovaWorkSchedulerJob,
)
from app.core.nova.work_revenue.service import NovaWorkError, _ensure, _new_id, _owner_filter, _record_audit
from app.helpers import now

JOB_KINDS = (
    "RECURRING_TASK_PREPARE",
    "FOLLOW_UP_REMINDER_PREPARE",
    "REPORT_PREPARE",
    "INVOICE_PREPARE",
    "CLIENT_FOLLOW_UP_PREPARE",
    "OPPORTUNITY_RECHECK_PREPARE",
)

JOB_STATUSES = ("PREPARED", "SKIPPED", "CANCELED")
DEFAULT_TZ = "America/Chicago"
PAUSED_ENGAGEMENT = {"ARCHIVED", "CANCELLED", "COMPLETE"}
PAUSED_SERIES = {"PAUSED", "ARCHIVED"}
PAUSED_OPP = {"ARCHIVED", "CLOSED", "REJECTED"}


def _validate_timezone(value: str | None) -> str:
    token = (value or DEFAULT_TZ).strip() or DEFAULT_TZ
    try:
        ZoneInfo(token)
    except ZoneInfoNotFoundError as exc:
        raise NovaWorkError("timezone must be an explicit IANA name") from exc
    return token


def _zone_now(timezone_name: str) -> datetime:
    return datetime.now(ZoneInfo(timezone_name))


def period_key(kind: str, timezone_name: str, when: datetime | None = None) -> str:
    stamp = when or _zone_now(timezone_name)
    local = stamp.astimezone(ZoneInfo(timezone_name))
    if kind in {"REPORT_PREPARE", "RECURRING_TASK_PREPARE"}:
        iso = local.isocalendar()
        return f"{kind}:{iso.year}-W{iso.week:02d}"
    if kind == "INVOICE_PREPARE":
        return f"{kind}:{local.strftime('%Y-%m')}"
    return f"{kind}:{local.strftime('%Y-%m-%d')}"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def job_out(row: NovaWorkSchedulerJob) -> dict[str, Any]:
    return {
        "job_id": row.job_id,
        "job_kind": row.job_kind,
        "period_key": row.period_key,
        "status": row.status,
        "timezone": row.timezone,
        "due_at": _iso(row.due_at),
        "engagement_id": row.engagement_id,
        "opportunity_id": row.opportunity_id,
        "supervised_action_id": row.supervised_action_id,
        "title": row.title,
        "notes": row.notes,
        "send": False,
        "client_contact": False,
        "external_submission": False,
        "financial_action": False,
        "created_at": _iso(row.created_at),
    }


def _series_paused(db: Session, organization_id: str, user: UserContext) -> set[str]:
    rows = _owner_filter(
        db.query(NovaWorkRecurringSeries).filter(NovaWorkRecurringSeries.organization_id == organization_id),
        NovaWorkRecurringSeries,
        user,
    ).all()
    return {row.series_id for row in rows if row.status in PAUSED_SERIES}


def _paused_engagements(db: Session, organization_id: str, user: UserContext) -> set[str]:
    rows = _owner_filter(
        db.query(NovaWorkEngagement).filter(NovaWorkEngagement.organization_id == organization_id),
        NovaWorkEngagement,
        user,
    ).all()
    return {row.engagement_id for row in rows if row.status in PAUSED_ENGAGEMENT}


def _paused_opportunities(db: Session, organization_id: str, user: UserContext) -> set[str]:
    rows = _owner_filter(
        db.query(NovaWorkOpportunity).filter(NovaWorkOpportunity.organization_id == organization_id),
        NovaWorkOpportunity,
        user,
    ).all()
    return {row.opportunity_id for row in rows if row.status in PAUSED_OPP or row.archived}


def prepare_jobs(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    timezone_name: str | None = None,
    kinds: list[str] | None = None,
) -> dict[str, Any]:
    _ensure()
    tz = _validate_timezone(timezone_name)
    wanted = [str(item).strip().upper() for item in (kinds or JOB_KINDS)]
    invalid = [item for item in wanted if item not in JOB_KINDS]
    if invalid:
        raise NovaWorkError("Unknown scheduler job kind")
    paused_eng = _paused_engagements(db, organization_id, user)
    paused_opp = _paused_opportunities(db, organization_id, user)
    _series_paused(db, organization_id, user)
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for kind in wanted:
        key = period_key(kind, tz)
        existing = (
            db.query(NovaWorkSchedulerJob)
            .filter(
                NovaWorkSchedulerJob.organization_id == organization_id,
                NovaWorkSchedulerJob.job_kind == kind,
                NovaWorkSchedulerJob.period_key == key,
            )
            .first()
        )
        if existing is not None:
            skipped.append({"job_kind": kind, "period_key": key, "reason": "duplicate_period"})
            continue
        if kind in {"RECURRING_TASK_PREPARE", "INVOICE_PREPARE", "REPORT_PREPARE"} and not paused_eng:
            # Still prepare an org-level reminder even with no engagements; paused work is not sourced.
            pass
        title = {
            "RECURRING_TASK_PREPARE": "Prepare recurring internal tasks",
            "FOLLOW_UP_REMINDER_PREPARE": "Prepare follow-up reminders",
            "REPORT_PREPARE": "Prepare weekly report draft",
            "INVOICE_PREPARE": "Prepare invoice-support draft",
            "CLIENT_FOLLOW_UP_PREPARE": "Prepare client follow-up draft",
            "OPPORTUNITY_RECHECK_PREPARE": "Prepare opportunity re-check",
        }[kind]
        row = NovaWorkSchedulerJob(
            job_id=_new_id("NWJ-"),
            organization_id=organization_id,
            owner_user_id=user.user_id,
            job_kind=kind,
            period_key=key,
            status="PREPARED",
            timezone=tz,
            due_at=_zone_now(tz),
            title=title,
            notes="Prepare only. Nova did not send, contact a client, submit, or execute payment.",
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            skipped.append({"job_kind": kind, "period_key": key, "reason": "duplicate_period"})
            _ensure()
            continue
        _record_audit(
            db,
            organization_id=organization_id,
            user=user,
            event_type="SCHEDULER_JOB_PREPARED",
            summary=f"Prepared {kind} for {key} in {tz}. No live action.",
            ref_id=row.job_id,
            entity_type="scheduler_job",
            actor_category="NOVA",
            new_state="PREPARED",
        )
        created.append(job_out(row))
    db.commit()
    return {
        "timezone": tz,
        "created": created,
        "skipped": skipped,
        "paused_engagements_ignored": sorted(paused_eng),
        "paused_opportunities_ignored": sorted(paused_opp),
        "send": False,
        "client_contact": False,
        "external_submission": False,
        "financial_action": False,
        "continuous_worker": False,
    }


def list_jobs(
    db: Session, *, organization_id: str, user: UserContext, limit: int = 100
) -> list[dict[str, Any]]:
    _ensure()
    rows = (
        _owner_filter(
            db.query(NovaWorkSchedulerJob).filter(NovaWorkSchedulerJob.organization_id == organization_id),
            NovaWorkSchedulerJob,
            user,
        )
        .order_by(NovaWorkSchedulerJob.created_at.desc())
        .limit(max(1, min(int(limit or 100), 200)))
        .all()
    )
    return [job_out(row) for row in rows]
