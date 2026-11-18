"""Authenticated owner-task authorization adapter for Operations pipeline.

Only for explicitly owner-invoked, development-only execution. Caller must
first pass the actual FastAPI require_work_revenue_owner dependency result;
this module never manufactures a user context or service principal. A hosted
background runner requires a separate revocable service authorization design.
"""
from __future__ import annotations

from collections.abc import Callable
from sqlalchemy.orm import Session

from .operations_owner_csv_api import _check_saved_csv_assignment


class OwnerTaskAuthorizationBlocked(ValueError):
    pass


def owner_task_authorizer(
    session_factory: Callable[[], Session], *, authenticated_owner,
) -> Callable[[str, str, str, str], bool]:
    """Return a fail-closed callback rechecking the live saved-task assignment."""
    owner_id = str(getattr(authenticated_owner, "user_id", "") or "")
    organization_id = str(getattr(authenticated_owner, "organization_id", "") or "")
    if (not owner_id or not organization_id
            or organization_id.lower() == "global"):
        raise OwnerTaskAuthorizationBlocked("Specific authenticated owner required")

    def authorize(org: str, owner: str, engagement: str, task: str) -> bool:
        if org != organization_id or owner != owner_id:
            return False
        if not isinstance(engagement, str) or not engagement:
            return False
        if not isinstance(task, str) or not task:
            return False
        try:
            with session_factory() as db:
                _check_saved_csv_assignment(
                    db, owner=authenticated_owner,
                    engagement_id=engagement, task_id=task)
        except Exception:
            return False
        return True

    return authorize
