"""Owner-authenticated Operations Agent CSV API skeleton.

Deliberately disabled until production storage, worker, retention and staging
validation are implemented. No customer data is accepted or processed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import UserContext
from app.core.nova.router import require_nova_access
from app.core.nova.service import NovaCoreService
from app.core.nova.work_revenue.router import require_work_revenue_owner

router = APIRouter(
    prefix="/api/nova/work/operations/csv-jobs",
    tags=["nova-operations-csv"],
    dependencies=[Depends(require_nova_access), Depends(require_work_revenue_owner)],
)


def _disabled() -> None:
    # No feature activation path until a separate implementation PR adds
    # real tenant-scoped persistence and a tested worker.
    raise HTTPException(
        status_code=503,
        detail="Operations CSV API is not enabled; secure storage and staging validation pending.",
    )


def _owner_scope(user: UserContext) -> str:
    """Resolve tenant from the authenticated owner session, never request fields.

    No database access, state change, queue creation or API activation here.
    """
    # Even privileged support accounts require a concrete session tenant.
    # A broad or absent scope must never reach an Operations assignment.
    session_org = getattr(user, "organization_id", None)
    if (
        not isinstance(session_org, str)
        or not session_org.strip()
        or session_org.strip().lower() == "global"
    ):
        raise HTTPException(status_code=403, detail="Tenant-specific organization required")
    try:
        org_id = NovaCoreService.resolve_organization_scope(user, None)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Authenticated organization required") from exc
    if (
        not isinstance(org_id, str)
        or not org_id.strip()
        or org_id.strip().lower() == "global"
        or org_id != session_org
    ):
        raise HTTPException(status_code=403, detail="Tenant-specific organization required")
    return org_id


@router.post("", status_code=503)
def submit_csv_job(user: UserContext = Depends(require_work_revenue_owner)):
    _owner_scope(user)
    _disabled()


@router.get("/{job_id}", status_code=503)
def csv_job_status(job_id: int, user: UserContext = Depends(require_work_revenue_owner)):
    _owner_scope(user)
    _disabled()


@router.post("/{job_id}/review", status_code=503)
def csv_job_review(job_id: int, user: UserContext = Depends(require_work_revenue_owner)):
    _owner_scope(user)
    _disabled()


@router.get("/{job_id}/download", status_code=503)
def csv_job_download(job_id: int, user: UserContext = Depends(require_work_revenue_owner)):
    _owner_scope(user)
    _disabled()
