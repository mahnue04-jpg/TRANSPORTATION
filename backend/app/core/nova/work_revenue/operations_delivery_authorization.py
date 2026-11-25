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

def _reject_queued_job_in_legacy_path(
    db: Session, *, job_id: str, owner: UserContext,

