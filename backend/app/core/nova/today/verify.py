"""Nova V2 Phase 4 result verification. Reads authoritative draft/task stores only."""
from __future__ import annotations

from typing import Literal

from app.auth import UserContext
from app.core.nova.today.db_recovery import recover_today_session
from app.core.nova.today.models import NovaV2CommandAction
from sqlalchemy.orm import Session

VerificationState = Literal["verified", "missing", "unavailable", "unknown"]


class DraftTenantDenied(PermissionError):
    """Raised when a draft exists but belongs to another tenant."""


def verify_result(
    db: Session,
    row: NovaV2CommandAction,
    *,
    organization_id: str,
    user: UserContext,
) -> VerificationState:
    if row.recommended_action == "create_draft" and not row.result_ref_id:
        return "unknown"
    if not row.result_ref_id:
        return "unknown"
    if row.recommended_action == "create_draft":
        try:
            return verify_draft_by_ref(
                db, row.result_ref_id, organization_id=organization_id, user=user
            )
        except DraftTenantDenied:
            return "missing"
    if row.recommended_action == "create_task":
        return _verify_task(db, row.result_ref_id, organization_id=organization_id, user=user)
    return "unknown"


def verify_draft_by_ref(
    db: Session,
    draft_id: str | None,
    *,
    organization_id: str,
    user: UserContext,
) -> VerificationState:
    """Load the exact draft by id. Tenant-safe. Does not use current-user list_drafts."""
    if not draft_id:
        return "unknown"
    try:
        from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, normalize_role
        from app.db.models import EmailDraftRecord
        from app.db.models import User as UserModel

        draft = db.query(EmailDraftRecord).filter(EmailDraftRecord.id == str(draft_id)).first()
        if draft is None:
            return "missing"
        owner = db.query(UserModel).filter(UserModel.id == draft.user_id).first()
        owner_org = getattr(owner, "organization_id", None) if owner is not None else None
        if organization_id and owner_org and owner_org != organization_id:
            raise DraftTenantDenied("Cross-tenant draft lookup is denied")
        viewer_is_admin = normalize_role(user.role) in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}
        if user.user_id != draft.user_id and not viewer_is_admin:
            return "missing"
        return "verified"
    except DraftTenantDenied:
        raise
    except Exception:
        recover_today_session(db)
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
        recover_today_session(db)
        return "unavailable"
    except Exception:
        recover_today_session(db)
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
