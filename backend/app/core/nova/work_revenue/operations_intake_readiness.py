"""Read-only bridge contract between Work & Revenue and Nova Operations.

A sourced lead is never an approved customer assignment. This assessment only
identifies evidence still needed. It does not execute, submit, invoice, upload,
persist approvals, or issue an Operations handoff.
"""
from __future__ import annotations

from typing import Any


def assess_operations_readiness(opportunity: Any, engagement: dict[str, Any] | None) -> dict[str, Any]:
    """Assess already authorized, server-derived Work & Revenue records.

    The HTTP caller must independently enforce the AMICOR owner role and
    organization-specific database visibility before calling this function.
    Values here are advisory; no field authorizes execution.
    """
    opportunity_id = str(getattr(opportunity, "opportunity_id", "") or "").strip()
    tenant_id = str(getattr(opportunity, "organization_id", "") or "").strip()
    if not opportunity_id or not tenant_id or tenant_id.lower() == "global":
        raise ValueError("Tenant-scoped opportunity required")

    archived = bool(getattr(opportunity, "archived", False))
    engagement_id = str((engagement or {}).get("engagement_id") or "").strip()
    engagement_tenant = str((engagement or {}).get("organization_id") or "").strip()
    engagement_opportunity = str((engagement or {}).get("opportunity_id") or "").strip()
    linked = bool(
        engagement_id and engagement_tenant == tenant_id
        and engagement_opportunity == opportunity_id
    )
    status = str((engagement or {}).get("status") or "").strip().upper()
    blockers = str((engagement or {}).get("blockers") or "").strip()
    tasks = (engagement or {}).get("tasks") if linked else []
    if not isinstance(tasks, list):
        tasks = []
    # A task tagged NOVA is not authorization to execute it.
    nova_tasks = [
        {
            "task_id": str(t.get("task_id") or ""),
            "title": str(t.get("title") or ""),
            "status": str(t.get("status") or ""),
            "review_required": bool(t.get("review_required", True)),
        }
        for t in tasks if isinstance(t, dict)
        and str(t.get("responsible_party") or "").strip().upper() == "NOVA"
    ]
    checklist: list[str] = []
    if archived:
        checklist.append("Restore or independently requalify the archived opportunity.")
    if not linked:
        checklist.append("Link an owner-verified engagement to this opportunity.")
    else:
        checklist.append("Verify the customer's acceptance and AMICOR's delivery authority.")
        if status not in {"ACTIVE", "IN_PROGRESS", "WON", "CONTRACTED"}:
            checklist.append("Confirm the engagement is active or won; a lead alone is not client work.")
        if blockers:
            checklist.append("Resolve recorded engagement blockers before execution.")
        if not nova_tasks:
            checklist.append("Define at least one bounded Nova Operations task with a review requirement.")
    checklist.append("Approve the exact scope, authorized input files, and data-handling terms.")
    checklist.append("Provision isolated tenant storage and verified owner-session authorization.")

    return {
        "opportunity_id": opportunity_id,
        "organization_id": tenant_id,
        "engagement_id": engagement_id if linked else None,
        "engagement_status": status if linked else None,
        "nova_task_previews": nova_tasks,
        "readiness": "blocked" if (archived or not linked or blockers) else "owner_review_required",
        "required_owner_actions": checklist,
        "handoff_created": False,
        "customer_upload_enabled": False,
        "external_actions_performed": False,
        "payment_or_revenue_confirmed": False,
        "execution_authorized": False,
    }
