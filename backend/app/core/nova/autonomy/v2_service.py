"""Phase 2B tenant-scoped workflow CRUD. Header persist only. No execution."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.autonomy import ledger
from app.core.nova.autonomy.models import (
    AutonomyApprovalOut,
    AutonomyOrgFlagOut,
    AutonomyWorkflowCreate,
    AutonomyWorkflowOut,
    NovaAutonomyApproval,
    NovaAutonomyExecutionAttempt,
    NovaAutonomyLedger,
    NovaAutonomyOrgFlag,
    NovaAutonomyWorkflow,
    NovaAutonomyWorkflowStep,
    new_approval_id,
    new_attempt_id,
    new_step_id,
    new_workflow_id,
)
from app.core.nova.autonomy.policy import can_act
from app.core.nova.autonomy.v2_states import (
    INTERNAL_TEST_ACTION,
    OPEN_STATUSES,
    STEP_APPROVE_FROM,
    next_status,
)
from app.core.nova.autonomy.v2_templates import validate_create
from app.helpers import now, uuid4


class Phase2BError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _caller_org(user: UserContext, requested: str | None) -> str:
    org_id = (user.organization_id or "").strip()
    if not org_id:
        raise Phase2BError("Organization scope is required for Nova", status_code=400)
    if requested and requested != org_id:
        raise Phase2BError("Cross-tenant Nova access denied", status_code=403)
    return org_id


def _new_correlation_id() -> str:
    return "NWC-" + uuid4().replace("-", "")[:12].upper()


def _workflow_out(db: Session, row: NovaAutonomyWorkflow) -> AutonomyWorkflowOut:
    steps = (
        db.query(NovaAutonomyWorkflowStep)
        .filter(
            NovaAutonomyWorkflowStep.organization_id == row.organization_id,
            NovaAutonomyWorkflowStep.workflow_id == row.workflow_id,
        )
        .order_by(NovaAutonomyWorkflowStep.sequence_number.asc())
        .all()
    )
    approvals = (
        db.query(NovaAutonomyApproval)
        .filter(
            NovaAutonomyApproval.organization_id == row.organization_id,
            NovaAutonomyApproval.workflow_id == row.workflow_id,
        )
        .order_by(NovaAutonomyApproval.created_at.asc())
        .all()
    )
    return AutonomyWorkflowOut.from_row(row, steps=steps, approvals=approvals)


def _existing_for_key(db: Session, *, organization_id: str, idempotency_key: str) -> AutonomyWorkflowOut | None:
    prior = ledger.latest_for_idempotency(
        db, organization_id=organization_id, idempotency_key=idempotency_key
    )
    if prior is None or not prior.workflow_id:
        return None
    row = (
        db.query(NovaAutonomyWorkflow)
        .filter(
            NovaAutonomyWorkflow.organization_id == organization_id,
            NovaAutonomyWorkflow.workflow_id == prior.workflow_id,
        )
        .first()
    )
    if row is None:
        return None
    return _workflow_out(db, row)


def create_workflow(
    db: Session,
    payload: AutonomyWorkflowCreate,
    *,
    user: UserContext,
    idempotency_key: str | None = None,
) -> AutonomyWorkflowOut:
    if not can_act(user):
        raise Phase2BError("Owner or admin approval is required to create a workflow", status_code=403)
    organization_id = _caller_org(user, payload.organization_id)
    _require_not_stopped(db, organization_id)
    try:
        workflow_type, initiating_module, _action = validate_create(
            workflow_type=payload.workflow_type,
            initiating_module=payload.initiating_module,
            action_type=payload.action_type,
        )
    except ValueError as exc:
        raise Phase2BError(str(exc), status_code=400) from exc

    key = (idempotency_key or payload.idempotency_key or "").strip()
    if key:
        existing = _existing_for_key(db, organization_id=organization_id, idempotency_key=key)
        if existing is not None:
            return existing

    workflow = NovaAutonomyWorkflow(
        workflow_id=new_workflow_id(),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        correlation_id=_new_correlation_id(),
        workflow_type=workflow_type,
        initiating_module=initiating_module,
        source_ref_id=payload.source_ref_id.strip(),
        status="proposed",
        current_step=None,
        retry_count=0,
        created_at=now(),
        updated_at=now(),
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    ledger.append(
        db,
        user=user,
        organization_id=organization_id,
        action_type="propose_workflow",
        risk_class="LOW",
        approval_state="proposed",
        source_module=initiating_module,
        source_ref_id=workflow.source_ref_id,
        executed=False,
        correlation_id=workflow.correlation_id,
        idempotency_key=key or None,
        result_ref_id=workflow.workflow_id,
        target=workflow.workflow_type,
        result="workflow_proposed",
        detail="header_only",
        workflow_id=workflow.workflow_id,
        target_module=initiating_module,
    )
    return _workflow_out(db, workflow)


def list_workflows(db: Session, *, user: UserContext, requested_org: str | None = None) -> list[AutonomyWorkflowOut]:
    organization_id = _caller_org(user, requested_org)
    rows = (
        db.query(NovaAutonomyWorkflow)
        .filter(NovaAutonomyWorkflow.organization_id == organization_id)
        .order_by(NovaAutonomyWorkflow.created_at.desc())
        .limit(50)
        .all()
    )
    return [_workflow_out(db, row) for row in rows]


def get_workflow(
    db: Session, workflow_id: str, *, user: UserContext, requested_org: str | None = None
) -> AutonomyWorkflowOut:
    organization_id = _caller_org(user, requested_org)
    row = (
        db.query(NovaAutonomyWorkflow)
        .filter(
            NovaAutonomyWorkflow.organization_id == organization_id,
            NovaAutonomyWorkflow.workflow_id == workflow_id,
        )
        .first()
    )
    if row is None:
        raise Phase2BError("Workflow not found", status_code=404)
    return _workflow_out(db, row)


def workflow_history(
    db: Session, workflow_id: str, *, user: UserContext, requested_org: str | None = None
) -> list[dict]:
    organization_id = _caller_org(user, requested_org)
    exists = (
        db.query(NovaAutonomyWorkflow.workflow_id)
        .filter(
            NovaAutonomyWorkflow.organization_id == organization_id,
            NovaAutonomyWorkflow.workflow_id == workflow_id,
        )
        .first()
    )
    if exists is None:
        raise Phase2BError("Workflow not found", status_code=404)
    rows = (
        db.query(NovaAutonomyLedger)
        .filter(
            NovaAutonomyLedger.organization_id == organization_id,
            NovaAutonomyLedger.workflow_id == workflow_id,
        )
        .order_by(NovaAutonomyLedger.created_at.asc())
        .limit(100)
        .all()
    )
    return [
        {
            "audit_id": row.audit_id,
            "correlation_id": row.correlation_id,
            "workflow_id": row.workflow_id,
            "action_type": row.action_type,
            "source_module": row.source_module,
            "source_ref_id": row.source_ref_id,
            "risk_class": row.risk_class,
            "approval_state": row.approval_state,
            "executed": bool(row.executed),
            "result": row.result,
            "organization_id": row.organization_id,
            "timestamp": row.created_at,
            "detail": row.detail,
        }
        for row in rows
    ]


def list_approvals(
    db: Session, workflow_id: str, *, user: UserContext, requested_org: str | None = None
) -> list[AutonomyApprovalOut]:
    return get_workflow(db, workflow_id, user=user, requested_org=requested_org).approvals


def read_org_flag(db: Session, *, user: UserContext, requested_org: str | None = None) -> AutonomyOrgFlagOut:
    organization_id = _caller_org(user, requested_org)
    flag = db.get(NovaAutonomyOrgFlag, organization_id)
    if flag is None:
        return AutonomyOrgFlagOut(organization_id=organization_id, phase2_enabled=False, emergency_stop=False)
    return AutonomyOrgFlagOut(
        organization_id=flag.organization_id,
        phase2_enabled=bool(flag.phase2_enabled),
        emergency_stop=bool(flag.emergency_stop),
        disabled_at=flag.disabled_at,
        disabled_by=flag.disabled_by,
    )


def _require_actor(user: UserContext) -> None:
    if not can_act(user):
        raise Phase2BError("Owner or admin approval is required", status_code=403)


def _org_flag(db: Session, organization_id: str) -> NovaAutonomyOrgFlag | None:
    return db.get(NovaAutonomyOrgFlag, organization_id)


def _require_not_stopped(db: Session, organization_id: str) -> None:
    flag = _org_flag(db, organization_id)
    if flag is not None and flag.emergency_stop:
        raise Phase2BError("Emergency stop is active for this organization", status_code=403)


def _load_workflow(db: Session, workflow_id: str, organization_id: str) -> NovaAutonomyWorkflow:
    row = (
        db.query(NovaAutonomyWorkflow)
        .filter(
            NovaAutonomyWorkflow.organization_id == organization_id,
            NovaAutonomyWorkflow.workflow_id == workflow_id,
        )
        .first()
    )
    if row is None:
        raise Phase2BError("Workflow not found", status_code=404)
    return row


def _audit(
    db: Session,
    *,
    user: UserContext,
    workflow: NovaAutonomyWorkflow,
    action_type: str,
    approval_state: str,
    result: str,
    detail: str,
    executed: bool = False,
    step_id: str | None = None,
    result_ref_id: str | None = None,
    idempotency_key: str | None = None,
    attempt_number: int | None = None,
) -> None:
    ledger.append(
        db,
        user=user,
        organization_id=workflow.organization_id,
        action_type=action_type,
        risk_class="LOW",
        approval_state=approval_state,
        source_module=workflow.initiating_module,
        source_ref_id=workflow.source_ref_id,
        executed=executed,
        correlation_id=workflow.correlation_id,
        idempotency_key=idempotency_key,
        result_ref_id=result_ref_id or workflow.workflow_id,
        target=workflow.workflow_type,
        result=result,
        detail=detail,
        workflow_id=workflow.workflow_id,
        step_id=step_id,
        target_module="autonomy",
        approver_user_id=user.user_id if can_act(user) else None,
        attempt_number=attempt_number,
    )


def _ensure_internal_step(db: Session, workflow: NovaAutonomyWorkflow) -> NovaAutonomyWorkflowStep:
    existing = (
        db.query(NovaAutonomyWorkflowStep)
        .filter(
            NovaAutonomyWorkflowStep.organization_id == workflow.organization_id,
            NovaAutonomyWorkflowStep.workflow_id == workflow.workflow_id,
        )
        .order_by(NovaAutonomyWorkflowStep.sequence_number.asc())
        .first()
    )
    if existing is not None:
        return existing
    step = NovaAutonomyWorkflowStep(
        step_id=new_step_id(),
        workflow_id=workflow.workflow_id,
        organization_id=workflow.organization_id,
        sequence_number=1,
        source_module="autonomy",
        target_module="autonomy",
        action_type=INTERNAL_TEST_ACTION,
        risk_class="LOW",
        status="waiting",
        idempotency_key=f"{workflow.workflow_id}-internal-test-1",
        created_at=now(),
        updated_at=now(),
    )
    db.add(step)
    return step


def _ensure_approval(
    db: Session,
    *,
    workflow: NovaAutonomyWorkflow,
    user: UserContext,
    scope: str,
    step_id: str | None = None,
) -> NovaAutonomyApproval:
    query = db.query(NovaAutonomyApproval).filter(
        NovaAutonomyApproval.organization_id == workflow.organization_id,
        NovaAutonomyApproval.workflow_id == workflow.workflow_id,
        NovaAutonomyApproval.approval_scope == scope,
        NovaAutonomyApproval.status == "granted",
    )
    if step_id:
        query = query.filter(NovaAutonomyApproval.step_id == step_id)
    else:
        query = query.filter(NovaAutonomyApproval.step_id.is_(None))
    existing = query.first()
    if existing is not None:
        return existing
    approval = NovaAutonomyApproval(
        approval_id=new_approval_id(),
        workflow_id=workflow.workflow_id,
        step_id=step_id,
        organization_id=workflow.organization_id,
        approver_user_id=user.user_id,
        approval_scope=scope,
        status="granted",
        created_at=now(),
    )
    db.add(approval)
    return approval


def approve_workflow(
    db: Session,
    workflow_id: str,
    *,
    user: UserContext,
    requested_org: str | None = None,
    idempotency_key: str | None = None,
) -> AutonomyWorkflowOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    _require_not_stopped(db, organization_id)
    workflow = _load_workflow(db, workflow_id, organization_id)
    key = (idempotency_key or f"{workflow_id}:approve").strip()
    if workflow.status in {"waiting", "approved"}:
        return _workflow_out(db, workflow)
    if next_status(workflow.status, "approve") is None:
        raise Phase2BError("Illegal workflow transition", status_code=409)
    step = _ensure_internal_step(db, workflow)
    _ensure_approval(db, workflow=workflow, user=user, scope="workflow")
    workflow.status = "waiting"
    workflow.current_step = step.step_id
    workflow.updated_at = now()
    db.commit()
    db.refresh(workflow)
    _audit(
        db,
        user=user,
        workflow=workflow,
        action_type="approve_workflow",
        approval_state="approved",
        result="workflow_approved",
        detail="supervised_waiting",
        idempotency_key=key,
        step_id=step.step_id,
    )
    return _workflow_out(db, workflow)


def approve_step(
    db: Session,
    workflow_id: str,
    step_id: str,
    *,
    user: UserContext,
    requested_org: str | None = None,
    idempotency_key: str | None = None,
) -> AutonomyWorkflowOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    _require_not_stopped(db, organization_id)
    workflow = _load_workflow(db, workflow_id, organization_id)
    step = (
        db.query(NovaAutonomyWorkflowStep)
        .filter(
            NovaAutonomyWorkflowStep.organization_id == organization_id,
            NovaAutonomyWorkflowStep.workflow_id == workflow_id,
            NovaAutonomyWorkflowStep.step_id == step_id,
        )
        .first()
    )
    if step is None:
        raise Phase2BError("Workflow step not found", status_code=404)
    if step.status == "completed" and step.result_ref_id:
        return _workflow_out(db, workflow)
    if workflow.status not in STEP_APPROVE_FROM:
        raise Phase2BError("Illegal workflow transition", status_code=409)
    if step.action_type != INTERNAL_TEST_ACTION:
        raise Phase2BError("External step execution is not enabled", status_code=409)
    key = (idempotency_key or f"{workflow_id}:{step_id}:approve").strip()
    _ensure_approval(db, workflow=workflow, user=user, scope="step", step_id=step.step_id)
    attempt_number = (
        db.query(NovaAutonomyExecutionAttempt)
        .filter(
            NovaAutonomyExecutionAttempt.organization_id == organization_id,
            NovaAutonomyExecutionAttempt.workflow_id == workflow_id,
            NovaAutonomyExecutionAttempt.step_id == step_id,
        )
        .count()
        + 1
    )
    result_ref = "INT-" + uuid4().replace("-", "")[:12].upper()
    stamp = now()
    db.add(
        NovaAutonomyExecutionAttempt(
            attempt_id=new_attempt_id(),
            workflow_id=workflow_id,
            step_id=step_id,
            organization_id=organization_id,
            attempt_number=attempt_number,
            executed=True,
            result_ref_id=result_ref,
            verification_status="verified",
            created_at=stamp,
            completed_at=stamp,
        )
    )
    step.status = "completed"
    step.result_ref_id = result_ref
    step.executed_at = stamp
    step.verified_at = stamp
    step.updated_at = stamp
    workflow.status = "completed"
    workflow.current_step = step.step_id
    workflow.completed_at = stamp
    workflow.updated_at = stamp
    db.commit()
    db.refresh(workflow)
    _audit(
        db,
        user=user,
        workflow=workflow,
        action_type=INTERNAL_TEST_ACTION,
        approval_state="completed",
        result="internal_test_verified",
        detail="internal_test_only",
        executed=True,
        step_id=step.step_id,
        result_ref_id=result_ref,
        idempotency_key=key,
        attempt_number=attempt_number,
    )
    return _workflow_out(db, workflow)


def cancel_workflow(
    db: Session,
    workflow_id: str,
    *,
    user: UserContext,
    requested_org: str | None = None,
) -> AutonomyWorkflowOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    workflow = _load_workflow(db, workflow_id, organization_id)
    if workflow.status == "cancelled":
        return _workflow_out(db, workflow)
    if next_status(workflow.status, "cancel") is None:
        raise Phase2BError("Illegal workflow transition", status_code=409)
    stamp = now()
    workflow.status = "cancelled"
    workflow.cancelled_at = stamp
    workflow.updated_at = stamp
    db.commit()
    db.refresh(workflow)
    _audit(
        db,
        user=user,
        workflow=workflow,
        action_type="cancel_workflow",
        approval_state="cancelled",
        result="workflow_cancelled",
        detail="supervised_cancel",
        idempotency_key=f"{workflow_id}:cancel",
    )
    return _workflow_out(db, workflow)


def pause_workflow(
    db: Session,
    workflow_id: str,
    *,
    user: UserContext,
    requested_org: str | None = None,
) -> AutonomyWorkflowOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    _require_not_stopped(db, organization_id)
    workflow = _load_workflow(db, workflow_id, organization_id)
    if workflow.status == "paused":
        return _workflow_out(db, workflow)
    if next_status(workflow.status, "pause") is None:
        raise Phase2BError("Illegal workflow transition", status_code=409)
    workflow.status = "paused"
    workflow.updated_at = now()
    db.commit()
    db.refresh(workflow)
    _audit(
        db,
        user=user,
        workflow=workflow,
        action_type="pause_workflow",
        approval_state="paused",
        result="workflow_paused",
        detail="supervised_pause",
        idempotency_key=f"{workflow_id}:pause",
    )
    return _workflow_out(db, workflow)


def resume_workflow(
    db: Session,
    workflow_id: str,
    *,
    user: UserContext,
    requested_org: str | None = None,
) -> AutonomyWorkflowOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    _require_not_stopped(db, organization_id)
    workflow = _load_workflow(db, workflow_id, organization_id)
    if workflow.status in {"waiting", "approved"}:
        return _workflow_out(db, workflow)
    if next_status(workflow.status, "resume") is None:
        raise Phase2BError("Illegal workflow transition", status_code=409)
    workflow.status = "waiting"
    workflow.updated_at = now()
    db.commit()
    db.refresh(workflow)
    _audit(
        db,
        user=user,
        workflow=workflow,
        action_type="resume_workflow",
        approval_state="waiting",
        result="workflow_resumed",
        detail="supervised_resume",
        idempotency_key=f"{workflow_id}:resume",
    )
    return _workflow_out(db, workflow)


def retry_workflow(
    db: Session,
    workflow_id: str,
    *,
    user: UserContext,
    requested_org: str | None = None,
) -> AutonomyWorkflowOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    _require_not_stopped(db, organization_id)
    workflow = _load_workflow(db, workflow_id, organization_id)
    if next_status(workflow.status, "retry") is None:
        raise Phase2BError("Illegal workflow transition", status_code=409)
    workflow.status = "waiting"
    workflow.retry_count = int(workflow.retry_count or 0) + 1
    workflow.updated_at = now()
    db.commit()
    db.refresh(workflow)
    _audit(
        db,
        user=user,
        workflow=workflow,
        action_type="retry_workflow",
        approval_state="waiting",
        result="workflow_retry_waiting",
        detail="supervised_retry_no_execute",
        idempotency_key=f"{workflow_id}:retry:{workflow.retry_count}",
    )
    return _workflow_out(db, workflow)


def emergency_stop(
    db: Session, *, user: UserContext, requested_org: str | None = None
) -> dict:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    stamp = now()
    flag = _org_flag(db, organization_id)
    if flag is None:
        flag = NovaAutonomyOrgFlag(
            organization_id=organization_id,
            phase2_enabled=False,
            emergency_stop=True,
            disabled_at=stamp,
            disabled_by=user.user_id,
            updated_at=stamp,
        )
        db.add(flag)
    else:
        flag.emergency_stop = True
        flag.phase2_enabled = False
        flag.disabled_at = stamp
        flag.disabled_by = user.user_id
        flag.updated_at = stamp
    open_rows = (
        db.query(NovaAutonomyWorkflow)
        .filter(
            NovaAutonomyWorkflow.organization_id == organization_id,
            NovaAutonomyWorkflow.status.in_(tuple(OPEN_STATUSES)),
        )
        .all()
    )
    cancelled_ids = []
    for workflow in open_rows:
        workflow.status = "cancelled"
        workflow.cancelled_at = stamp
        workflow.updated_at = stamp
        cancelled_ids.append(workflow.workflow_id)
    db.commit()
    for workflow_id in cancelled_ids:
        workflow = _load_workflow(db, workflow_id, organization_id)
        _audit(
            db,
            user=user,
            workflow=workflow,
            action_type="emergency_stop",
            approval_state="cancelled",
            result="workflow_emergency_stopped",
            detail="org_emergency_stop",
            idempotency_key=f"{workflow_id}:emergency-stop",
        )
    return {
        "organization_id": organization_id,
        "phase2_enabled": False,
        "emergency_stop": True,
        "cancelled_workflow_ids": cancelled_ids,
        "executed": False,
        "mutated_external": False,
    }
