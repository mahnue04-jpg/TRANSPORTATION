"""Owner-controlled completion and invoice preparation for Nova Work & Revenue."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue import managed, ops
from app.core.nova.work_revenue.schemas import (
    DeliverableUpdate,
    EngagementUpdate,
    InvoiceSupportCreate,
    InvoiceSupportDecision,
    OwnerCompletionRequest,
    OwnerInvoicePrepRequest,
    RevenueEntryCreate,
    TaskUpdate,
)
from app.core.nova.work_revenue.service import NovaWorkError


def approve_internal_work(
    db: Session,
    engagement_id: str,
    *,
    organization_id: str,
    user: UserContext,
    payload: OwnerCompletionRequest,
) -> dict[str, Any]:
    engagement = managed.get_engagement_row(
        db, engagement_id, organization_id=organization_id, user=user
    )
    if engagement.status in {"ARCHIVED", "CANCELLED"}:
        raise NovaWorkError("Archived/cancelled work cannot be completed", status_code=409)

    deliverables = ops.list_deliverables(
        db,
        organization_id=organization_id,
        user=user,
        engagement_id=engagement_id,
        limit=200,
    )
    if not deliverables:
        raise NovaWorkError("No deliverables exist for owner review", status_code=409)

    pending_deliverables = [
        item.deliverable_id
        for item in deliverables
        if item.delivery_status not in {"READY_FOR_REVIEW", "OWNER_APPROVED", "CONFIRMED_DELIVERED"}
    ]
    if pending_deliverables:
        raise NovaWorkError(
            "All deliverables must be READY_FOR_REVIEW before owner completion",
            status_code=409,
        )

    tasks = ops.list_tasks(
        db,
        organization_id=organization_id,
        user=user,
        engagement_id=engagement_id,
        limit=200,
    )
    invalid_tasks = [
        task for task in tasks
        if task["status"] not in {"COMPLETE", "CANCELLED", "OWNER_REVIEW", "NOT_STARTED"}
        or (
            task["status"] == "NOT_STARTED"
            and not (
                task.get("classification") != "NOVA"
                and "owner review" in str(task.get("title") or "").strip().lower()
            )
        )
    ]
    if invalid_tasks:
        raise NovaWorkError(
            "Internal work is not ready for owner completion: "
            + ", ".join(str(task.get("title") or task["task_id"]) for task in invalid_tasks[:8]),
            status_code=409,
        )

    approved_deliverables: list[str] = []
    for item in deliverables:
        if item.delivery_status == "READY_FOR_REVIEW":
            updated = ops.update_deliverable(
                db,
                item.deliverable_id,
                DeliverableUpdate(
                    owner_approved=True,
                    notes=payload.owner_notes,
                ),
                organization_id=organization_id,
                user=user,
            )
            approved_deliverables.append(updated.deliverable_id)
        else:
            approved_deliverables.append(item.deliverable_id)

    completed_tasks: list[str] = []

    # Complete Nova review tasks first so owner-review dependencies can resolve.
    for task in tasks:
        if task["status"] == "OWNER_REVIEW" and task.get("classification") == "NOVA":
            updated = ops.update_task(
                db,
                task["task_id"],
                TaskUpdate(
                    status="COMPLETE",
                    owner_notes=payload.owner_notes or "Owner approved reviewed Nova work.",
                ),
                organization_id=organization_id,
                user=user,
            )
            completed_tasks.append(updated["task_id"])

    # Complete owner review tasks only after Nova work is complete.
    refreshed_tasks = ops.list_tasks(
        db,
        organization_id=organization_id,
        user=user,
        engagement_id=engagement_id,
        limit=200,
    )
    for task in refreshed_tasks:
        title = str(task.get("title") or "").strip().lower()
        if task["status"] == "NOT_STARTED" and task.get("classification") != "NOVA" and "owner review" in title:
            ops.update_task(
                db,
                task["task_id"],
                TaskUpdate(
                    status="IN_PROGRESS",
                    owner_notes=payload.owner_notes or "Owner reviewing completed internal work.",
                ),
                organization_id=organization_id,
                user=user,
            )
            updated = ops.update_task(
                db,
                task["task_id"],
                TaskUpdate(
                    status="COMPLETE",
                    owner_notes=payload.owner_notes or "Owner approved completed internal work.",
                ),
                organization_id=organization_id,
                user=user,
            )
            completed_tasks.append(updated["task_id"])
        elif task["status"] == "OWNER_REVIEW" and task.get("classification") != "NOVA":
            updated = ops.update_task(
                db,
                task["task_id"],
                TaskUpdate(
                    status="COMPLETE",
                    owner_notes=payload.owner_notes or "Owner approved reviewed internal work.",
                ),
                organization_id=organization_id,
                user=user,
            )
            completed_tasks.append(updated["task_id"])

    final_tasks = ops.list_tasks(
        db,
        organization_id=organization_id,
        user=user,
        engagement_id=engagement_id,
        limit=200,
    )
    incomplete = [
        task for task in final_tasks
        if task["status"] not in {"COMPLETE", "CANCELLED"}
    ]
    if incomplete:
        raise NovaWorkError(
            "Internal work still has incomplete tasks: "
            + ", ".join(str(task.get("title") or task["task_id"]) for task in incomplete[:8]),
            status_code=409,
        )

    if engagement.status != "COMPLETE":
        final_engagement = managed.update_engagement(
            db,
            engagement_id,
            EngagementUpdate(
                status="COMPLETE",
                notes=payload.owner_notes or "Owner approved internal completion. COMPLETE != PAID.",
            ),
            organization_id=organization_id,
            user=user,
        )
    else:
        final_engagement = managed.get_engagement(
            db, engagement_id, organization_id=organization_id, user=user
        )

    return {
        "engagement_id": engagement_id,
        "status": final_engagement["status"],
        "deliverables_approved": len(set(approved_deliverables)),
        "deliverable_ids": sorted(set(approved_deliverables)),
        "tasks_completed_this_action": len(set(completed_tasks)),
        "task_ids": sorted(set(completed_tasks)),
        "external_delivery": False,
        "invoice_sent": False,
        "payment_received": False,
        "complete_equals_paid": False,
        "next_action": "Prepare invoice support only if owner supplies quantity and rate.",
    }


def prepare_invoice_support(
    db: Session,
    engagement_id: str,
    *,
    organization_id: str,
    user: UserContext,
    payload: OwnerInvoicePrepRequest,
) -> dict[str, Any]:
    engagement = managed.get_engagement_row(
        db, engagement_id, organization_id=organization_id, user=user
    )
    if engagement.status != "COMPLETE":
        raise NovaWorkError(
            "Owner must complete internal work before preparing invoice support",
            status_code=409,
        )

    deliverables = ops.list_deliverables(
        db,
        organization_id=organization_id,
        user=user,
        engagement_id=engagement_id,
        limit=200,
    )
    approved_ids = [
        item.deliverable_id
        for item in deliverables
        if item.owner_approved or item.delivery_status in {"OWNER_APPROVED", "CONFIRMED_DELIVERED"}
    ]
    if not approved_ids:
        raise NovaWorkError("No owner-approved deliverables are available for invoice support", status_code=409)

    subtotal = round(float(payload.quantity) * float(payload.rate), 2)
    if subtotal > 1_000_000_000:
        raise NovaWorkError("Invoice-support subtotal exceeds the allowed maximum", status_code=422)
    existing_invoices = [
        item for item in managed.list_invoice_supports(
            db, organization_id=organization_id, user=user, limit=200
        )
        if item.get("engagement_id") == engagement_id
        and item.get("status") in {"DRAFT", "READY_FOR_OWNER_REVIEW", "APPROVED"}
        and abs(float(item.get("draft_subtotal") or 0) - subtotal) < 0.005
    ]

    if existing_invoices:
        invoice = existing_invoices[0]
    else:
        invoice = managed.create_invoice_support(
            db,
            InvoiceSupportCreate(
                engagement_id=engagement_id,
                client_name=engagement.client_name,
                deliverable_ids=approved_ids,
                quantity=payload.quantity,
                rate=payload.rate,
                invoice_required=payload.invoice_required,
                owner_notes=payload.owner_notes or "Prepared from owner-supplied quantity/rate. Not sent.",
            ),
            organization_id=organization_id,
            user=user,
        )

    if invoice["status"] == "DRAFT":
        invoice = managed.transition_invoice_support(
            db,
            invoice["invoice_support_id"],
            "READY_FOR_OWNER_REVIEW",
            InvoiceSupportDecision(
                owner_notes=payload.owner_notes or "Review internal invoice-support draft. Not sent."
            ),
            organization_id=organization_id,
            user=user,
        )

    revenue = None
    if payload.record_estimated_revenue:
        existing_revenue = [
            item for item in ops.list_revenue_entries(
                db,
                organization_id=organization_id,
                user=user,
                engagement_id=engagement_id,
                limit=200,
            )
            if item.stage == "ESTIMATED"
            and item.currency == payload.currency.upper()
            and abs(float(item.amount) - subtotal) < 0.005
        ]
        if existing_revenue:
            revenue = existing_revenue[0]
        else:
            revenue = ops.create_revenue_entry(
                db,
                RevenueEntryCreate(
                    engagement_id=engagement_id,
                    stage="ESTIMATED",
                    amount=subtotal,
                    currency=payload.currency,
                    reconciliation_notes=(
                        "Estimated from owner-supplied invoice-support quantity/rate. "
                        "Not contracted, invoiced externally, or received."
                    ),
                ),
                organization_id=organization_id,
                user=user,
            )

    return {
        "engagement_id": engagement_id,
        "invoice_support": invoice,
        "estimated_revenue": revenue.model_dump() if hasattr(revenue, "model_dump") else revenue,
        "owner_supplied_quantity": payload.quantity,
        "owner_supplied_rate": payload.rate,
        "subtotal": subtotal,
        "invoice_sent": False,
        "stripe_invoice_created": False,
        "payment_intent_created": False,
        "payment_received": False,
        "estimated_equals_received": False,
    }
