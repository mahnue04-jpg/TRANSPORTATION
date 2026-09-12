"""Nova V2 Phase 4 result verification. Reads authoritative draft/task stores only."""
from __future__ import annotations

from typing import Literal

from app.auth import UserContext
from app.core.nova.today.models import NovaV2CommandAction
from sqlalchemy.orm import Session

VerificationState = Literal["verified", "missing", "unavailable", "unknown"]


def verify_result(
    db: Session,
    row: NovaV2CommandAction,
    *,
    organization_id: str,
    user: UserContext,
) -> VerificationState:
    if not row.result_ref_id:
        return "unknown"
    if row.recommended_action == "create_draft":
        return _verify_draft(db, row.result_ref_id, user=user)
    if row.recommended_action == "create_task":
        return _verify_task(db, row.result_ref_id, organization_id=organization_id, user=user)
    return "unknown"


def _verify_draft(db: Session, draft_id: str, *, user: UserContext) -> VerificationState:
    try:
        from app.core.nova.communications.service import list_drafts

        drafts = list_drafts(db, user=user)
        if any(str(item.id) == str(draft_id) for item in drafts):
            return "verified"
        return "missing"
    except Exception:
        return "unavailable"


def _verify_task(
    db: Session,
    task_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> VerificationState:
    try:
        from app.core.nova.business.service import NovaBusinessError, get_task

        get_task(db, task_id, organization_id=organization_id, user=user)
        return "verified"
    except NovaBusinessError as exc:
        if getattr(exc, "status_code", 400) == 404:
            return "missing"
        return "unavailable"
    except Exception:
        return "unavailable"


def verification_label(result_type: str | None, state: VerificationState | None) -> str:
    if not state or state == "unknown":
        return result_type or ""
    if state == "verified" and result_type == "draft_created":
        return "Draft created — verified"
    if state == "verified" and result_type == "task_created":
        return "Task created — verified"
    if state == "missing" and result_type == "draft_created":
        return "Draft reference missing"
    if state == "missing" and result_type == "task_created":
        return "Task reference missing"
    if state == "unavailable":
        return "Verification unavailable"
    if result_type == "source_rechecked":
        return f"Source re-checked — {state}"
    return f"{result_type or 'result'} — {state}"
