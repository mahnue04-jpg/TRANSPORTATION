"""Phase 2B CRUD, Phase 2C transitions, and Phase 2H supervised jobs. No background runner."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.autonomy import v2_jobs, v2_service
from app.core.nova.autonomy.models import (
    AutonomyApprovalOut,
    AutonomyJobOut,
    AutonomyJobQueueRequest,
    AutonomyOrgFlagOut,
    AutonomyWorkflowCreate,
    AutonomyWorkflowOut,
)
from app.core.nova.router import require_nova_access
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/autonomy/v2",
    tags=["nova-autonomy-v2"],
    dependencies=[Depends(require_nova_access)],
)


def _raise(exc: Exception) -> None:
    if isinstance(exc, v2_service.Phase2BError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise exc


@router.get("/org-flag", response_model=AutonomyOrgFlagOut)
def get_org_flag(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_service.read_org_flag(db, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.get("/workflows", response_model=list[AutonomyWorkflowOut])
def list_workflows(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_service.list_workflows(db, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.post("/workflows", response_model=AutonomyWorkflowOut)
def create_workflow(
    payload: AutonomyWorkflowCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        return v2_service.create_workflow(db, payload, user=user, idempotency_key=idempotency_key)
    except Exception as exc:
        _raise(exc)


@router.get("/workflows/{workflow_id}", response_model=AutonomyWorkflowOut)
def get_workflow(
    workflow_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_service.get_workflow(db, workflow_id, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.get("/workflows/{workflow_id}/history")
def get_workflow_history(
    workflow_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_service.workflow_history(db, workflow_id, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.get("/workflows/{workflow_id}/approvals", response_model=list[AutonomyApprovalOut])
def get_workflow_approvals(
    workflow_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_service.list_approvals(db, workflow_id, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.post("/workflows/{workflow_id}/approve", response_model=AutonomyWorkflowOut)
def approve_workflow(
    workflow_id: str,
    organization_id: str | None = None,
    step_count: int | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        return v2_service.approve_workflow(
            db,
            workflow_id,
            user=user,
            requested_org=organization_id,
            idempotency_key=idempotency_key,
            step_count=step_count,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/workflows/{workflow_id}/cancel", response_model=AutonomyWorkflowOut)
def cancel_workflow(
    workflow_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_service.cancel_workflow(db, workflow_id, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.post("/workflows/{workflow_id}/pause", response_model=AutonomyWorkflowOut)
def pause_workflow(
    workflow_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_service.pause_workflow(db, workflow_id, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.post("/workflows/{workflow_id}/retry", response_model=AutonomyWorkflowOut)
def retry_workflow(
    workflow_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_service.retry_workflow(db, workflow_id, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.post("/workflows/{workflow_id}/resume", response_model=AutonomyWorkflowOut)
def resume_workflow(
    workflow_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_service.resume_workflow(db, workflow_id, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.post("/workflows/{workflow_id}/steps/{step_id}/approve", response_model=AutonomyWorkflowOut)
def approve_step(
    workflow_id: str,
    step_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        return v2_service.approve_step(
            db,
            workflow_id,
            step_id,
            user=user,
            requested_org=organization_id,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/emergency-stop")
def emergency_stop(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_service.emergency_stop(db, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.get("/jobs", response_model=list[AutonomyJobOut])
def list_jobs(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_jobs.list_jobs(db, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.post("/jobs", response_model=AutonomyJobOut)
def queue_job(
    payload: AutonomyJobQueueRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_jobs.queue_job(
            db,
            user=user,
            workflow_id=payload.workflow_id,
            step_id=payload.step_id,
            requested_org=payload.organization_id,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/jobs/claim-next", response_model=AutonomyJobOut)
def claim_next_job(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_jobs.claim_next_job(db, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.get("/jobs/{job_id}", response_model=AutonomyJobOut)
def get_job(
    job_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_jobs.get_job(db, job_id, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.post("/jobs/{job_id}/claim", response_model=AutonomyJobOut)
def claim_job(
    job_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_jobs.claim_job(db, job_id, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.post("/jobs/{job_id}/run", response_model=AutonomyJobOut)
def run_job(
    job_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_jobs.run_job(db, job_id, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.post("/jobs/{job_id}/cancel", response_model=AutonomyJobOut)
def cancel_job(
    job_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_jobs.cancel_job(db, job_id, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)


@router.post("/jobs/{job_id}/retry", response_model=AutonomyJobOut)
def retry_job(
    job_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return v2_jobs.retry_job(db, job_id, user=user, requested_org=organization_id)
    except Exception as exc:
        _raise(exc)
