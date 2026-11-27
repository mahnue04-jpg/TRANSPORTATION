"""Unregistered staging contract for Operations owner approvals.

DO NOT mount this router into the app. The offline SQLite implementation is
not customer storage and no authenticated production assignment endpoint is
available. The existing dependency grants owner-only access; this skeleton
always denies execution even to owners.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import UserContext, get_current_user_context
from app.core.nova.router import require_nova_access
from app.core.nova.work_revenue.router import require_work_revenue_owner
from app.core.nova.work_revenue.operations_owner_scope import owner_approval_identity

router = APIRouter(
    prefix="/api/nova/work/operations/owner-approvals",
    tags=["nova-operations-approval-staging-disabled"],
    dependencies=[Depends(require_nova_access), Depends(require_work_revenue_owner)],
)


@router.post("/{opportunity_id}", status_code=503)
def disabled_approval_staging(
    opportunity_id: str,
    user: UserContext = Depends(require_work_revenue_owner),
) -> None:
    """Fail closed until an explicitly approved staging implementation exists."""
    owner_approval_identity(user)
    raise HTTPException(
        status_code=503,
        detail="Operations approval endpoint disabled; secure storage and staging approval pending.",
    )


@router.post("/{opportunity_id}/review", status_code=503)
def disabled_review_staging(
    opportunity_id: str,
    user: UserContext = Depends(require_work_revenue_owner),
) -> None:
    """Never write review decisions from this unregistered skeleton."""
    owner_approval_identity(user)
    raise HTTPException(
        status_code=503,
        detail="Operations review endpoint disabled; secure storage and staging approval pending.",
    )
