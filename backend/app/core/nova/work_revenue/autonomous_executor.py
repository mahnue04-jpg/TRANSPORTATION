"""Controlled executor for owner-started Nova Work & Revenue engagements."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue import managed, ops
from app.core.nova.work_revenue.models import NovaWorkDeliverable, NovaWorkTask
from app.core.nova.work_revenue.schemas import DeliverableCreate, DeliverableUpdate, EngagementUpdate, TaskUpdate
from app.core.nova.work_revenue.service import (
    NovaWorkError,
    _record_audit,
    get_engagement,
    get_opportunity,
)

_SOURCE_DATA_TASK_TERMS = (
    "source data",
    "missing, duplicate",
    "invalid values",
    "clean and normalize",
    "calculations and transformations",
    "spreadsheet/report structure",
    "validate totals",
    "sample records",
)
_OUTLINE_TITLE = "Prepare internal work outline"
_OUTLINE_MARKER = "AUTONOMOUS_EXECUTOR_OUTLINE_V1"


def _is_source_data_task(title: str) -> bool:
    value = str(title or "").strip().lower()
    return any(term in value for term in _SOURCE_DATA_TASK_TERMS)


def run_autonomous_engagement(
    db: Session,
    engagement_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    engagement = get_engagement(db, engagement_id, organization_id=organization_id, user=user)
    if str(engagement.get("source") or "") != "nova_autonomous":
        raise NovaWorkError("Autonomous executor is limited to Nova autonomous engagements", status_code=409)

    if str(engagement.get("status") or "") in {"ARCHIVED", "CLOSED", "CANCELLED", "COMPLETE"}:
        raise NovaWorkError("This engagement is not open for autonomous execution", status_code=409)

    if engagement.get("status") != "ACTIVE":
        managed.update_engagement(
            db,
            engagement_id,
            EngagementUpdate(status="ACTIVE"),
            organization_id=organization_id,
            user=user,
        )

    opportunity_id = engagement.get("opportunity_id")
    opportunity = (
        get_opportunity(db, opportunity_id, organization_id=organization_id, user=user)
        if opportunity_id
        else None
    )

    advanced: list[str] = []
    blocked: list[str] = []
    deliverable_id: str | None = None

    outline_task = (
        db.query(NovaWorkTask)
        .filter(
            NovaWorkTask.organization_id == organization_id,
            NovaWorkTask.engagement_id == engagement_id,
            NovaWorkTask.classification == "NOVA",
            NovaWorkTask.title == _OUTLINE_TITLE,
        )
        .first()
    )
    if outline_task is not None and outline_task.status in {"NOT_STARTED", "READY"}:
        ops.update_task(
            db,
            outline_task.task_id,
            TaskUpdate(status="IN_PROGRESS"),
            organization_id=organization_id,
            user=user,
        )
        existing_outline = (
            db.query(NovaWorkDeliverable)
            .filter(
                NovaWorkDeliverable.organization_id == organization_id,
                NovaWorkDeliverable.engagement_id == engagement_id,
                NovaWorkDeliverable.notes == _OUTLINE_MARKER,
            )
            .first()
        )
        if existing_outline is None:
            title = getattr(opportunity, "opportunity_title", None) or engagement.get("service") or "Internal work"
            description = getattr(opportunity, "description", None) or "No additional opportunity description was stored."
            deliverable = ops.create_deliverable(
                db,
                DeliverableCreate(
                    engagement_id=engagement_id,
                    deliverable_type="DOCUMENT",
                    description=(
                        f"Internal autonomous work outline for {title}. "
                        f"Scope basis: {description[:2500]} "
                        "This outline is derived only from stored opportunity scope. "
                        "No client/source dataset has been analyzed."
                    ),
                    notes=_OUTLINE_MARKER,
                ),
                organization_id=organization_id,
                user=user,
            )
            deliverable = ops.update_deliverable(
                db,
                deliverable.deliverable_id,
                DeliverableUpdate(review_status="READY_FOR_REVIEW"),
                organization_id=organization_id,
                user=user,
            )
            deliverable_id = deliverable.deliverable_id
        else:
            deliverable_id = existing_outline.deliverable_id
        ops.update_task(
            db,
            outline_task.task_id,
            TaskUpdate(
                status="OWNER_REVIEW",
                owner_notes="Internal work outline generated from stored opportunity scope. Owner review required before any external use.",
            ),
            organization_id=organization_id,
            user=user,
        )
        advanced.append(outline_task.task_id)

    ready_tasks = (
        db.query(NovaWorkTask)
        .filter(
            NovaWorkTask.organization_id == organization_id,
            NovaWorkTask.engagement_id == engagement_id,
            NovaWorkTask.classification == "NOVA",
            NovaWorkTask.status == "READY",
        )
        .all()
    )
    for task in ready_tasks:
        if not _is_source_data_task(task.title):
            continue
        reason = (
            "SOURCE DATA REQUIRED: this task depends on the client/source dataset. "
            "No engagement-level source dataset is available, so Nova did not invent or analyze data."
        )
        ops.update_task(
            db,
            task.task_id,
            TaskUpdate(status="BLOCKED", blocked_reason=reason, owner_notes=reason),
            organization_id=organization_id,
            user=user,
        )
        blocked.append(task.task_id)

    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="AUTONOMOUS_EXECUTOR_RUN",
        summary=(
            f"Nova internal executor ran: {len(advanced)} task(s) advanced; "
            f"{len(blocked)} task(s) blocked for missing source data. No external action."
        ),
        ref_id=engagement_id,
        entity_type="engagement",
        actor_category="NOVA",
        new_state="ACTIVE",
    )
    db.commit()

    return {
        "status": "AUTONOMOUS_EXECUTOR_RAN",
        "engagement_id": engagement_id,
        "engagement_status": "ACTIVE",
        "tasks_advanced": len(advanced),
        "tasks_blocked": len(blocked),
        "advanced_task_ids": advanced,
        "blocked_task_ids": blocked,
        "deliverable_id": deliverable_id,
        "owner_review_required": True,
        "source_data_required": bool(blocked),
        "external_submission": False,
        "client_contact": False,
        "contract_acceptance": False,
        "financial_execution": False,
    }
