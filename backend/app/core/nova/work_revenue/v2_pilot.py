"""Owner-only V2 pilot workflow snapshot. No live adapters."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.managed import reconciliation as v1_reconciliation
from app.core.nova.work_revenue.models import NovaWorkApplication
from app.core.nova.work_revenue.service import _ensure_v2, _owner_filter, get_opportunity
from app.core.nova.work_revenue.v2_revenue import revenue_preparation
from app.core.nova.work_revenue.v2_status import LIVE_DISABLED

STEPS = (
    "create_or_import_opportunity",
    "qualify",
    "prepare_materials",
    "owner_review",
    "owner_approve",
    "record_manual_external_submission",
    "convert_to_engagement",
    "track_tasks_deliverables",
    "owner_confirms_delivered",
    "prepare_invoice_support",
    "owner_records_received_revenue",
    "dashboard_separated_totals",
)


def _next_action(opportunity: dict[str, Any], application: NovaWorkApplication | None) -> str:
    status = str(opportunity.get("status") or "")
    if status in {"DISCOVERED", "REVIEWING"}:
        return "Qualify the opportunity. OWNER ACTION REQUIRED if facts are missing."
    if status in {"QUALIFIED", "OWNER_REVIEW"}:
        return "Prepare application/work materials. NOVA PREPARED drafts stay internal."
    if application and application.approval_state == "READY_FOR_OWNER_REVIEW":
        return "Owner review. Approval is not submission."
    if application and application.approved_for_future_submission and not application.manual_submission_recorded:
        return "Record MANUAL_EXTERNAL_SUBMISSION only after the owner actually submits. NOT SENT BY NOVA."
    if status == "SUBMITTED":
        return "If won/accepted, convert to an internal engagement. Nova does not contact the client."
    if status == "WON":
        return "Track tasks and deliverables. PAYMENT NOT CONFIRMED until the owner records received cash."
    if status in {"CLOSED", "REJECTED"}:
        return "Historical/archived. No ordinary financial mutation."
    return "Continue owner-controlled tracking. RECEIVED CONFIRMED BY OWNER is the only received-cash signal."


def pilot_workflow(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    opportunity_id: str | None = None,
) -> dict[str, Any]:
    _ensure_v2()
    opportunity = None
    application = None
    if opportunity_id:
        row = get_opportunity(db, opportunity_id, organization_id=organization_id, user=user)
        opportunity = {
            "opportunity_id": row.opportunity_id,
            "source": row.source,
            "company_name": row.company_name,
            "opportunity_title": row.opportunity_title,
            "description": row.description,
            "estimated_value": row.estimated_value if row.estimated_value is not None else row.compensation_amount,
            "qualification": row.qualification_outcome,
            "status": row.status,
            "owner_user_id": row.owner_user_id,
            "created_at": row.discovered_at.isoformat() if row.discovered_at else None,
            "archived": bool(row.archived),
        }
        application = (
            _owner_filter(
                db.query(NovaWorkApplication).filter(
                    NovaWorkApplication.organization_id == organization_id,
                    NovaWorkApplication.opportunity_id == row.opportunity_id,
                ),
                NovaWorkApplication,
                user,
            ).first()
        )
    recon = v1_reconciliation(db, organization_id=organization_id, user=user)
    prep = revenue_preparation(db, organization_id=organization_id, user=user, reconciliation=recon)
    return {
        "pilot": True,
        "live_adapters": False,
        "nova_claims_external_submission": False,
        "steps": list(STEPS),
        "labels": {
            "OWNER_ACTION_REQUIRED": True,
            "NOVA_PREPARED": True,
            "MANUALLY_SUBMITTED": True,
            "NOT_SENT_BY_NOVA": True,
            "PAYMENT_NOT_CONFIRMED": True,
            "RECEIVED_CONFIRMED_BY_OWNER": True,
        },
        "opportunity": opportunity,
        "application": None
        if application is None
        else {
            "application_id": application.application_id,
            "approval_state": application.approval_state,
            "approved_for_future_submission": bool(application.approved_for_future_submission),
            "manual_submission_recorded": bool(application.manual_submission_recorded),
            "externally_submitted": False,
            "not_sent_by_nova": True,
        },
        "next_action": _next_action(opportunity or {}, application),
        "dashboard": {
            "pipeline_value": prep.get("expected_revenue"),
            "contracted_value": prep.get("contracted_revenue"),
            "billed_support_value": prep.get("client_billed"),
            "received": prep.get("amicor_received"),
            "remaining": prep.get("remaining_balance"),
            "historical_received": prep.get("archived_historical_revenue"),
            "active_received": prep.get("amicor_received"),
            "partially_paid": prep.get("partially_paid"),
            "categories_mixed": False,
            "owner_confirmation_authoritative": True,
        },
        "live_capabilities": LIVE_DISABLED,
    }
