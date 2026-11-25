"""Narrow owner authorization checks for staging CSV delivery."""
from __future__ import annotations
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.auth import UserContext
from . import service

def _csv_task_scope(task: dict) -> bool:
    """Only tasks explicitly described as CSV/spreadsheet cleanup are eligible.

    General Nova administrative work is not authorization to transform files.
    This label gate is intentionally narrow; a future structured work-type
    authorization should replace text labels before customer production.
    """
    description = " ".join(
        str(task.get(field) or "").strip().lower()
        for field in ("title", "description", "deliverable")
    )
    return any(
        label in description
        for label in (
            "csv", "spreadsheet cleanup", "spreadsheet cleaning",
            "data cleanup", "data cleaning", "data validation",
            "data reconciliation",
        )
    )

def _eligible_engagement(engagement: dict, org: str, owner_id: str) -> bool:
    """Same fail-closed gate for owner task listing and processing."""
    return (
        str(engagement.get("organization_id") or "") == org
        and str(engagement.get("owner_user_id") or "") == owner_id
        and str(engagement.get("status") or "").strip().upper() == "ACTIVE"
        and not str(engagement.get("blockers") or "").strip()
    )

def _eligible_task(task: dict, completed_task_ids: set[str]) -> bool:
    """Restrict CSV work to unblocked, explicitly scoped supervised Nova tasks."""
    dependency = str(task.get("depends_on_task_id") or "").strip()
    return (
        _csv_task_scope(task)
        and str(task.get("classification") or "").strip().upper() == "NOVA"
        and str(task.get("responsible_party") or "").strip().upper() == "NOVA"
        and task.get("review_required") is True
        and str(task.get("status") or "").strip().upper()
        in {"READY", "NOT_STARTED", "IN_PROGRESS"}
        and not str(task.get("blocked_reason") or "").strip()
        and not str(task.get("required_owner_input") or "").strip()
        and (not dependency or dependency in completed_task_ids)
    )

def _completed_task_ids(engagement: dict) -> set[str]:
    return {
        str(task.get("task_id") or "")
        for task in engagement.get("tasks") or []
        if isinstance(task, dict)
        and str(task.get("status") or "").strip().upper() == "COMPLETE"
    }

def _check_saved_csv_assignment(
    db: Session, *, owner: UserContext, engagement_id: str, task_id: str,
) -> None:
    org = str(getattr(owner, "organization_id", "") or "").strip()
    if not org or org.lower() == "global":
        raise HTTPException(403, "Specific owner organization required")
    try:
        engagement = service.get_engagement(
            db, engagement_id, organization_id=org, user=owner,
        )
    except service.NovaWorkError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if not _eligible_engagement(engagement, org, str(owner.user_id)):
        raise HTTPException(409, "Engagement no longer eligible")
    task = next(
        (item for item in engagement.get("tasks") or []
         if isinstance(item, dict) and item.get("task_id") == task_id),
        None,
    )
    if task is None:
        raise HTTPException(404, "Task not found on authorized engagement")
    if not _eligible_task(task, _completed_task_ids(engagement)):
        raise HTTPException(409, "Task not authorized for CSV processing")


def _reject_queued_job_in_legacy_path(
    db: Session, *, job_id: str, owner: UserContext,
) -> None:
    """Prevent legacy review/download/recover from bypassing queued lease gates.

    The original synchronous path remains available if the lease table has not
    been migrated. Database inspection errors fail closed instead of treating
    queued jobs as unguarded legacy work.
    """
    import sqlalchemy as sa
    from sqlalchemy import MetaData, Table

    try:
        table_name = "nova_operations_processing_leases"
        if not sa.inspect(db.get_bind()).has_table(table_name):
            return
        lease_jobs = Table(table_name, MetaData(), autoload_with=db.get_bind())
        scoped = db.execute(sa.select(lease_jobs.c.job_id).where(
            lease_jobs.c.job_id == job_id,
            lease_jobs.c.organization_id == str(owner.organization_id),
            lease_jobs.c.owner_user_id == str(owner.user_id),
        )).first()
    except Exception as exc:
        raise HTTPException(503, "CSV job mode cannot be verified") from exc
    if scoped is not None:
        raise HTTPException(409, "Queued job requires supervised owner workflow")
