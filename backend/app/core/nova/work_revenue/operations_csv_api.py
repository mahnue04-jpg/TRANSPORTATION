"""Owner-authenticated Operations Agent CSV API skeleton.

Deliberately disabled until production storage, worker, retention and staging
validation are implemented. No customer data is accepted or processed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import UserContext, get_current_user_context
from app.core.nova.router import require_nova_access
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


@router.post("", status_code=503)
def submit_csv_job(user: UserContext = Depends(get_current_user_context)):
    _disabled()


@router.get("/{job_id}", status_code=503)
def csv_job_status(job_id: int, user: UserContext = Depends(get_current_user_context)):
    _disabled()


@router.post("/{job_id}/review", status_code=503)
def csv_job_review(job_id: int, user: UserContext = Depends(get_current_user_context)):
    _disabled()


@router.get("/{job_id}/download", status_code=503)
def csv_job_download(job_id: int, user: UserContext = Depends(get_current_user_context)):
    _disabled()
