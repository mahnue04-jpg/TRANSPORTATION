"""Phase 2 internal operations: deliverables, revenue entries, tasks, analytics. No live execution."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.flags import engine_guardrails
from app.core.nova.work_revenue.lifecycle import (
    ANALYTICS_PERIODS,
    DELIVERABLE_STATUSES,
    DELIVERABLE_TYPES,
    LIST_DEFAULT_LIMIT,
    LIST_MAX_LIMIT,
    OWNER_ACTION_CATEGORIES,
    PAID_STAGES,
    REVENUE_STAGES,
    category_for_action,
    normalize_revenue_stage,
    normalize_task_status,
)
from app.core.nova.work_revenue.materials import sanitize_untrusted
from app.core.nova.work_revenue.models import (
    NovaWorkDeliverable,
    NovaWorkMaterial,
    NovaWorkOwnerAction,
    NovaWorkRevenueEntry,
    NovaWorkTask,
)
from app.core.nova.work_revenue.owner_facts import fact_catalog
from app.core.nova.work_revenue.recurring import list_recurring_templates, reporting_period
from app.core.nova.work_revenue.schemas import (
    TASK_STATUSES,
    DeliverableConfirm,
    DeliverableCreate,
    DeliverableOut,
    DeliverableUpdate,
    MaterialRevise,
    OwnerActionUpdate,
    RevenueConfirm,
    RevenueEntryCreate,
    RevenueEntryOut,
    TaskUpdate,
)
from app.core.nova.work_revenue.service import (
    NovaWorkError,
    _ensure,
    _new_id,
    _owner_filter,
    _record_audit,
    _validate_amount,
    get_application,
    get_engagement,
    list_engagements,
    list_opportunities,
    list_owner_actions,
)
from app.helpers import now

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_PAID_JUMP_FROM = {"PAYMENT_PENDING", "PARTIALLY_PAID", "INVOICED_EXTERNALLY", "OVERDUE", "CONTRACTED"}
REVENUE_TRANSITIONS: dict[str, set[str]] = {
    "ESTIMATED": {"QUOTED", "CONTRACTED", "CANCELLED"},
    "QUOTED": {"CONTRACTED", "INVOICE_DRAFT", "CANCELLED"},
    "CONTRACTED": {"INVOICE_DRAFT", "INVOICED_EXTERNALLY", "PAYMENT_PENDING", "CANCELLED"},
    "INVOICE_DRAFT": {"INVOICED_EXTERNALLY", "CANCELLED"},
    "INVOICED_EXTERNALLY": {"PAYMENT_PENDING", "OVERDUE", "CANCELLED"},
    "PAYMENT_PENDING": {"PARTIALLY_PAID", "PAID", "OVERDUE", "CANCELLED"},
    "PARTIALLY_PAID": {"PAID", "OVERDUE", "CANCELLED"},
    "OVERDUE": {"PAYMENT_PENDING", "PARTIALLY_PAID", "PAID", "WRITTEN_OFF", "CANCELLED"},
    "PAID": set(),
    "WRITTEN_OFF": set(),
    "CANCELLED": set(),
}
TASK_TRANSITIONS: dict[str, set[str]] = {
    "NOT_STARTED": {"READY", "IN_PROGRESS", "BLOCKED", "CANCELLED"},
    "READY": {"IN_PROGRESS", "BLOCKED", "CANCELLED"},
    "IN_PROGRESS": {"OWNER_REVIEW", "COMPLETE", "BLOCKED", "CANCELLED"},
    "OWNER_REVIEW": {"IN_PROGRESS", "COMPLETE", "BLOCKED"},
    "BLOCKED": {"READY", "IN_PROGRESS", "CANCELLED"},
    "COMPLETE": set(),
    "CANCELLED": set(),
}
DELIVERABLE_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"READY_FOR_REVIEW", "CANCELLED"},
    "READY_FOR_REVIEW": {"OWNER_APPROVED", "DRAFT", "CANCELLED"},
    "OWNER_APPROVED": {"CONFIRMED_DELIVERED", "CANCELLED"},
    "CONFIRMED_DELIVERED": set(),
    "CANCELLED": set(),
}


def clamp_limit(limit: int | None) -> int:
    value = LIST_DEFAULT_LIMIT if limit is None else int(limit)
    if value < 1:
        return 1
    return min(value, LIST_MAX_LIMIT)


def _validate_currency(value: str | None) -> str:
    token = str(value or "USD").strip().upper()
    if not _CURRENCY_RE.match(token):
        raise NovaWorkError("Currency must be a 3-letter code such as USD")
    return token


def owner_facts(*, applicant_party: str = "AMICOR") -> dict[str, Any]:
    return fact_catalog(applicant_party=applicant_party)


def recurring_catalog() -> dict[str, Any]:
    return {
        "templates": list_recurring_templates(),
        "notifications_enabled": False,
        "external_schedule_created": False,
        "policy": "Recurring templates are internal only. Nova does not send reports or create calendar events.",
    }


def period_window(period: str | None) -> datetime | None:
    token = str(period or "all").strip().lower()
    if token not in ANALYTICS_PERIODS:
        raise NovaWorkError("Unknown analytics period")
    if token == "all":
        return None
    current = now()
    if token == "today":
        return current - timedelta(days=1)
    if token == "week":
        return current - timedelta(days=7)
    return current - timedelta(days=31)


def _in_period(value: datetime | None, start: datetime | None) -> bool:
    if start is None or value is None:
        return True
    current = now()
    if value.tzinfo is None and current.tzinfo is not None:
        value = value.replace(tzinfo=current.tzinfo)
    return value >= start


def deliverable_out(row: NovaWorkDeliverable) -> DeliverableOut:
    return DeliverableOut(
        deliverable_id=row.deliverable_id,
        engagement_id=row.engagement_id,
        opportunity_id=row.opportunity_id,
        deliverable_type=row.deliverable_type,
        description=row.description,
        due_date=row.due_date,
        draft_status=row.draft_status,
        review_status=row.review_status,
        owner_approved=bool(row.owner_approved),
        delivery_status=row.delivery_status,
        owner_confirmed_delivered=bool(row.owner_confirmed_delivered),
        completed_at=row.completed_at,
        notes=row.notes,
    )


def revenue_out(row: NovaWorkRevenueEntry) -> RevenueEntryOut:
    display = row.stage
    if bool(row.owner_confirmed) and row.stage in PAID_STAGES:
        display = "OWNER_CONFIRMED_RECEIVED"
    elif row.stage == "INVOICED_EXTERNALLY":
        display = "MANUAL_RECORD_ONLY"
    return RevenueEntryOut(
        entry_id=row.entry_id,
        engagement_id=row.engagement_id,
        opportunity_id=row.opportunity_id,
        stage=row.stage,
        amount=row.amount,
        currency=row.currency,
        expected_payment_date=row.expected_payment_date,
        invoice_reference=row.invoice_reference,
        received_date=row.received_date,
        owner_confirmed=bool(row.owner_confirmed),
        reconciliation_notes=row.reconciliation_notes,
        display_stage=display,
    )


def _task_query(db: Session, organization_id: str, user: UserContext):
    query = db.query(NovaWorkTask).filter(NovaWorkTask.organization_id == organization_id)
    return _owner_filter(query, NovaWorkTask, user)


def _deliverable_query(db: Session, organization_id: str, user: UserContext):
    query = db.query(NovaWorkDeliverable).filter(NovaWorkDeliverable.organization_id == organization_id)
    return _owner_filter(query, NovaWorkDeliverable, user)


def _revenue_query(db: Session, organization_id: str, user: UserContext):
    query = db.query(NovaWorkRevenueEntry).filter(NovaWorkRevenueEntry.organization_id == organization_id)
    return _owner_filter(query, NovaWorkRevenueEntry, user)


def get_task(db: Session, task_id: str, *, organization_id: str, user: UserContext) -> NovaWorkTask:
    _ensure()
    row = _task_query(db, organization_id, user).filter(NovaWorkTask.task_id == task_id).first()
    if row is None:
        raise NovaWorkError("Task not found", status_code=404)
    return row


def get_deliverable(db: Session, deliverable_id: str, *, organization_id: str, user: UserContext) -> NovaWorkDeliverable:
    _ensure()
    row = _deliverable_query(db, organization_id, user).filter(NovaWorkDeliverable.deliverable_id == deliverable_id).first()
    if row is None:
        raise NovaWorkError("Deliverable not found", status_code=404)
    return row


def get_revenue_entry(db: Session, entry_id: str, *, organization_id: str, user: UserContext) -> NovaWorkRevenueEntry:
    _ensure()
    row = _revenue_query(db, organization_id, user).filter(NovaWorkRevenueEntry.entry_id == entry_id).first()
    if row is None:
        raise NovaWorkError("Revenue entry not found", status_code=404)
    return row


def list_tasks(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    engagement_id: str | None = None,
    status: str | None = None,
    nova_capable: bool | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    _ensure()
    query = _task_query(db, organization_id, user)
    if engagement_id:
        query = query.filter(NovaWorkTask.engagement_id == engagement_id)
    if status:
        query = query.filter(NovaWorkTask.status == normalize_task_status(status))
    if nova_capable is True:
        query = query.filter(NovaWorkTask.classification == "NOVA")
    elif nova_capable is False:
        query = query.filter(NovaWorkTask.classification != "NOVA")
    rows = (
        query.order_by(NovaWorkTask.updated_at.desc())
        .offset(max(offset, 0))
        .limit(clamp_limit(limit))
        .all()
    )
    return [
        {
            "task_id": item.task_id,
            "engagement_id": item.engagement_id,
            "title": item.title,
            "description": item.description,
            "responsible_party": item.responsible_party,
            "classification": item.classification,
            "status": item.status,
            "priority": item.priority,
            "due_date": item.due_date.isoformat() if item.due_date else None,
            "depends_on_task_id": item.depends_on_task_id,
            "blocked_reason": item.blocked_reason,
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            "owner_notes": item.owner_notes,
            "review_required": item.review_required,
        }
        for item in rows
    ]


def update_task(
    db: Session,
    task_id: str,
    payload: TaskUpdate,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    row = get_task(db, task_id, organization_id=organization_id, user=user)
    if payload.status is not None:
        target = normalize_task_status(payload.status)
        if target not in TASK_STATUSES:
            raise NovaWorkError("Unknown task status")
        if target != row.status:
            allowed = TASK_TRANSITIONS.get(row.status, set())
            if target not in allowed:
                raise NovaWorkError(f"Cannot transition task from {row.status} to {target}")
            if target in {"IN_PROGRESS", "COMPLETE"} and row.depends_on_task_id:
                parent = get_task(db, row.depends_on_task_id, organization_id=organization_id, user=user)
                if parent.status != "COMPLETE":
                    raise NovaWorkError("Task dependency is not complete")
            row.status = target
            if target == "COMPLETE":
                row.completed_at = now()
                _record_audit(
                    db,
                    organization_id=organization_id,
                    user=user,
                    event_type="TASK_COMPLETED",
                    summary=f"Internal task completed: {row.title}",
                    ref_id=row.task_id,
                    entity_type="task",
                    actor_category="OWNER" if row.classification != "NOVA" else "NOVA",
                )
            elif target == "BLOCKED" and not (payload.blocked_reason or row.blocked_reason):
                raise NovaWorkError("Blocked tasks require a blocked reason")
    if payload.blocked_reason is not None:
        row.blocked_reason = sanitize_untrusted(payload.blocked_reason) or None
    if payload.owner_notes is not None:
        row.owner_notes = sanitize_untrusted(payload.owner_notes) or None
    if payload.depends_on_task_id is not None:
        if payload.depends_on_task_id:
            parent = get_task(db, payload.depends_on_task_id, organization_id=organization_id, user=user)
            if parent.engagement_id != row.engagement_id:
                raise NovaWorkError("Task dependency must belong to the same engagement")
            row.depends_on_task_id = parent.task_id
        else:
            row.depends_on_task_id = None
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return {
        "task_id": row.task_id,
        "engagement_id": row.engagement_id,
        "title": row.title,
        "status": row.status,
        "depends_on_task_id": row.depends_on_task_id,
        "blocked_reason": row.blocked_reason,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "owner_notes": row.owner_notes,
    }


def list_deliverables(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    engagement_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[DeliverableOut]:
    _ensure()
    query = _deliverable_query(db, organization_id, user)
    if engagement_id:
        query = query.filter(NovaWorkDeliverable.engagement_id == engagement_id)
    rows = query.order_by(NovaWorkDeliverable.updated_at.desc()).offset(max(offset, 0)).limit(clamp_limit(limit)).all()
    return [deliverable_out(item) for item in rows]


def create_deliverable(
    db: Session,
    payload: DeliverableCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> DeliverableOut:
    engagement = get_engagement(db, payload.engagement_id, organization_id=organization_id, user=user)
    dtype = str(payload.deliverable_type or "OTHER").strip().upper()
    if dtype not in DELIVERABLE_TYPES:
        raise NovaWorkError("Unknown deliverable type")
    row = NovaWorkDeliverable(
        deliverable_id=_new_id("NWD-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        engagement_id=payload.engagement_id,
        opportunity_id=engagement.get("opportunity_id"),
        deliverable_type=dtype,
        description=sanitize_untrusted(payload.description) or "Internal deliverable",
        due_date=payload.due_date,
        draft_status="DRAFT",
        review_status="DRAFT",
        owner_approved=False,
        delivery_status="DRAFT",
        owner_confirmed_delivered=False,
        notes=sanitize_untrusted(payload.notes) or None,
    )
    db.add(row)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="DELIVERABLE_CREATED",
        summary=f"Internal deliverable recorded: {dtype}. Nothing was sent.",
        ref_id=row.deliverable_id,
        entity_type="deliverable",
        actor_category="NOVA",
    )
    db.commit()
    db.refresh(row)
    return deliverable_out(row)


def update_deliverable(
    db: Session,
    deliverable_id: str,
    payload: DeliverableUpdate,
    *,
    organization_id: str,
    user: UserContext,
) -> DeliverableOut:
    row = get_deliverable(db, deliverable_id, organization_id=organization_id, user=user)
    target = payload.review_status or payload.draft_status
    if target:
        token = str(target).strip().upper()
        if token not in DELIVERABLE_STATUSES:
            raise NovaWorkError("Unknown deliverable status")
        if token == "CONFIRMED_DELIVERED":
            raise NovaWorkError("Delivered status requires explicit owner confirmation")
        if token != row.delivery_status:
            allowed = DELIVERABLE_TRANSITIONS.get(row.delivery_status, set())
            if token not in allowed:
                raise NovaWorkError(f"Cannot transition deliverable from {row.delivery_status} to {token}")
            row.draft_status = token if token in {"DRAFT", "READY_FOR_REVIEW"} else row.draft_status
            row.review_status = token
            row.delivery_status = token
            if token == "OWNER_APPROVED":
                row.owner_approved = True
    if payload.owner_approved is True:
        if row.delivery_status not in {"READY_FOR_REVIEW", "OWNER_APPROVED"}:
            raise NovaWorkError("Owner approval requires READY_FOR_REVIEW")
        row.owner_approved = True
        row.review_status = "OWNER_APPROVED"
        row.delivery_status = "OWNER_APPROVED"
    if payload.notes is not None:
        row.notes = sanitize_untrusted(payload.notes) or None
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return deliverable_out(row)


def confirm_deliverable(
    db: Session,
    deliverable_id: str,
    payload: DeliverableConfirm,
    *,
    organization_id: str,
    user: UserContext,
) -> DeliverableOut:
    row = get_deliverable(db, deliverable_id, organization_id=organization_id, user=user)
    if payload.owner_confirmed_delivered is not True:
        raise NovaWorkError("Delivered confirmation must be explicit")
    if not row.owner_approved and row.delivery_status != "OWNER_APPROVED":
        raise NovaWorkError("Owner must approve the deliverable before confirming delivery")
    row.owner_confirmed_delivered = True
    row.delivery_status = "CONFIRMED_DELIVERED"
    row.review_status = "CONFIRMED_DELIVERED"
    row.completed_at = now()
    if payload.notes is not None:
        row.notes = sanitize_untrusted(payload.notes) or row.notes
    row.updated_at = now()
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="DELIVERABLE_CONFIRMED",
        summary="Owner confirmed internal delivery. Nova did not transmit anything externally.",
        ref_id=row.deliverable_id,
        entity_type="deliverable",
        actor_category="OWNER",
    )
    db.commit()
    db.refresh(row)
    return deliverable_out(row)


def list_revenue_entries(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    engagement_id: str | None = None,
    stage: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[RevenueEntryOut]:
    _ensure()
    query = _revenue_query(db, organization_id, user)
    if engagement_id:
        query = query.filter(NovaWorkRevenueEntry.engagement_id == engagement_id)
    if stage:
        query = query.filter(NovaWorkRevenueEntry.stage == stage)
    rows = query.order_by(NovaWorkRevenueEntry.updated_at.desc()).offset(max(offset, 0)).limit(clamp_limit(limit)).all()
    return [revenue_out(item) for item in rows]


def create_revenue_entry(
    db: Session,
    payload: RevenueEntryCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> RevenueEntryOut:
    _ensure()
    amount = _validate_amount(payload.amount, label="amount")
    if amount is None:
        raise NovaWorkError("Amount is required")
    stage = normalize_revenue_stage(payload.stage or "ESTIMATED")
    if stage not in REVENUE_STAGES:
        raise NovaWorkError("Unknown revenue stage")
    if stage in PAID_STAGES:
        raise NovaWorkError("Revenue cannot be created as PAID. Owner confirmation is required on an existing entry.")
    if payload.engagement_id:
        get_engagement(db, payload.engagement_id, organization_id=organization_id, user=user)
    row = NovaWorkRevenueEntry(
        entry_id=_new_id("NWR-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        engagement_id=payload.engagement_id,
        opportunity_id=payload.opportunity_id,
        stage=stage,
        amount=amount,
        currency=_validate_currency(payload.currency),
        expected_payment_date=payload.expected_payment_date,
        invoice_reference=sanitize_untrusted(payload.invoice_reference)[:120] or None,
        owner_confirmed=False,
        reconciliation_notes=sanitize_untrusted(payload.reconciliation_notes) or None,
    )
    db.add(row)
    event = "REVENUE_CONTRACTED" if stage == "CONTRACTED" else "REVENUE_ESTIMATED"
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type=event,
        summary=f"Internal revenue {stage} recorded. Not received cash.",
        ref_id=row.entry_id,
        entity_type="revenue",
        actor_category="OWNER",
    )
    db.commit()
    db.refresh(row)
    return revenue_out(row)


def update_revenue_stage(
    db: Session,
    entry_id: str,
    stage: str,
    *,
    organization_id: str,
    user: UserContext,
) -> RevenueEntryOut:
    row = get_revenue_entry(db, entry_id, organization_id=organization_id, user=user)
    target = normalize_revenue_stage(stage)
    if target not in REVENUE_STAGES:
        raise NovaWorkError("Unknown revenue stage")
    if target in PAID_STAGES:
        raise NovaWorkError("PAID requires explicit owner confirmation")
    allowed = REVENUE_TRANSITIONS.get(row.stage, set())
    if target not in allowed:
        raise NovaWorkError(f"Cannot transition revenue from {row.stage} to {target}")
    previous = row.stage
    row.stage = target
    row.updated_at = now()
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="PAYMENT_STATUS_CHANGED",
        summary=f"Revenue stage {previous} → {target}. Not a payment processor event.",
        ref_id=row.entry_id,
        entity_type="revenue",
        actor_category="OWNER",
    )
    db.commit()
    db.refresh(row)
    return revenue_out(row)


def confirm_revenue_received(
    db: Session,
    entry_id: str,
    payload: RevenueConfirm,
    *,
    organization_id: str,
    user: UserContext,
) -> RevenueEntryOut:
    row = get_revenue_entry(db, entry_id, organization_id=organization_id, user=user)
    if payload.owner_confirmed is not True:
        raise NovaWorkError("Received revenue requires explicit owner confirmation")
    if row.stage not in _PAID_JUMP_FROM and row.stage not in PAID_STAGES:
        raise NovaWorkError("Revenue cannot jump to PAID from the current stage")
    if payload.amount is not None:
        row.amount = _validate_amount(payload.amount, label="amount") or row.amount
    row.owner_confirmed = True
    row.stage = "PAID" if row.stage != "PARTIALLY_PAID" or (payload.amount is not None and payload.amount >= row.amount) else "PARTIALLY_PAID"
    if row.stage == "PARTIALLY_PAID" and payload.amount is not None and payload.amount < (row.amount or 0):
        row.stage = "PARTIALLY_PAID"
    row.received_date = payload.received_date or now()
    if payload.reconciliation_notes is not None:
        row.reconciliation_notes = sanitize_untrusted(payload.reconciliation_notes) or None
    row.updated_at = now()
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="REVENUE_RECEIVED_CONFIRMED",
        summary="Owner confirmed received revenue. Nova did not collect payment.",
        ref_id=row.entry_id,
        entity_type="revenue",
        actor_category="OWNER",
    )
    db.commit()
    db.refresh(row)
    return revenue_out(row)


def revise_material(
    db: Session,
    application_id: str,
    material_id: str,
    payload: MaterialRevise,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    application = get_application(db, application_id, organization_id=organization_id, user=user)
    parent = (
        db.query(NovaWorkMaterial)
        .filter(
            NovaWorkMaterial.organization_id == organization_id,
            NovaWorkMaterial.application_id == application.application_id,
            NovaWorkMaterial.material_id == material_id,
        )
        .first()
    )
    if parent is None:
        raise NovaWorkError("Draft material not found", status_code=404)
    revision = int(getattr(parent, "revision", 1) or 1) + 1
    row = NovaWorkMaterial(
        material_id=_new_id("NWM-"),
        application_id=application.application_id,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        kind=parent.kind,
        title=(sanitize_untrusted(payload.title) or parent.title)[:220],
        body=sanitize_untrusted(payload.body) or parent.body,
        status="DRAFT",
        owner_input_required=True,
        revision=revision,
        parent_material_id=parent.material_id,
    )
    db.add(row)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="DRAFT_REVISED",
        summary=f"Draft {parent.kind} revision {revision} stored internally. Nothing was sent.",
        ref_id=row.material_id,
        entity_type="material",
        actor_category="NOVA",
    )
    db.commit()
    db.refresh(row)
    return {
        "material_id": row.material_id,
        "application_id": row.application_id,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "status": row.status,
        "owner_input_required": row.owner_input_required,
        "revision": row.revision,
        "parent_material_id": row.parent_material_id,
    }


def update_owner_action(
    db: Session,
    action_id: str,
    payload: OwnerActionUpdate,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    _ensure()
    query = db.query(NovaWorkOwnerAction).filter(
        NovaWorkOwnerAction.organization_id == organization_id,
        NovaWorkOwnerAction.action_id == action_id,
    )
    row = _owner_filter(query, NovaWorkOwnerAction, user).first()
    if row is None:
        raise NovaWorkError("Owner action not found", status_code=404)
    if payload.owner_notes is not None:
        row.owner_notes = sanitize_untrusted(payload.owner_notes) or None
    if payload.status is not None:
        status = str(payload.status).strip().upper()
        if status not in {"OPEN", "DONE", "CANCELLED"}:
            raise NovaWorkError("Unknown owner-action status")
        row.status = status
    if not getattr(row, "category", None):
        row.category = category_for_action(row.action_type)
        if row.category not in OWNER_ACTION_CATEGORIES:
            row.category = "PROVIDE_INFORMATION"
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return {
        "action_id": row.action_id,
        "action_type": row.action_type,
        "status": row.status,
        "category": row.category,
        "owner_notes": row.owner_notes,
        "explanation": row.explanation,
        "display_label": row.display_label,
    }


def analytics(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    period: str = "all",
) -> dict[str, Any]:
    start = period_window(period)
    opps = list_opportunities(db, organization_id=organization_id, user=user)
    if start is not None:
        opps = [item for item in opps if _in_period(item.created_at, start)]
    engagements = list_engagements(db, organization_id=organization_id, user=user)
    actions = list_owner_actions(db, organization_id=organization_id, user=user)
    tasks = list_tasks(db, organization_id=organization_id, user=user, limit=LIST_MAX_LIMIT)
    deliverables = list_deliverables(db, organization_id=organization_id, user=user, limit=LIST_MAX_LIMIT)
    revenue = list_revenue_entries(db, organization_id=organization_id, user=user, limit=LIST_MAX_LIMIT)
    due_cutoff = now() + timedelta(days=1)
    tasks_due = 0
    for item in tasks:
        if item.get("status") in {"COMPLETE", "CANCELLED"}:
            continue
        due = item.get("due_date")
        if due:
            tasks_due += 1
        elif item.get("status") in {"READY", "IN_PROGRESS", "NOT_STARTED"}:
            tasks_due += 1
    estimated = sum((item.estimated_value or 0) for item in opps)
    quoted = sum((item.quoted_amount or 0) for item in opps)
    contracted = sum((item.contract_amount or 0) for item in opps)
    invoiced = sum(item.amount for item in revenue if item.stage in {"INVOICE_DRAFT", "INVOICED_EXTERNALLY", "PAYMENT_PENDING", "OVERDUE"})
    received = sum(item.amount for item in revenue if item.owner_confirmed and item.stage in PAID_STAGES)
    received += sum((item.amount_received or 0) for item in opps if item.owner_confirmed_payment_received)
    return {
        "period": period or "all",
        "new_opportunities": len([item for item in opps if item.status == "DISCOVERED"]),
        "qualified_opportunities": len(
            [item for item in opps if item.qualification_outcome in {"NOVA_CAN_PERFORM", "NOVA_WITH_OWNER_REVIEW"} or item.status in {"QUALIFIED", "OWNER_REVIEW", "APPLICATION_PREPARED"}]
        ),
        "owner_actions_pending": len(actions),
        "active_engagements": len([item for item in engagements if item["status"] in {"NOT_STARTED", "READY", "ACTIVE"}]),
        "blocked_engagements": len([item for item in engagements if item["status"] == "BLOCKED" or item.get("blockers")]),
        "tasks_due": tasks_due,
        "completed_work": len([item for item in deliverables if item.owner_confirmed_delivered]) + len([item for item in tasks if item.get("status") == "COMPLETE"]),
        "estimated_pipeline": estimated,
        "quoted_pipeline": quoted,
        "contracted_revenue": contracted,
        "invoiced_revenue": invoiced,
        "received_revenue": received,
        "disclaimer": (
            "ESTIMATED != CONTRACTED. CONTRACTED != INVOICED. INVOICED != RECEIVED. "
            "Nova does not collect payment."
        ),
        "guardrails": engine_guardrails(),
        "due_cutoff": due_cutoff.isoformat(),
        "reporting_period": reporting_period(period or "weekly"),
    }
