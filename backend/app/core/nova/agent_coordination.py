"""Owner-only coordination view shared by Work & Revenue and Operations Agent."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.models import NovaWorkOpportunity, NovaWorkOwnerAction
from app.modules.marketing.models import MarketingWebsiteLead, ensure_marketing_schema

WORK_TO_OPS_STATUSES = {
    "QUALIFIED",
    "OWNER_REVIEW",
    "APPROVED_TO_APPLY",
    "APPLICATION_PREPARED",
    "SUBMITTED",
    "FOLLOW_UP_DUE",
    "INTERVIEW",
    "OFFER",
    "WON",
}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def coordination_snapshot(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    limit: int = 50,
) -> dict[str, Any]:
    """Return a minimal shared handoff feed. No external action is performed."""
    ensure_marketing_schema()
    cap = max(1, min(int(limit or 50), 100))

    work_rows = (
        db.query(NovaWorkOpportunity)
        .filter(
            NovaWorkOpportunity.organization_id == organization_id,
            NovaWorkOpportunity.owner_user_id == user.user_id,
            NovaWorkOpportunity.archived.is_(False),
            NovaWorkOpportunity.status.in_(WORK_TO_OPS_STATUSES),
        )
        .order_by(NovaWorkOpportunity.updated_at.desc())
        .limit(cap)
        .all()
    )
    action_rows = (
        db.query(NovaWorkOwnerAction)
        .filter(
            NovaWorkOwnerAction.organization_id == organization_id,
            NovaWorkOwnerAction.owner_user_id == user.user_id,
            NovaWorkOwnerAction.status == "OPEN",
        )
        .all()
    )
    action_by_opp: dict[str, list[str]] = {}
    for action in action_rows:
        if action.opportunity_id:
            action_by_opp.setdefault(action.opportunity_id, []).append(action.action_type)

    operations_rows = (
        db.query(MarketingWebsiteLead)
        .filter(
            MarketingWebsiteLead.lead_type == "anonymous_operations",
            MarketingWebsiteLead.status.in_(["new", "contacted", "qualified"]),
        )
        .order_by(MarketingWebsiteLead.created_at.desc())
        .limit(cap)
        .all()
    )

    return {
        "roles": {
            "work_revenue": "Find, qualify, pursue, track, contract, invoice-support, and revenue follow-up.",
            "operations_agent": "Scope, prepare, execute supported operations work, quality-check, and escalate owner decisions.",
        },
        "work_revenue_to_operations": [
            {
                "opportunity_id": row.opportunity_id,
                "company_name": row.company_name,
                "title": row.opportunity_title,
                "stage": row.status,
                "estimated_value": row.estimated_value,
                "priority": row.priority,
                "next_follow_up_at": _iso(row.follow_up_at),
                "owner_actions": action_by_opp.get(row.opportunity_id, []),
                "operations_instruction": (
                    "Prepare to scope and deliver supported work if this lead converts. "
                    "Do not contact the prospect or make commitments from this feed."
                ),
                "updated_at": _iso(row.updated_at),
            }
            for row in work_rows
        ],
        "operations_to_work_revenue": [
            {
                "lead_id": row.id,
                "organization_name": row.organization_name,
                "contact_name": row.contact_name,
                "status": row.status,
                "service_plan": row.service_plan,
                "lead_source": row.lead_source,
                "work_revenue_instruction": (
                    "Track commercial follow-up, qualification, proposal/contract state, and revenue status. "
                    "Do not mark won or paid without evidence."
                ),
                "created_at": _iso(row.created_at),
            }
            for row in operations_rows
        ],
        "owner_approval_required": len(action_rows),
        "rules": {
            "shared_context": True,
            "separate_responsibilities": True,
            "operations_agent_may_contact_prospect_from_feed": False,
            "work_revenue_may_execute_delivery_from_feed": False,
            "owner_approval_controls_preserved": True,
        },
    }
