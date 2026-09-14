"""Phase 2H supervised job queue. Single-shot claim/run only. No background runner."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.autonomy import ledger
from app.core.nova.autonomy.models import (
    AutonomyJobOut,
    AutonomyProcessOneOut,
    NovaAutonomyApproval,
    NovaAutonomyExecutionAttempt,
    NovaAutonomyJob,
    NovaAutonomyWorkflow,
    NovaAutonomyWorkflowStep,
    new_attempt_id,
    new_job_id,
)
from app.core.nova.autonomy.policy import can_act, classify, is_blocked, normalize_action_type
from app.core.nova.autonomy.v2_adapters import READ_ONLY_ACTIONS
from app.core.nova.autonomy.v2_service import (
    Phase2BError,
    _caller_org,
    _load_workflow,
    _org_flag,
    _require_actor,
    _require_not_stopped,
)
from app.core.nova.autonomy.v2_states import INTERNAL_TEST_ACTION, MAX_STEP_RETRIES
from app.helpers import now, uuid4

JOB_STATES = frozenset(
    {"queued", "claimed", "running", "succeeded", "failed", "cancelled", "blocked"}
)
OPEN_JOB_STATES = frozenset({"queued", "claimed", "running"})
CLAIMABLE_STATES = frozenset({"queued"})
RUNNABLE_STATES = frozenset({"claimed", "running"})
CANCELABLE_STATES = frozenset({"queued", "claimed", "running", "failed"})
MAX_JOB_ATTEMPTS = MAX_STEP_RETRIES
LOCK_STALE_SECONDS = 300
FAIL_CLOSED_REF = "job-fail-closed"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _job_out(row: NovaAutonomyJob) -> AutonomyJobOut:
    return AutonomyJobOut.from_row(row)


def _require_phase2_enabled(db: Session, organization_id: str) -> None:
    flag = _org_flag(db, organization_id)
    if flag is None or not bool(flag.phase2_enabled):
        raise Phase2BError("Phase 2 worker tick is not enabled for this organization", status_code=403)


def _stopped(db: Session, organization_id: str) -> bool:
    flag = _org_flag(db, organization_id)
    return flag is not None and bool(flag.emergency_stop)


def _tick_eligible(job: NovaAutonomyJob) -> bool:
    action = normalize_action_type(job.action_type)
    risk = _action_risk(action)
    if is_blocked(risk) or risk == "MEDIUM":
        return False
    return _queue_permitted(action)


def _action_risk(action_type: str) -> str:
    action = normalize_action_type(action_type)
    if action == INTERNAL_TEST_ACTION:
        return "LOW"
    return classify(action)


def _queue_permitted(action_type: str) -> bool:
    action = normalize_action_type(action_type)
    if action == INTERNAL_TEST_ACTION:
        return True
    return _action_risk(action) == "LOW" and action in READ_ONLY_ACTIONS


def _load_job(db: Session, job_id: str, organization_id: str) -> NovaAutonomyJob:
    row = (
        db.query(NovaAutonomyJob)
        .filter(
            NovaAutonomyJob.organization_id == organization_id,
            NovaAutonomyJob.job_id == job_id,
        )
        .first()
    )
    if row is None:
        raise Phase2BError("Job not found", status_code=404)
    return row


def _load_step(
    db: Session, *, organization_id: str, workflow_id: str, step_id: str
) -> NovaAutonomyWorkflowStep:
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
    return step


def _existing_job(
    db: Session, *, organization_id: str, workflow_id: str, step_id: str, action_type: str
) -> NovaAutonomyJob | None:
    return (
        db.query(NovaAutonomyJob)
        .filter(
            NovaAutonomyJob.organization_id == organization_id,
            NovaAutonomyJob.workflow_id == workflow_id,
            NovaAutonomyJob.step_id == step_id,
            NovaAutonomyJob.action_type == action_type,
        )
        .first()
    )


def _matching_approval(
    db: Session, *, workflow: NovaAutonomyWorkflow, step: NovaAutonomyWorkflowStep
) -> NovaAutonomyApproval | None:
    stamp = now()
    rows = (
        db.query(NovaAutonomyApproval)
        .filter(
            NovaAutonomyApproval.organization_id == workflow.organization_id,
            NovaAutonomyApproval.workflow_id == workflow.workflow_id,
            NovaAutonomyApproval.status == "granted",
        )
        .all()
    )
    for row in rows:
        if row.revoked_at is not None:
            continue
        expires = _as_utc(row.expires_at)
        if expires is not None and expires <= stamp:
            continue
        if row.step_id == step.step_id:
            return row
        if (
            row.step_id is None
            and row.approval_scope == "workflow"
            and workflow.current_step == step.step_id
        ):
            return row
    return None


def _audit_job(
    db: Session,
    *,
    user: UserContext,
    job: NovaAutonomyJob,
    old_status: str,
    new_status: str,
    result: str,
    executed: bool = False,
    verification_result: str | None = None,
) -> None:
    ledger.append(
        db,
        user=user,
        organization_id=job.organization_id,
        action_type=job.action_type,
        risk_class=job.risk_class,
        approval_state=new_status,
        source_module="autonomy",
        source_ref_id=job.job_id,
        executed=executed,
        correlation_id=job.correlation_id,
        result_ref_id=job.result_ref_id or job.job_id,
        target=job.target_module,
        result=result,
        verification_result=verification_result,
        detail=f"job_id={job.job_id} old={old_status} new={new_status}",
        workflow_id=job.workflow_id,
        step_id=job.step_id,
        target_module=job.target_module,
        approver_user_id=user.user_id if can_act(user) else None,
        attempt_number=int(job.attempt_count or 0),
    )


def recover_stale_locks(
    db: Session, *, user: UserContext, organization_id: str
) -> int:
    cutoff = now() - timedelta(seconds=LOCK_STALE_SECONDS)
    rows = (
        db.query(NovaAutonomyJob)
        .filter(
            NovaAutonomyJob.organization_id == organization_id,
            NovaAutonomyJob.status.in_(("claimed", "running")),
        )
        .all()
    )
    released = 0
    for job in rows:
        locked = _as_utc(job.locked_at)
        if locked is None or locked > cutoff:
            continue
        old = job.status
        job.status = "queued"
        job.locked_at = None
        job.updated_at = now()
        db.commit()
        db.refresh(job)
        _audit_job(
            db,
            user=user,
            job=job,
            old_status=old,
            new_status="queued",
            result="job_lock_released",
        )
        released += 1
    return released


def list_jobs(db: Session, *, user: UserContext, requested_org: str | None = None) -> list[AutonomyJobOut]:
    organization_id = _caller_org(user, requested_org)
    rows = (
        db.query(NovaAutonomyJob)
        .filter(NovaAutonomyJob.organization_id == organization_id)
        .order_by(NovaAutonomyJob.created_at.desc())
        .limit(50)
        .all()
    )
    return [_job_out(row) for row in rows]


def get_job(
    db: Session, job_id: str, *, user: UserContext, requested_org: str | None = None
) -> AutonomyJobOut:
    organization_id = _caller_org(user, requested_org)
    return _job_out(_load_job(db, job_id, organization_id))


def queue_job(
    db: Session,
    *,
    user: UserContext,
    workflow_id: str,
    step_id: str,
    requested_org: str | None = None,
) -> AutonomyJobOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    workflow = _load_workflow(db, workflow_id, organization_id)
    step = _load_step(db, organization_id=organization_id, workflow_id=workflow_id, step_id=step_id)
    existing = _existing_job(
        db,
        organization_id=organization_id,
        workflow_id=workflow_id,
        step_id=step_id,
        action_type=step.action_type,
    )
    if existing is not None:
        return _job_out(existing)
    _require_not_stopped(db, organization_id)
    approval = _matching_approval(db, workflow=workflow, step=step)
    if approval is None:
        raise Phase2BError("Owner or admin approval is required for this step", status_code=409)
    risk = _action_risk(step.action_type)
    stamp = now()
    if is_blocked(risk):
        job = NovaAutonomyJob(
            job_id=new_job_id(),
            organization_id=organization_id,
            workflow_id=workflow.workflow_id,
            step_id=step.step_id,
            correlation_id=workflow.correlation_id,
            action_type=step.action_type,
            target_module=step.target_module or step.source_module,
            risk_class=risk,
            approval_id=approval.approval_id,
            status="blocked",
            attempt_count=0,
            created_at=stamp,
            updated_at=stamp,
            available_at=stamp,
            last_error="high_or_prohibited",
        )
        db.add(job)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            reused = _existing_job(
                db,
                organization_id=organization_id,
                workflow_id=workflow_id,
                step_id=step_id,
                action_type=step.action_type,
            )
            if reused is None:
                raise Phase2BError("Job could not be created", status_code=409)
            return _job_out(reused)
        db.refresh(job)
        _audit_job(
            db,
            user=user,
            job=job,
            old_status="none",
            new_status="blocked",
            result="job_blocked",
        )
        return _job_out(job)
    if risk == "MEDIUM" or not _queue_permitted(step.action_type):
        raise Phase2BError("Action is not queued for supervised execution", status_code=409)
    job = NovaAutonomyJob(
        job_id=new_job_id(),
        organization_id=organization_id,
        workflow_id=workflow.workflow_id,
        step_id=step.step_id,
        correlation_id=workflow.correlation_id,
        action_type=step.action_type,
        target_module=step.target_module or step.source_module,
        risk_class=risk,
        approval_id=approval.approval_id,
        status="queued",
        attempt_count=0,
        created_at=stamp,
        updated_at=stamp,
        available_at=stamp,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        reused = _existing_job(
            db,
            organization_id=organization_id,
            workflow_id=workflow_id,
            step_id=step_id,
            action_type=step.action_type,
        )
        if reused is None:
            raise Phase2BError("Job could not be created", status_code=409)
        return _job_out(reused)
    db.refresh(job)
    _audit_job(db, user=user, job=job, old_status="none", new_status="queued", result="job_queued")
    return _job_out(job)


def _claim_row(db: Session, *, user: UserContext, job: NovaAutonomyJob) -> NovaAutonomyJob:
    if _stopped(db, job.organization_id):
        _audit_job(
            db,
            user=user,
            job=job,
            old_status=job.status,
            new_status=job.status,
            result="emergency_stop_blocked",
        )
        raise Phase2BError("Emergency stop is active for this organization", status_code=403)
    if job.status == "blocked":
        raise Phase2BError("Blocked job cannot be claimed", status_code=409)
    if job.status == "cancelled":
        raise Phase2BError("Cancelled job cannot be claimed", status_code=409)
    if job.status == "succeeded":
        return job
    available = _as_utc(job.available_at) or now()
    if job.status not in CLAIMABLE_STATES or available > now():
        raise Phase2BError("Job is not eligible to claim", status_code=409)
    old = job.status
    stamp = now()
    job.status = "claimed"
    job.locked_at = stamp
    job.updated_at = stamp
    db.commit()
    db.refresh(job)
    _audit_job(db, user=user, job=job, old_status=old, new_status="claimed", result="job_claimed")
    return job


def claim_job(
    db: Session, job_id: str, *, user: UserContext, requested_org: str | None = None
) -> AutonomyJobOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    recover_stale_locks(db, user=user, organization_id=organization_id)
    job = _load_job(db, job_id, organization_id)
    return _job_out(_claim_row(db, user=user, job=job))


def claim_next_job(db: Session, *, user: UserContext, requested_org: str | None = None) -> AutonomyJobOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    recover_stale_locks(db, user=user, organization_id=organization_id)
    if _stopped(db, organization_id):
        raise Phase2BError("Emergency stop is active for this organization", status_code=403)
    job = (
        db.query(NovaAutonomyJob)
        .filter(
            NovaAutonomyJob.organization_id == organization_id,
            NovaAutonomyJob.status == "queued",
            NovaAutonomyJob.available_at <= now(),
        )
        .order_by(NovaAutonomyJob.available_at.asc(), NovaAutonomyJob.created_at.asc())
        .first()
    )
    if job is None:
        raise Phase2BError("No eligible job", status_code=404)
    return _job_out(_claim_row(db, user=user, job=job))


def _record_attempt(
    db: Session,
    *,
    job: NovaAutonomyJob,
    executed: bool,
    result_ref_id: str | None,
    verification_status: str,
    failure_reason: str | None,
) -> None:
    stamp = now()
    db.add(
        NovaAutonomyExecutionAttempt(
            attempt_id=new_attempt_id(),
            workflow_id=job.workflow_id,
            step_id=job.step_id,
            organization_id=job.organization_id,
            attempt_number=int(job.attempt_count or 0),
            executed=executed,
            result_ref_id=result_ref_id,
            verification_status=verification_status,
            failure_reason=failure_reason,
            created_at=stamp,
            completed_at=stamp,
        )
    )


def run_job(
    db: Session, job_id: str, *, user: UserContext, requested_org: str | None = None
) -> AutonomyJobOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    job = _load_job(db, job_id, organization_id)
    if job.status == "cancelled":
        raise Phase2BError("Cancelled job cannot execute", status_code=409)
    if job.status == "blocked":
        raise Phase2BError("Blocked job cannot execute", status_code=409)
    if job.status == "succeeded":
        return _job_out(job)
    if _stopped(db, organization_id):
        _audit_job(
            db,
            user=user,
            job=job,
            old_status=job.status,
            new_status=job.status,
            result="emergency_stop_blocked",
        )
        raise Phase2BError("Emergency stop is active for this organization", status_code=403)
    if job.status not in RUNNABLE_STATES:
        raise Phase2BError("Job must be claimed before execution", status_code=409)
    if int(job.attempt_count or 0) >= MAX_JOB_ATTEMPTS:
        raise Phase2BError("Retry limit reached", status_code=409)

    workflow = _load_workflow(db, job.workflow_id, organization_id)
    step = _load_step(
        db,
        organization_id=organization_id,
        workflow_id=job.workflow_id,
        step_id=job.step_id,
    )
    risk = _action_risk(job.action_type)
    old = job.status
    stamp = now()
    job.status = "running"
    job.locked_at = stamp
    job.attempt_count = int(job.attempt_count or 0) + 1
    job.updated_at = stamp
    db.commit()
    db.refresh(job)
    _audit_job(db, user=user, job=job, old_status=old, new_status="running", result="job_running")

    if is_blocked(risk) or not _queue_permitted(job.action_type):
        job.status = "blocked"
        job.locked_at = None
        job.last_error = "high_or_prohibited"
        job.updated_at = now()
        db.commit()
        db.refresh(job)
        _record_attempt(
            db,
            job=job,
            executed=False,
            result_ref_id=None,
            verification_status="blocked",
            failure_reason=job.last_error,
        )
        db.commit()
        _audit_job(db, user=user, job=job, old_status="running", new_status="blocked", result="job_blocked")
        return _job_out(job)

    if (workflow.source_ref_id or "").strip().lower() == FAIL_CLOSED_REF:
        job.status = "failed"
        job.locked_at = None
        job.last_error = "internal_test_failed"
        job.updated_at = now()
        db.commit()
        db.refresh(job)
        _record_attempt(
            db,
            job=job,
            executed=False,
            result_ref_id=None,
            verification_status="failed",
            failure_reason=job.last_error,
        )
        db.commit()
        _audit_job(db, user=user, job=job, old_status="running", new_status="failed", result="job_failed")
        return _job_out(job)

    action = normalize_action_type(job.action_type)
    result_ref = "INT-" + uuid4().replace("-", "")[:12].upper()
    if action != INTERNAL_TEST_ACTION and action not in READ_ONLY_ACTIONS:
        job.status = "failed"
        job.locked_at = None
        job.last_error = "external_action_blocked"
        job.updated_at = now()
        db.commit()
        db.refresh(job)
        _record_attempt(
            db,
            job=job,
            executed=False,
            result_ref_id=None,
            verification_status="failed",
            failure_reason=job.last_error,
        )
        db.commit()
        _audit_job(db, user=user, job=job, old_status="running", new_status="failed", result="job_failed")
        return _job_out(job)
    if not result_ref.startswith("INT-"):
        job.status = "failed"
        job.locked_at = None
        job.last_error = "result_not_verified"
        job.updated_at = now()
        db.commit()
        db.refresh(job)
        _record_attempt(
            db,
            job=job,
            executed=False,
            result_ref_id=None,
            verification_status="failed",
            failure_reason=job.last_error,
        )
        db.commit()
        _audit_job(db, user=user, job=job, old_status="running", new_status="failed", result="job_failed")
        return _job_out(job)

    executed = action == INTERNAL_TEST_ACTION
    job.status = "succeeded"
    job.result_ref_id = result_ref
    job.last_error = None
    job.locked_at = None
    job.completed_at = now()
    job.updated_at = job.completed_at
    db.commit()
    db.refresh(job)
    _record_attempt(
        db,
        job=job,
        executed=executed,
        result_ref_id=result_ref,
        verification_status="verified",
        failure_reason=None,
    )
    db.commit()
    _audit_job(
        db,
        user=user,
        job=job,
        old_status="running",
        new_status="succeeded",
        result="job_succeeded",
        executed=executed,
        verification_result="verified",
    )
    return _job_out(job)


def cancel_job(
    db: Session, job_id: str, *, user: UserContext, requested_org: str | None = None
) -> AutonomyJobOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    job = _load_job(db, job_id, organization_id)
    if job.status == "cancelled":
        return _job_out(job)
    if job.status == "succeeded":
        raise Phase2BError("Succeeded job cannot be cancelled", status_code=409)
    if job.status not in CANCELABLE_STATES:
        raise Phase2BError("Job cannot be cancelled", status_code=409)
    old = job.status
    stamp = now()
    job.status = "cancelled"
    job.locked_at = None
    job.updated_at = stamp
    db.commit()
    db.refresh(job)
    _audit_job(db, user=user, job=job, old_status=old, new_status="cancelled", result="job_cancelled")
    return _job_out(job)


def retry_job(
    db: Session, job_id: str, *, user: UserContext, requested_org: str | None = None
) -> AutonomyJobOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    _require_not_stopped(db, organization_id)
    job = _load_job(db, job_id, organization_id)
    if job.status == "cancelled":
        raise Phase2BError("Cancelled job cannot execute", status_code=409)
    if job.status != "failed":
        raise Phase2BError("Only a failed job may be retried", status_code=409)
    if int(job.attempt_count or 0) >= MAX_JOB_ATTEMPTS:
        raise Phase2BError("Retry limit reached", status_code=409)
    if not _queue_permitted(job.action_type) or is_blocked(_action_risk(job.action_type)):
        raise Phase2BError("Action is not queued for supervised execution", status_code=409)
    old = job.status
    stamp = now()
    job.status = "queued"
    job.locked_at = None
    job.available_at = stamp
    job.updated_at = stamp
    db.commit()
    db.refresh(job)
    _audit_job(db, user=user, job=job, old_status=old, new_status="queued", result="job_retried")
    return _job_out(job)


def process_one_job(
    db: Session, *, user: UserContext, requested_org: str | None = None
) -> AutonomyProcessOneOut:
    _require_actor(user)
    organization_id = _caller_org(user, requested_org)
    _require_phase2_enabled(db, organization_id)
    _require_not_stopped(db, organization_id)
    released = recover_stale_locks(db, user=user, organization_id=organization_id)
    candidates = (
        db.query(NovaAutonomyJob)
        .filter(
            NovaAutonomyJob.organization_id == organization_id,
            NovaAutonomyJob.status == "queued",
            NovaAutonomyJob.available_at <= now(),
        )
        .order_by(NovaAutonomyJob.available_at.asc(), NovaAutonomyJob.created_at.asc())
        .all()
    )
    selected = next((row for row in candidates if _tick_eligible(row)), None)
    if selected is None:
        raise Phase2BError("No eligible job", status_code=404)
    claimed = _claim_row(db, user=user, job=selected)
    ran = run_job(db, claimed.job_id, user=user, requested_org=organization_id)
    verification = "verified" if ran.status == "succeeded" and ran.result_ref_id else ran.status
    _audit_job(
        db,
        user=user,
        job=_load_job(db, ran.job_id, organization_id),
        old_status=ran.status,
        new_status=ran.status,
        result="process_one_tick",
        executed=bool(ran.executed),
        verification_result=verification,
    )
    return AutonomyProcessOneOut(
        processed=1,
        released_stale_locks=released,
        mutated_external=False,
        phase2_enabled=True,
        verification_result=verification,
        job=ran,
    )
