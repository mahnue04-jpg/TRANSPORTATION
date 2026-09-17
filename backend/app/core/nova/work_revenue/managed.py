"""Internal V1 completion workflows. No live discovery, send, or financial execution."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.flags import engine_guardrails
from app.core.nova.work_revenue.lifecycle import (
    DISCLOSURE_STATUSES,
    ENGAGEMENT_TRANSITIONS,
    FACT_VALUE_STATUSES,
    INVOICE_SUPPORT_STATUSES,
    LIST_MAX_LIMIT,
    clamp_list_limit,
    OCCURRENCE_STATUSES,
    OWNER_ACTION_CATEGORIES,
    QUEUE_STATUSES,
    RECURRING_SERIES_STATUSES,
    REPORT_STATUSES,
    category_for_action,
    normalize_engagement_status,
    normalize_revenue_stage,
    queue_status_for,
)
from app.core.nova.work_revenue.materials import sanitize_untrusted
from app.core.nova.work_revenue.models import (
    NovaWorkBusinessFact,
    NovaWorkDeliverable,
    NovaWorkDisclosurePolicy,
    NovaWorkEngagement,
    NovaWorkInvoiceSupport,
    NovaWorkOwnerAction,
    NovaWorkPlatformPolicy,
    NovaWorkRecurringOccurrence,
    NovaWorkRecurringSeries,
    NovaWorkRevenueEntry,
    NovaWorkTask,
    NovaWorkWeeklyReport,
)
from app.core.nova.work_revenue.owner_facts import FACT_DEFINITIONS, SENSITIVE_FACT_IDS, fact_catalog
from app.core.nova.work_revenue.recurring import next_due_date
from app.core.nova.work_revenue.schemas import (
    OWNER_ACTION_TYPES,
    BusinessFactUpdate,
    DisclosureAcknowledge,
    DisclosurePolicyCreate,
    EngagementUpdate,
    InvoiceSupportCreate,
    InvoiceSupportDecision,
    OwnerActionCreate,
    PlatformPolicyCreate,
    RecurringComplete,
    RecurringSeriesCreate,
    WeeklyReportCreate,
    WeeklyReportDecision,
)
from app.core.nova.work_revenue.service import (
    NovaWorkError,
    _ensure,
    _new_id,
    _owner_filter,
    _record_audit,
    _record_history,
    _validate_amount,
    _validate_date_range,
    get_engagement,
    list_engagements,
    list_opportunities,
    list_owner_actions,
)
from app.core.nova.work_revenue.verified_profile import OWNER_INPUT_REQUIRED
from app.helpers import now

_SECRET_RE = re.compile(
    r"(password|api[_-]?key|secret|ssn|routing number|account number|\b\d{8,}\b|sk_[a-z]+_|pk_[a-z]+_|wh[a-z]{3}_)",
    re.I,
)
_SENSITIVE_READY_VALUES = {
    "MISSING",
    "OWNER_SAYS_READY",
    "OWNER_SAYS_NOT_READY",
    "NOT_APPLICABLE",
    OWNER_INPUT_REQUIRED,
    "[OWNER INPUT REQUIRED]",
}
REPORT_TRANSITIONS = {
    "DRAFT": {"READY_FOR_OWNER_REVIEW", "ARCHIVED"},
    "READY_FOR_OWNER_REVIEW": {"APPROVED_FOR_MANUAL_USE", "DRAFT", "ARCHIVED"},
    "APPROVED_FOR_MANUAL_USE": {"ARCHIVED"},
    "ARCHIVED": set(),
}
INVOICE_TRANSITIONS = {
    "DRAFT": {"READY_FOR_OWNER_REVIEW", "ARCHIVED"},
    "READY_FOR_OWNER_REVIEW": {"APPROVED", "DRAFT", "ARCHIVED"},
    "APPROVED": {"ARCHIVED"},
    "ARCHIVED": set(),
}


def _query(db: Session, model, organization_id: str, user: UserContext):
    return _owner_filter(db.query(model).filter(model.organization_id == organization_id), model, user)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _period_key(frequency: str, when: datetime) -> str:
    token = str(frequency or "weekly").strip().lower()
    if token == "monthly":
        return when.strftime("%Y-%m")
    if token in {"daily", "day"}:
        return when.strftime("%Y-%m-%d")
    iso = when.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _attention_state(row: NovaWorkRecurringSeries) -> str:
    if row.status == "ARCHIVED":
        return "archived"
    if row.status == "PAUSED":
        return "paused"
    due = row.next_work_date
    current = now()
    if due is not None:
        if due.tzinfo is None and current.tzinfo is not None:
            due = due.replace(tzinfo=current.tzinfo)
        if due < current:
            return "overdue"
    return "on_track"


def _series_out(row: NovaWorkRecurringSeries, occurrences: list[NovaWorkRecurringOccurrence] | None = None) -> dict[str, Any]:
    return {
        "series_id": row.series_id,
        "engagement_id": row.engagement_id,
        "template_id": row.template_id,
        "title": row.title,
        "frequency": row.frequency,
        "status": row.status,
        "next_work_date": _iso(row.next_work_date),
        "last_period_key": row.last_period_key,
        "attention_state": _attention_state(row),
        "external_send": False,
        "notifications_enabled": False,
        "calendar_created": False,
        "notes": row.notes,
        "completion_history": [
            {
                "occurrence_id": item.occurrence_id,
                "period_key": item.period_key,
                "status": item.status,
                "task_id": item.task_id,
                "due_date": _iso(item.due_date),
                "completed_at": _iso(item.completed_at),
                "notes": item.notes,
            }
            for item in (occurrences or [])
        ],
    }


def get_engagement_row(db: Session, engagement_id: str, *, organization_id: str, user: UserContext) -> NovaWorkEngagement:
    _ensure()
    row = (
        _query(db, NovaWorkEngagement, organization_id, user)
        .filter(NovaWorkEngagement.engagement_id == engagement_id)
        .first()
    )
    if row is None:
        raise NovaWorkError("Engagement not found", status_code=404)
    return row


def list_work_queue(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    status: str | None = None,
    priority: str | None = None,
    source: str | None = None,
    client: str | None = None,
    owner_action: bool | None = None,
    due_before: datetime | None = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    _ensure()
    rows = list_engagements(db, organization_id=organization_id, user=user)
    wanted = str(status or "").strip().upper() or None
    if wanted == "WAITING_ON_OWNER":
        wanted = "OWNER_ACTION_REQUIRED"
    if wanted and wanted not in QUEUE_STATUSES:
        raise NovaWorkError("Unknown queue status")
    client_token = str(client or "").strip().lower()
    source_token = str(source or "").strip().lower()
    priority_token = str(priority or "").strip().lower()
    filtered: list[dict[str, Any]] = []
    for item in rows:
        item["queue_status"] = queue_status_for(item.get("status"))
        item["source"] = item.get("source")
        item["priority"] = item.get("priority") or "normal"
        if wanted and item["queue_status"] != wanted:
            continue
        if priority_token and str(item.get("priority") or "").lower() != priority_token:
            continue
        if source_token and str(item.get("source") or "").lower() != source_token:
            continue
        if client_token and client_token not in str(item.get("client_name") or "").lower():
            continue
        has_owner = item["queue_status"] == "OWNER_ACTION_REQUIRED" or bool(item.get("blockers"))
        if owner_action is True and not has_owner:
            continue
        if owner_action is False and has_owner:
            continue
        if due_before is not None:
            due_raw = item.get("due_date")
            if not due_raw:
                continue
            due_value = due_raw if isinstance(due_raw, datetime) else datetime.fromisoformat(str(due_raw).replace("Z", "+00:00"))
            compare = due_before
            if due_value.tzinfo is None and compare.tzinfo is not None:
                due_value = due_value.replace(tzinfo=compare.tzinfo)
            if due_value > compare:
                continue
        filtered.append(item)
    reverse = str(order or "desc").lower() != "asc"
    key = str(sort or "updated_at")
    def sort_value(item: dict[str, Any]) -> str:
        if key == "status":
            return str(item.get("queue_status") or "")
        if key == "priority":
            return str(item.get("priority") or "")
        if key == "source":
            return str(item.get("source") or "")
        if key in {"client", "engagement", "client_name"}:
            return str(item.get("client_name") or "")
        if key in {"due_date", "due"}:
            return str(item.get("due_date") or "")
        if key in {"owner_action", "owner_action_required"}:
            return "1" if item.get("queue_status") == "OWNER_ACTION_REQUIRED" else "0"
        return str(item.get("updated_at") or item.get("due_date") or "")
    filtered.sort(key=sort_value, reverse=reverse)
    cap = clamp_list_limit(limit, default=LIST_MAX_LIMIT)
    return filtered[:cap]


def update_engagement(
    db: Session,
    engagement_id: str,
    payload: EngagementUpdate,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    row = get_engagement_row(db, engagement_id, organization_id=organization_id, user=user)
    previous = row.status
    if payload.status is not None:
        target = normalize_engagement_status(payload.status)
        allowed = ENGAGEMENT_TRANSITIONS.get(row.status, set())
        if target != row.status and target not in allowed:
            raise NovaWorkError(f"Cannot transition engagement from {row.status} to {target}")
        row.status = target
        _record_history(
            db,
            organization_id=organization_id,
            user=user,
            ref_type="engagement",
            ref_id=row.engagement_id,
            from_status=previous,
            to_status=target,
            note="Internal queue status change only. No external message was sent.",
        )
        _record_audit(
            db,
            organization_id=organization_id,
            user=user,
            event_type="QUEUE_STATUS_CHANGED",
            summary=f"Engagement {previous} → {target}. APPROVED != SUBMITTED. COMPLETE != PAID.",
            ref_id=row.engagement_id,
            entity_type="engagement",
            actor_category="OWNER",
            previous_state=previous,
            new_state=target,
        )
    if payload.priority is not None:
        row.priority = sanitize_untrusted(payload.priority)[:16] or "normal"
    if payload.blockers is not None:
        row.blockers = sanitize_untrusted(payload.blockers) or None
        if row.blockers and row.status in {"NEW", "NOT_STARTED", "READY", "ACTIVE"}:
            row.status = "BLOCKED"
    if payload.notes is not None:
        row.notes = sanitize_untrusted(payload.notes) or None
    if payload.due_date is not None:
        row.due_date = payload.due_date
    row.updated_at = now()
    db.commit()
    return get_engagement(db, engagement_id, organization_id=organization_id, user=user)


def create_recurring_series(
    db: Session,
    payload: RecurringSeriesCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    engagement = get_engagement_row(db, payload.engagement_id, organization_id=organization_id, user=user)
    frequency = sanitize_untrusted(payload.frequency)[:40] or "weekly"
    duplicate = (
        _query(db, NovaWorkRecurringSeries, organization_id, user)
        .filter(
            NovaWorkRecurringSeries.engagement_id == engagement.engagement_id,
            NovaWorkRecurringSeries.title == sanitize_untrusted(payload.title)[:220],
            NovaWorkRecurringSeries.status != "ARCHIVED",
        )
        .first()
    )
    if duplicate is not None:
        raise NovaWorkError("A matching recurring series already exists for this engagement", status_code=409)
    row = NovaWorkRecurringSeries(
        series_id=_new_id("NWRS-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        engagement_id=engagement.engagement_id,
        template_id=sanitize_untrusted(payload.template_id)[:80] or None,
        title=sanitize_untrusted(payload.title)[:220],
        frequency=frequency,
        status="ACTIVE",
        next_work_date=payload.next_work_date or next_due_date(frequency),
        notes=sanitize_untrusted(payload.notes) or None,
    )
    db.add(row)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="RECURRING_CREATED",
        summary=f"Internal recurring series created. No calendar, email, or customer notice was sent.",
        ref_id=row.series_id,
        entity_type="recurring",
        actor_category="OWNER",
        new_state="ACTIVE",
    )
    db.commit()
    db.refresh(row)
    return _series_out(row, [])


def list_recurring_series(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    _ensure()
    cap = clamp_list_limit(limit, default=LIST_MAX_LIMIT)
    rows = (
        _query(db, NovaWorkRecurringSeries, organization_id, user)
        .order_by(NovaWorkRecurringSeries.updated_at.desc())
        .limit(cap)
        .all()
    )
    series_ids = [row.series_id for row in rows]
    occ_query = _query(db, NovaWorkRecurringOccurrence, organization_id, user)
    if series_ids:
        occ_rows = occ_query.filter(NovaWorkRecurringOccurrence.series_id.in_(series_ids)).all()
    else:
        occ_rows = []
    by_series: dict[str, list[NovaWorkRecurringOccurrence]] = {}
    for item in occ_rows:
        by_series.setdefault(item.series_id, []).append(item)
    return [_series_out(row, by_series.get(row.series_id, [])) for row in rows]


def _get_series(db: Session, series_id: str, *, organization_id: str, user: UserContext) -> NovaWorkRecurringSeries:
    _ensure()
    row = _query(db, NovaWorkRecurringSeries, organization_id, user).filter(NovaWorkRecurringSeries.series_id == series_id).first()
    if row is None:
        raise NovaWorkError("Recurring series not found", status_code=404)
    return row


def generate_recurring_occurrence(
    db: Session,
    series_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    row = _get_series(db, series_id, organization_id=organization_id, user=user)
    if row.status != "ACTIVE":
        raise NovaWorkError("Recurring work can be generated only while ACTIVE")
    due = row.next_work_date or now()
    period = _period_key(row.frequency, due)
    existing = (
        _query(db, NovaWorkRecurringOccurrence, organization_id, user)
        .filter(
            NovaWorkRecurringOccurrence.series_id == row.series_id,
            NovaWorkRecurringOccurrence.period_key == period,
        )
        .first()
    )
    if existing is not None:
        raise NovaWorkError("An occurrence already exists for this period", status_code=409)
    task = NovaWorkTask(
        task_id=_new_id("NWT-"),
        engagement_id=row.engagement_id,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        title=f"{row.title} ({period})",
        responsible_party="NOVA",
        classification="NOVA",
        status="READY",
        priority="normal",
        due_date=due,
        review_required=True,
        description="Generated from an internal recurring series. Nova will not send this work externally.",
    )
    db.add(task)
    db.flush()
    occurrence = NovaWorkRecurringOccurrence(
        occurrence_id=_new_id("NWRO-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        series_id=row.series_id,
        engagement_id=row.engagement_id,
        task_id=task.task_id,
        period_key=period,
        status="OPEN",
        due_date=due,
    )
    db.add(occurrence)
    row.last_period_key = period
    row.updated_at = now()
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="RECURRING_GENERATED",
        summary=f"Internal occurrence {period} generated. No notification was sent.",
        ref_id=occurrence.occurrence_id,
        entity_type="recurring",
        actor_category="NOVA",
        new_state="OPEN",
    )
    db.commit()
    history = _query(db, NovaWorkRecurringOccurrence, organization_id, user).filter(
        NovaWorkRecurringOccurrence.series_id == row.series_id
    ).all()
    return _series_out(row, history)


def set_recurring_status(
    db: Session,
    series_id: str,
    status: str,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    row = _get_series(db, series_id, organization_id=organization_id, user=user)
    target = str(status or "").strip().upper()
    if target not in RECURRING_SERIES_STATUSES:
        raise NovaWorkError("Unknown recurring status")
    previous = row.status
    if previous == "ARCHIVED" and target != "ARCHIVED":
        raise NovaWorkError("Archived recurring series cannot be resumed")
    row.status = target
    row.updated_at = now()
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="QUEUE_STATUS_CHANGED",
        summary=f"Recurring series {previous} → {target}. Internal only.",
        ref_id=row.series_id,
        entity_type="recurring",
        actor_category="OWNER",
        previous_state=previous,
        new_state=target,
    )
    db.commit()
    history = _query(db, NovaWorkRecurringOccurrence, organization_id, user).filter(
        NovaWorkRecurringOccurrence.series_id == row.series_id
    ).all()
    return _series_out(row, history)


def complete_recurring_occurrence(
    db: Session,
    series_id: str,
    payload: RecurringComplete,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    row = _get_series(db, series_id, organization_id=organization_id, user=user)
    open_item = (
        _query(db, NovaWorkRecurringOccurrence, organization_id, user)
        .filter(
            NovaWorkRecurringOccurrence.series_id == row.series_id,
            NovaWorkRecurringOccurrence.status == "OPEN",
        )
        .order_by(NovaWorkRecurringOccurrence.created_at.desc())
        .first()
    )
    if open_item is None:
        raise NovaWorkError("No open occurrence to complete")
    open_item.status = "COMPLETE"
    open_item.completed_at = now()
    open_item.notes = sanitize_untrusted(payload.notes) or None
    open_item.updated_at = now()
    if open_item.task_id:
        task = _query(db, NovaWorkTask, organization_id, user).filter(NovaWorkTask.task_id == open_item.task_id).first()
        if task is not None:
            task.status = "COMPLETE"
            task.completed_at = open_item.completed_at
            task.updated_at = now()
    row.next_work_date = next_due_date(row.frequency, from_time=open_item.due_date or now())
    row.updated_at = now()
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="RECURRING_COMPLETED",
        summary="Internal occurrence completed. COMPLETE != PAID. No customer was contacted.",
        ref_id=open_item.occurrence_id,
        entity_type="recurring",
        actor_category="OWNER",
        previous_state="OPEN",
        new_state="COMPLETE",
    )
    db.commit()
    history = _query(db, NovaWorkRecurringOccurrence, organization_id, user).filter(
        NovaWorkRecurringOccurrence.series_id == row.series_id
    ).all()
    return _series_out(row, history)


def _report_out(row: NovaWorkWeeklyReport) -> dict[str, Any]:
    try:
        body = json.loads(row.body_json or "{}")
    except json.JSONDecodeError:
        body = {}
    return {
        "report_id": row.report_id,
        "engagement_id": row.engagement_id,
        "period_start": _iso(row.period_start),
        "period_end": _iso(row.period_end),
        "status": row.status,
        "title": row.title,
        "body": body,
        "owner_notes": row.owner_notes,
        "send_enabled": False,
        "updated_at": _iso(row.updated_at),
    }


def generate_weekly_report(
    db: Session,
    payload: WeeklyReportCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    _ensure()
    if payload.engagement_id:
        get_engagement_row(db, payload.engagement_id, organization_id=organization_id, user=user)
    period_end = payload.period_end or now()
    period_start = payload.period_start or (period_end - timedelta(days=7))
    _validate_date_range(period_start, period_end)
    engagements = list_engagements(db, organization_id=organization_id, user=user)
    if payload.engagement_id:
        engagements = [item for item in engagements if item.get("engagement_id") == payload.engagement_id]
    opportunities = list_opportunities(db, organization_id=organization_id, user=user)
    actions = list_owner_actions(db, organization_id=organization_id, user=user)
    tasks = _query(db, NovaWorkTask, organization_id, user).limit(LIST_MAX_LIMIT).all()
    if payload.engagement_id:
        tasks = [item for item in tasks if item.engagement_id == payload.engagement_id]
    completed = [item for item in tasks if item.status == "COMPLETE"]
    pending = [item for item in tasks if item.status not in {"COMPLETE", "CANCELLED"}]
    blocked = [item for item in engagements if queue_status_for(item.get("status")) == "BLOCKED" or item.get("blockers")]
    estimated = sum((item.estimated_value or 0) for item in opportunities)
    contracted = sum((item.contract_amount or 0) for item in opportunities)
    received = sum((item.amount_received or 0) for item in opportunities if item.owner_confirmed_payment_received)
    body = {
        "weekly_activity_summary": {
            "engagements": len(engagements),
            "tasks_completed": len(completed),
            "tasks_pending": len(pending),
            "owner_actions_open": len(actions),
        },
        "work_completed": [{"task_id": item.task_id, "title": item.title} for item in completed[:50]],
        "work_pending": [{"task_id": item.task_id, "title": item.title, "status": item.status} for item in pending[:50]],
        "blockers": [{"engagement_id": item.get("engagement_id"), "blockers": item.get("blockers")} for item in blocked],
        "owner_actions_needed": [
            {"action_id": item.action_id, "action_type": item.action_type, "category": item.category}
            for item in actions
        ],
        "opportunity_pipeline": {
            "count": len(opportunities),
            "titles": [sanitize_untrusted(item.opportunity_title)[:220] for item in opportunities[:20]],
        },
        "estimated_revenue": estimated,
        "contracted_revenue": contracted,
        "owner_confirmed_received_revenue": received,
        "disclaimer": "This is an internal draft. Generating a report is not sending it. Nova does not email, SMS, or deliver this to a client.",
        "revenue_rules": "ESTIMATED != CONTRACTED. CONTRACTED != INVOICED. INVOICED != RECEIVED. COMPLETE != PAID.",
    }
    row = NovaWorkWeeklyReport(
        report_id=_new_id("NWWK-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        engagement_id=payload.engagement_id,
        period_start=period_start,
        period_end=period_end,
        status="DRAFT",
        title=f"Weekly managed-service report {period_start.date()} to {period_end.date()}",
        body_json=json.dumps(body),
    )
    db.add(row)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="REPORT_CREATED",
        summary="Internal weekly report draft generated. Nothing was sent.",
        ref_id=row.report_id,
        entity_type="report",
        actor_category="NOVA",
        new_state="DRAFT",
    )
    create_owner_action(
        db,
        OwnerActionCreate(
            action_type="REVIEW_WEEKLY_REPORT",
            category="REVIEW_WEEKLY_REPORT",
            explanation="Review the internal weekly report draft. Approval does not send it.",
            engagement_id=payload.engagement_id,
            ref_type="report",
            ref_id=row.report_id,
        ),
        organization_id=organization_id,
        user=user,
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return _report_out(row)


def list_weekly_reports(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    _ensure()
    rows = (
        _query(db, NovaWorkWeeklyReport, organization_id, user)
        .order_by(NovaWorkWeeklyReport.updated_at.desc())
        .limit(clamp_list_limit(limit, default=LIST_MAX_LIMIT))
        .all()
    )
    return [_report_out(item) for item in rows]


def _get_report(db: Session, report_id: str, *, organization_id: str, user: UserContext) -> NovaWorkWeeklyReport:
    row = _query(db, NovaWorkWeeklyReport, organization_id, user).filter(NovaWorkWeeklyReport.report_id == report_id).first()
    if row is None:
        raise NovaWorkError("Weekly report not found", status_code=404)
    return row


def transition_weekly_report(
    db: Session,
    report_id: str,
    target: str,
    payload: WeeklyReportDecision,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    row = _get_report(db, report_id, organization_id=organization_id, user=user)
    wanted = str(target or "").strip().upper()
    if wanted not in REPORT_STATUSES:
        raise NovaWorkError("Unknown report status")
    allowed = REPORT_TRANSITIONS.get(row.status, set())
    if wanted not in allowed:
        raise NovaWorkError(f"Cannot transition report from {row.status} to {wanted}")
    previous = row.status
    row.status = wanted
    if payload.owner_notes is not None:
        row.owner_notes = sanitize_untrusted(payload.owner_notes) or None
    row.updated_at = now()
    event = "REPORT_APPROVED" if wanted == "APPROVED_FOR_MANUAL_USE" else "QUEUE_STATUS_CHANGED"
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type=event,
        summary=f"Weekly report {previous} → {wanted}. Approval is for manual use only. Nothing was sent.",
        ref_id=row.report_id,
        entity_type="report",
        actor_category="OWNER",
        previous_state=previous,
        new_state=wanted,
    )
    db.commit()
    db.refresh(row)
    return _report_out(row)


def refuse_report_send() -> None:
    raise NovaWorkError("Weekly reports cannot be sent. Generating a report is not sending it.", status_code=409)


def _invoice_out(row: NovaWorkInvoiceSupport) -> dict[str, Any]:
    try:
        deliverable_ids = json.loads(row.deliverable_ids_json or "[]")
    except json.JSONDecodeError:
        deliverable_ids = []
    return {
        "invoice_support_id": row.invoice_support_id,
        "engagement_id": row.engagement_id,
        "client_name": row.client_name,
        "work_period_start": _iso(row.work_period_start),
        "work_period_end": _iso(row.work_period_end),
        "deliverable_ids": deliverable_ids,
        "quantity": row.quantity,
        "rate": row.rate,
        "draft_subtotal": row.draft_subtotal,
        "adjustment_notes": row.adjustment_notes,
        "invoice_required": bool(row.invoice_required),
        "status": row.status,
        "owner_notes": row.owner_notes,
        "stripe_invoice_created": False,
        "payment_intent_created": False,
        "externally_sent": False,
        "money_received": False,
        "printable_summary": {
            "client_name": row.client_name,
            "quantity": row.quantity,
            "rate": row.rate,
            "draft_subtotal": row.draft_subtotal,
            "status": row.status,
            "disclaimer": "Internal invoice-support draft only. Nova does not create Stripe invoices or collect payment.",
        },
    }


def create_invoice_support(
    db: Session,
    payload: InvoiceSupportCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    engagement = get_engagement_row(db, payload.engagement_id, organization_id=organization_id, user=user)
    _validate_date_range(payload.work_period_start, payload.work_period_end)
    quantity = _validate_amount(payload.quantity, label="quantity") or 0
    rate = _validate_amount(payload.rate, label="rate") or 0
    duplicate = (
        _query(db, NovaWorkInvoiceSupport, organization_id, user)
        .filter(
            NovaWorkInvoiceSupport.engagement_id == engagement.engagement_id,
            NovaWorkInvoiceSupport.status == "DRAFT",
            NovaWorkInvoiceSupport.work_period_start == payload.work_period_start,
            NovaWorkInvoiceSupport.work_period_end == payload.work_period_end,
        )
        .first()
    )
    if duplicate is not None:
        raise NovaWorkError("A draft invoice-support record already exists for this period", status_code=409)
    ids = [sanitize_untrusted(item)[:32] for item in (payload.deliverable_ids or []) if item]
    row = NovaWorkInvoiceSupport(
        invoice_support_id=_new_id("NWIS-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        engagement_id=engagement.engagement_id,
        client_name=sanitize_untrusted(payload.client_name)[:220] or engagement.client_name,
        work_period_start=payload.work_period_start,
        work_period_end=payload.work_period_end,
        deliverable_ids_json=json.dumps(ids),
        quantity=quantity,
        rate=rate,
        draft_subtotal=round(quantity * rate, 2),
        adjustment_notes=sanitize_untrusted(payload.adjustment_notes) or None,
        invoice_required=bool(payload.invoice_required),
        status="DRAFT",
        owner_notes=sanitize_untrusted(payload.owner_notes) or None,
    )
    db.add(row)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="INVOICE_SUPPORT_CREATED",
        summary="Internal invoice-support draft stored. No Stripe invoice or charge was created.",
        ref_id=row.invoice_support_id,
        entity_type="invoice_support",
        actor_category="OWNER",
        new_state="DRAFT",
    )
    db.commit()
    db.refresh(row)
    return _invoice_out(row)


def list_invoice_supports(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    _ensure()
    rows = (
        _query(db, NovaWorkInvoiceSupport, organization_id, user)
        .order_by(NovaWorkInvoiceSupport.updated_at.desc())
        .limit(clamp_list_limit(limit, default=LIST_MAX_LIMIT))
        .all()
    )
    return [_invoice_out(item) for item in rows]


def _get_invoice(db: Session, invoice_support_id: str, *, organization_id: str, user: UserContext) -> NovaWorkInvoiceSupport:
    row = (
        _query(db, NovaWorkInvoiceSupport, organization_id, user)
        .filter(NovaWorkInvoiceSupport.invoice_support_id == invoice_support_id)
        .first()
    )
    if row is None:
        raise NovaWorkError("Invoice-support record not found", status_code=404)
    return row


def transition_invoice_support(
    db: Session,
    invoice_support_id: str,
    target: str,
    payload: InvoiceSupportDecision,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    row = _get_invoice(db, invoice_support_id, organization_id=organization_id, user=user)
    wanted = str(target or "").strip().upper()
    if wanted not in INVOICE_SUPPORT_STATUSES:
        raise NovaWorkError("Unknown invoice-support status")
    allowed = INVOICE_TRANSITIONS.get(row.status, set())
    if wanted not in allowed:
        raise NovaWorkError(f"Cannot transition invoice-support from {row.status} to {wanted}")
    previous = row.status
    row.status = wanted
    if payload.owner_notes is not None:
        row.owner_notes = sanitize_untrusted(payload.owner_notes) or None
    row.updated_at = now()
    event = "INVOICE_SUPPORT_APPROVED" if wanted == "APPROVED" else "QUEUE_STATUS_CHANGED"
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type=event,
        summary=f"Invoice-support {previous} → {wanted}. APPROVED != PAID. No invoice was sent.",
        ref_id=row.invoice_support_id,
        entity_type="invoice_support",
        actor_category="OWNER",
        previous_state=previous,
        new_state=wanted,
    )
    db.commit()
    db.refresh(row)
    return _invoice_out(row)


def refuse_invoice_send() -> None:
    raise NovaWorkError("Invoice-support records cannot be sent or charged.", status_code=409)


def reconciliation(db: Session, *, organization_id: str, user: UserContext) -> dict[str, Any]:
    _ensure()
    entries = (
        _query(db, NovaWorkRevenueEntry, organization_id, user)
        .order_by(NovaWorkRevenueEntry.updated_at.desc())
        .limit(LIST_MAX_LIMIT)
        .all()
    )
    opportunities = list_opportunities(db, organization_id=organization_id, user=user, limit=LIST_MAX_LIMIT)
    invoices = (
        _query(db, NovaWorkInvoiceSupport, organization_id, user)
        .order_by(NovaWorkInvoiceSupport.updated_at.desc())
        .limit(LIST_MAX_LIMIT)
        .all()
    )

    def _sum(predicate) -> float:
        return round(sum(item.amount for item in entries if predicate(item)), 2)

    estimated = _sum(lambda item: item.stage == "ESTIMATED")
    quoted = _sum(lambda item: item.stage == "QUOTED")
    contracted = _sum(lambda item: item.stage == "CONTRACTED")
    awaiting_invoice = _sum(lambda item: item.stage in {"CONTRACTED", "INVOICE_DRAFT"})
    manual_invoice = _sum(lambda item: normalize_revenue_stage(item.stage) == "INVOICED_EXTERNALLY")
    awaiting_confirm = _sum(lambda item: item.stage in {"INVOICED_EXTERNALLY", "PAYMENT_PENDING", "OVERDUE"} and not item.owner_confirmed)
    received = _sum(lambda item: bool(item.owner_confirmed) and item.stage in {"PAID", "PARTIALLY_PAID"})
    return {
        "estimated_pipeline": estimated,
        "quoted": quoted,
        "contracted": contracted,
        "awaiting_invoice": awaiting_invoice,
        "manually_recorded_invoice": manual_invoice,
        "awaiting_owner_payment_confirmation": awaiting_confirm,
        "owner_confirmed_received": received,
        "authoritative_source": "nova_work_revenue_entries",
        "opportunity_context": {
            "estimated_pipeline": round(sum((item.estimated_value or 0) for item in opportunities), 2),
            "quoted": round(sum((item.quoted_amount or 0) for item in opportunities), 2),
            "contracted": round(sum((item.contract_amount or 0) for item in opportunities), 2),
            "owner_confirmed_received": round(
                sum((item.amount_received or 0) for item in opportunities if item.owner_confirmed_payment_received),
                2,
            ),
            "note": "Opportunity fields are pipeline context only. They are not added into the authoritative totals.",
        },
        "invoice_support_context": {
            "draft_subtotal": round(
                sum(item.draft_subtotal for item in invoices if item.status in {"DRAFT", "READY_FOR_OWNER_REVIEW"}),
                2,
            ),
            "note": "Invoice-support drafts are not Stripe invoices and are not received revenue.",
        },
        "rules": {
            "APPROVED_EQUALS_SUBMITTED": False,
            "APPROVED_EQUALS_PAID": False,
            "COMPLETE_EQUALS_PAID": False,
            "owner_confirmation_required_for_received": True,
            "inferred_from_contract": False,
            "inferred_from_task_completion": False,
            "inferred_from_draft_invoice": False,
            "inferred_from_approval": False,
            "opportunity_fields_are_authoritative": False,
        },
        "disclaimer": "ESTIMATED != CONTRACTED. CONTRACTED != INVOICED. INVOICED != RECEIVED. Nova does not collect payment.",
        "guardrails": engine_guardrails(),
    }


def create_owner_action(
    db: Session,
    payload: OwnerActionCreate,
    *,
    organization_id: str,
    user: UserContext,
    commit: bool = True,
) -> dict[str, Any]:
    _ensure()
    action_type = str(payload.action_type or "").strip().upper()
    if action_type not in OWNER_ACTION_TYPES:
        raise NovaWorkError("Unknown owner-action type")
    category = str(payload.category or category_for_action(action_type)).strip().upper()
    if category not in OWNER_ACTION_CATEGORIES:
        category = "PROVIDE_INFORMATION"
    row = NovaWorkOwnerAction(
        action_id=_new_id("NWAO-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        opportunity_id=payload.opportunity_id,
        application_id=payload.application_id,
        engagement_id=payload.engagement_id,
        ref_type=sanitize_untrusted(payload.ref_type)[:32] or None,
        ref_id=sanitize_untrusted(payload.ref_id)[:32] or None,
        action_type=action_type,
        display_label="OWNER ACTION REQUIRED",
        explanation=sanitize_untrusted(payload.explanation) or "Owner action is required. Approval does not execute an external action.",
        status="OPEN",
        category=category,
    )
    db.add(row)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="OWNER_ACTION_REQUIRED",
        summary=f"OWNER ACTION REQUIRED: {action_type}. Approval is informational only.",
        ref_id=row.action_id,
        entity_type="owner_action",
        actor_category="NOVA",
        new_state="OPEN",
    )
    if commit:
        db.commit()
        db.refresh(row)
    return {
        "action_id": row.action_id,
        "action_type": row.action_type,
        "category": row.category,
        "status": row.status,
        "explanation": row.explanation,
        "opportunity_id": row.opportunity_id,
        "application_id": row.application_id,
        "engagement_id": row.engagement_id,
        "ref_type": row.ref_type,
        "ref_id": row.ref_id,
        "display_label": row.display_label,
        "executes_externally": False,
    }


def stored_facts(db: Session, *, organization_id: str, user: UserContext) -> dict[str, dict[str, Any]]:
    _ensure()
    rows = _query(db, NovaWorkBusinessFact, organization_id, user).all()
    current = now()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        status = row.value_status
        if row.expiration_date and row.expiration_date < current:
            status = "EXPIRED"
        out[row.fact_key] = {
            "value_status": status,
            "value_display": row.value_display,
            "verification_date": _iso(row.verification_date),
            "expiration_date": _iso(row.expiration_date),
            "source_description": row.source_description,
            "notes": row.notes,
        }
    return out


def owner_fact_catalog(db: Session, *, organization_id: str, user: UserContext, applicant_party: str = "AMICOR") -> dict[str, Any]:
    return fact_catalog(applicant_party=applicant_party, stored=stored_facts(db, organization_id=organization_id, user=user))


def update_business_fact(
    db: Session,
    fact_key: str,
    payload: BusinessFactUpdate,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    _ensure()
    key = str(fact_key or "").strip()
    definition = next((item for item in FACT_DEFINITIONS if item["fact_id"] == key), None)
    if definition is None:
        raise NovaWorkError("Unknown business fact key", status_code=404)
    status = str(payload.value_status or "OWNER_PROVIDED").strip().upper()
    if status not in FACT_VALUE_STATUSES:
        raise NovaWorkError("Unknown fact value status")
    display = sanitize_untrusted(payload.value_display)[:400] if payload.value_display else OWNER_INPUT_REQUIRED
    if _SECRET_RE.search(display or ""):
        raise NovaWorkError("Business facts cannot store secrets, tax identifiers, or banking credentials")
    if key in SENSITIVE_FACT_IDS:
        token = (display or "").strip()
        if token not in _SENSITIVE_READY_VALUES:
            raise NovaWorkError("Sensitive facts accept readiness flags only. Do not store numbers or credentials.")
        display = token or OWNER_INPUT_REQUIRED
    if status == "MISSING":
        display = OWNER_INPUT_REQUIRED
    _validate_date_range(payload.verification_date, payload.expiration_date)
    row = _query(db, NovaWorkBusinessFact, organization_id, user).filter(NovaWorkBusinessFact.fact_key == key).first()
    if row is None:
        row = NovaWorkBusinessFact(
            fact_record_id=_new_id("NWBF-"),
            organization_id=organization_id,
            owner_user_id=user.user_id,
            fact_key=key,
            display_label=definition["label"],
        )
        db.add(row)
    previous = row.value_status
    row.value_status = status
    row.value_display = display
    row.verification_date = payload.verification_date
    row.expiration_date = payload.expiration_date
    row.source_description = sanitize_untrusted(payload.source_description)[:400] or None
    row.notes = sanitize_untrusted(payload.notes) or None
    row.updated_at = now()
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="FACT_UPDATED",
        summary=f"Owner fact {key} {previous} → {status}. Nova did not invent this value.",
        ref_id=row.fact_record_id,
        entity_type="business_fact",
        actor_category="OWNER",
        previous_state=previous,
        new_state=status,
    )
    db.commit()
    db.refresh(row)
    return owner_fact_catalog(db, organization_id=organization_id, user=user)


def _disclosure_out(row: NovaWorkDisclosurePolicy) -> dict[str, Any]:
    return {
        "policy_id": row.policy_id,
        "opportunity_id": row.opportunity_id,
        "engagement_id": row.engagement_id,
        "ai_assistance_used": bool(row.ai_assistance_used),
        "subcontractor_allowed": bool(row.subcontractor_allowed),
        "disclosure_required": bool(row.disclosure_required),
        "owner_acknowledgment_required": bool(row.owner_acknowledgment_required),
        "owner_acknowledged": bool(row.owner_acknowledged),
        "policy_status": row.policy_status,
        "notes": row.notes,
        "live_policy_scraped": False,
        "terms_accepted_automatically": False,
    }


def create_disclosure_policy(
    db: Session,
    payload: DisclosurePolicyCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    _ensure()
    status = "MANUAL_REVIEW_REQUIRED" if payload.owner_acknowledgment_required else "DRAFT"
    row = NovaWorkDisclosurePolicy(
        policy_id=_new_id("NWDP-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        opportunity_id=payload.opportunity_id,
        engagement_id=payload.engagement_id,
        ai_assistance_used=bool(payload.ai_assistance_used),
        subcontractor_allowed=bool(payload.subcontractor_allowed),
        disclosure_required=bool(payload.disclosure_required),
        owner_acknowledgment_required=bool(payload.owner_acknowledgment_required),
        owner_acknowledged=False,
        policy_status=status,
        notes=sanitize_untrusted(payload.notes) or None,
    )
    db.add(row)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="OWNER_ACTION_REQUIRED",
        summary="Internal AI/subcontractor disclosure policy stored. No third-party terms were accepted.",
        ref_id=row.policy_id,
        entity_type="disclosure",
        actor_category="NOVA",
        new_state=status,
    )
    db.commit()
    db.refresh(row)
    return _disclosure_out(row)


def list_disclosure_policies(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    _ensure()
    rows = (
        _query(db, NovaWorkDisclosurePolicy, organization_id, user)
        .order_by(NovaWorkDisclosurePolicy.updated_at.desc())
        .limit(clamp_list_limit(limit, default=LIST_MAX_LIMIT))
        .all()
    )
    return [_disclosure_out(item) for item in rows]


def acknowledge_disclosure(
    db: Session,
    policy_id: str,
    payload: DisclosureAcknowledge,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    row = _query(db, NovaWorkDisclosurePolicy, organization_id, user).filter(NovaWorkDisclosurePolicy.policy_id == policy_id).first()
    if row is None:
        raise NovaWorkError("Disclosure policy not found", status_code=404)
    if payload.owner_acknowledged is not True:
        raise NovaWorkError("Owner acknowledgment must be explicit")
    previous = row.policy_status
    row.owner_acknowledged = True
    row.policy_status = "ACKNOWLEDGED"
    if payload.notes is not None:
        row.notes = sanitize_untrusted(payload.notes) or None
    row.updated_at = now()
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="DISCLOSURE_ACKNOWLEDGED",
        summary="Owner acknowledged the internal disclosure policy. No external terms were accepted.",
        ref_id=row.policy_id,
        entity_type="disclosure",
        actor_category="OWNER",
        previous_state=previous,
        new_state="ACKNOWLEDGED",
    )
    db.commit()
    db.refresh(row)
    return _disclosure_out(row)


def platform_policy_catalog() -> dict[str, Any]:
    return {
        "flags": [
            "LOGIN_REQUIRED",
            "CAPTCHA_REQUIRED",
            "HUMAN_SUBMISSION_ONLY",
            "TERMS_RESTRICT_AUTOMATION",
            "EXTERNAL_AUTOMATION_UNKNOWN",
            "MANUAL_REVIEW_REQUIRED",
        ],
        "defaults": {
            "LOGIN_REQUIRED": True,
            "CAPTCHA_REQUIRED": True,
            "HUMAN_SUBMISSION_ONLY": True,
            "TERMS_RESTRICT_AUTOMATION": True,
            "EXTERNAL_AUTOMATION_UNKNOWN": True,
            "MANUAL_REVIEW_REQUIRED": True,
        },
        "policy": "Nova does not bypass CAPTCHA, login, MFA, anti-bot measures, or website restrictions. Flags are internal metadata only.",
        "live_fetch_enabled": False,
        "live_submit_enabled": False,
    }


def create_platform_policy(
    db: Session,
    payload: PlatformPolicyCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    _ensure()
    row = NovaWorkPlatformPolicy(
        policy_id=_new_id("NWPP-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        opportunity_id=payload.opportunity_id,
        source_label=sanitize_untrusted(payload.source_label)[:120] or "unknown",
        login_required=True if payload.login_required else bool(payload.login_required),
        captcha_required=True if payload.captcha_required else bool(payload.captcha_required),
        human_submission_only=True,
        terms_restrict_automation=True,
        external_automation_unknown=True,
        manual_review_required=True,
        notes=sanitize_untrusted(payload.notes) or None,
    )
    # Hard-enforce safety: never store a record that claims automation is allowed.
    row.human_submission_only = True
    row.terms_restrict_automation = True
    row.manual_review_required = True
    db.add(row)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="OWNER_ACTION_REQUIRED",
        summary="Internal platform-policy flags stored. Nova will not bypass login, CAPTCHA, or terms.",
        ref_id=row.policy_id,
        entity_type="platform_policy",
        actor_category="OWNER",
        new_state="MANUAL_REVIEW_REQUIRED",
    )
    db.commit()
    db.refresh(row)
    return {
        "policy_id": row.policy_id,
        "opportunity_id": row.opportunity_id,
        "source_label": row.source_label,
        "LOGIN_REQUIRED": bool(row.login_required),
        "CAPTCHA_REQUIRED": bool(row.captcha_required),
        "HUMAN_SUBMISSION_ONLY": bool(row.human_submission_only),
        "TERMS_RESTRICT_AUTOMATION": bool(row.terms_restrict_automation),
        "EXTERNAL_AUTOMATION_UNKNOWN": bool(row.external_automation_unknown),
        "MANUAL_REVIEW_REQUIRED": bool(row.manual_review_required),
        "notes": row.notes,
        "bypass_allowed": False,
    }


def list_platform_policies(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    _ensure()
    rows = (
        _query(db, NovaWorkPlatformPolicy, organization_id, user)
        .order_by(NovaWorkPlatformPolicy.updated_at.desc())
        .limit(clamp_list_limit(limit, default=LIST_MAX_LIMIT))
        .all()
    )
    return [
        {
            "policy_id": item.policy_id,
            "opportunity_id": item.opportunity_id,
            "source_label": item.source_label,
            "LOGIN_REQUIRED": bool(item.login_required),
            "CAPTCHA_REQUIRED": bool(item.captcha_required),
            "HUMAN_SUBMISSION_ONLY": bool(item.human_submission_only),
            "TERMS_RESTRICT_AUTOMATION": bool(item.terms_restrict_automation),
            "EXTERNAL_AUTOMATION_UNKNOWN": bool(item.external_automation_unknown),
            "MANUAL_REVIEW_REQUIRED": bool(item.manual_review_required),
            "notes": item.notes,
            "bypass_allowed": False,
        }
        for item in rows
    ]


def completion_counts(db: Session, *, organization_id: str, user: UserContext) -> dict[str, int]:
    _ensure()
    recurring = _query(db, NovaWorkRecurringSeries, organization_id, user).all()
    overdue = 0
    for item in recurring:
        if _attention_state(item) == "overdue":
            overdue += 1
    reports = _query(db, NovaWorkWeeklyReport, organization_id, user).filter(
        NovaWorkWeeklyReport.status.in_(("DRAFT", "READY_FOR_OWNER_REVIEW"))
    ).count()
    invoices = _query(db, NovaWorkInvoiceSupport, organization_id, user).filter(
        NovaWorkInvoiceSupport.status.in_(("DRAFT", "READY_FOR_OWNER_REVIEW"))
    ).count()
    blocked = _query(db, NovaWorkEngagement, organization_id, user).filter(
        NovaWorkEngagement.status.in_(("BLOCKED", "OWNER_ACTION_REQUIRED", "WAITING_ON_OWNER"))
    ).count()
    return {
        "recurring_overdue": int(overdue),
        "reports_awaiting_review": int(reports or 0),
        "invoice_support_drafts": int(invoices or 0),
        "blocked_work": int(blocked or 0),
        "recurring_series": len(recurring),
    }
