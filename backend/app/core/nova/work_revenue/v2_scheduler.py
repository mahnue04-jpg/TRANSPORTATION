"""Supervised scheduler foundation. Prepare/generate only. No send, contact, or pay."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.models import (
    NovaWorkEngagement,
    NovaWorkOpportunity,
    NovaWorkRecurringSeries,
    NovaWorkSchedulerJob,
)
from app.core.nova.work_revenue.service import NovaWorkError, _ensure, _new_id, _owner_filter, _record_audit
from app.core.nova.work_revenue.v2_freeze import FROZEN_ENGAGEMENT, FROZEN_OPPORTUNITY, FROZEN_SERIES
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
TITLES = {
    "RECURRING_TASK_PREPARE": "Prepare recurring internal tasks",
    "FOLLOW_UP_REMINDER_PREPARE": "Prepare follow-up reminders",
    "REPORT_PREPARE": "Prepare weekly report draft",
    "INVOICE_PREPARE": "Prepare invoice-support draft",
    "CLIENT_FOLLOW_UP_PREPARE": "Prepare client follow-up draft",
    "OPPORTUNITY_RECHECK_PREPARE": "Prepare opportunity re-check",
}


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
        "owner_user_id": row.owner_user_id,
        "organization_id": row.organization_id,
        "send": False,
        "client_contact": False,
        "external_submission": False,
        "financial_action": False,
        "created_at": _iso(row.created_at),
    }


def _active_series(db: Session, organization_id: str, user: UserContext) -> list[NovaWorkRecurringSeries]:
    rows = _owner_filter(
        db.query(NovaWorkRecurringSeries).filter(NovaWorkRecurringSeries.organization_id == organization_id),
        NovaWorkRecurringSeries,
        user,
    ).all()
    return [row for row in rows if row.status not in FROZEN_SERIES]


def _active_engagements(db: Session, organization_id: str, user: UserContext) -> list[NovaWorkEngagement]:
    rows = _owner_filter(
        db.query(NovaWorkEngagement).filter(NovaWorkEngagement.organization_id == organization_id),
        NovaWorkEngagement,
        user,
    ).all()
    return [row for row in rows if row.status not in FROZEN_ENGAGEMENT]


def _active_opportunities(db: Session, organization_id: str, user: UserContext) -> list[NovaWorkOpportunity]:
    rows = _owner_filter(
        db.query(NovaWorkOpportunity).filter(NovaWorkOpportunity.organization_id == organization_id),
        NovaWorkOpportunity,
        user,
    ).all()
    return [row for row in rows if row.status not in FROZEN_OPPORTUNITY and not row.archived]


def _should_skip(kind: str, series, engagements, opportunities) -> str | None:
    if kind == "RECURRING_TASK_PREPARE" and not series:
        return "paused_or_archived_recurring_source"
    if kind in {"INVOICE_PREPARE", "REPORT_PREPARE", "CLIENT_FOLLOW_UP_PREPARE", "FOLLOW_UP_REMINDER_PREPARE"} and not engagements:
        return "paused_archived_or_cancelled_engagement"
    if kind == "OPPORTUNITY_RECHECK_PREPARE" and not opportunities:
        return "closed_or_archived_opportunity"
    return None


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
    series = _active_series(db, organization_id, user)
    engagements = _active_engagements(db, organization_id, user)
    opportunities = _active_opportunities(db, organization_id, user)
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
        skip_reason = _should_skip(kind, series, engagements, opportunities)
        status = "SKIPPED" if skip_reason else "PREPARED"
        notes = (
            f"Skipped: {skip_reason}. Prepare only. Nova did not send, contact a client, submit, or execute payment."
            if skip_reason
            else "Prepare only. Nova did not send, contact a client, submit, or execute payment."
        )
        row = NovaWorkSchedulerJob(
            job_id=_new_id("NWJ-"),
            organization_id=organization_id,
            owner_user_id=user.user_id,
            job_kind=kind,
            period_key=key,
            status=status,
            timezone=tz,
            due_at=_zone_now(tz),
            title=TITLES[kind],
            notes=notes,
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            skipped.append({"job_kind": kind, "period_key": key, "reason": "duplicate_period"})
            continue
        _record_audit(
            db,
            organization_id=organization_id,
            user=user,
            event_type="SCHEDULER_JOB_PREPARED",
            summary=f"{status} {kind} for {key} in {tz}. No live action.",
            ref_id=row.job_id,
            entity_type="scheduler_job",
            actor_category="NOVA",
            new_state=status,
            source="v2_scheduler",
        )
        created.append(job_out(row))
        if skip_reason:
            skipped.append({"job_kind": kind, "period_key": key, "reason": skip_reason, "job_id": row.job_id})
    db.commit()
    return {
        "timezone": tz,
        "created": created,
        "skipped": skipped,
        "paused_engagements_ignored": sorted(row.engagement_id for row in _owner_filter(
            db.query(NovaWorkEngagement).filter(NovaWorkEngagement.organization_id == organization_id),
            NovaWorkEngagement,
            user,
        ).all() if row.status in FROZEN_ENGAGEMENT),
        "paused_opportunities_ignored": sorted(row.opportunity_id for row in _owner_filter(
            db.query(NovaWorkOpportunity).filter(NovaWorkOpportunity.organization_id == organization_id),
            NovaWorkOpportunity,
            user,
        ).all() if row.status in FROZEN_OPPORTUNITY or row.archived),
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
