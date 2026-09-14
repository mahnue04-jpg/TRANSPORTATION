"""Autonomy Phase 1 ledger plus Phase 2A schema models. No secrets or message bodies."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


def new_workflow_id() -> str:
    return "NWF-" + uuid4().replace("-", "")[:12].upper()


def new_step_id() -> str:
    return "NWS-" + uuid4().replace("-", "")[:12].upper()


def new_approval_id() -> str:
    return "NWA-" + uuid4().replace("-", "")[:12].upper()


def new_attempt_id() -> str:
    return "NWT-" + uuid4().replace("-", "")[:12].upper()


def new_job_id() -> str:
    return "NWJ-" + uuid4().replace("-", "")[:12].upper()


class NovaAutonomyLedger(Base):
    """Append-only autonomy audit row. Never stores secrets, tokens, or message bodies."""

    __tablename__ = "nova_autonomy_ledger"
    __table_args__ = (
        Index("ix_nova_autonomy_audit_id", "audit_id"),
        Index("ix_nova_autonomy_correlation", "organization_id", "correlation_id"),
        Index("ix_nova_autonomy_idempotency", "organization_id", "idempotency_key"),
        Index("ix_nova_autonomy_org_created", "organization_id", "created_at"),
        Index("ix_nova_autonomy_ledger_workflow", "organization_id", "workflow_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    audit_id: Mapped[str] = mapped_column(String(40), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_module: Mapped[str] = mapped_column(String(40), nullable=False, default="autonomy")
    source_ref_id: Mapped[str] = mapped_column(String(80), nullable=False)
    result_ref_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target: Mapped[str | None] = mapped_column(String(240), nullable=True)
    risk_class: Mapped[str] = mapped_column(String(16), nullable=False)
    approval_state: Mapped[str] = mapped_column(String(32), nullable=False)
    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    today_action_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result: Mapped[str] = mapped_column(String(240), nullable=False, default="recorded")
    verification_result: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    step_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_module: Mapped[str | None] = mapped_column(String(40), nullable=True)
    approver_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)


class NovaAutonomyWorkflow(Base):
    """Phase 2A workflow header. No execution. Restrict deletes so audit history stays."""

    __tablename__ = "nova_autonomy_workflows"
    __table_args__ = (
        Index("ix_nova_autonomy_wf_org_status", "organization_id", "status"),
        Index("ix_nova_autonomy_wf_org_correlation", "organization_id", "correlation_id"),
        Index("ix_nova_autonomy_wf_org_owner", "organization_id", "owner_user_id"),
    )

    workflow_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_workflow_id)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(80), nullable=False)
    workflow_type: Mapped[str] = mapped_column(String(64), nullable=False)
    initiating_module: Mapped[str] = mapped_column(String(40), nullable=False)
    source_ref_id: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    current_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NovaAutonomyWorkflowStep(Base):
    """Phase 2A ordered step. Idempotency is unique per organization."""

    __tablename__ = "nova_autonomy_workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence_number", name="uq_nova_autonomy_step_order"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_nova_autonomy_step_idemp"),
        Index("ix_nova_autonomy_step_org_workflow", "organization_id", "workflow_id"),
        Index("ix_nova_autonomy_step_org_status", "organization_id", "status"),
    )

    step_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_step_id)
    workflow_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("nova_autonomy_workflows.workflow_id", ondelete="RESTRICT"),
        nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_module: Mapped[str] = mapped_column(String(40), nullable=False)
    target_module: Mapped[str] = mapped_column(String(40), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_class: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    result_ref_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NovaAutonomyApproval(Base):
    """Phase 2A tenant-scoped approval grant. Expiry and revoke are stored only."""

    __tablename__ = "nova_autonomy_approvals"
    __table_args__ = (
        Index("ix_nova_autonomy_appr_org_workflow", "organization_id", "workflow_id"),
        Index("ix_nova_autonomy_appr_org_status", "organization_id", "status"),
    )

    approval_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_approval_id)
    workflow_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("nova_autonomy_workflows.workflow_id", ondelete="RESTRICT"),
        nullable=False,
    )
    step_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("nova_autonomy_workflow_steps.step_id", ondelete="RESTRICT"),
        nullable=True,
    )
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approver_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approval_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="granted")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaAutonomyExecutionAttempt(Base):
    """Append-only execution attempt history. No update helper is provided."""

    __tablename__ = "nova_autonomy_execution_attempts"
    __table_args__ = (
        UniqueConstraint("workflow_id", "step_id", "attempt_number", name="uq_nova_autonomy_attempt_seq"),
        Index("ix_nova_autonomy_attempt_org_workflow", "organization_id", "workflow_id"),
    )

    attempt_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_attempt_id)
    workflow_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("nova_autonomy_workflows.workflow_id", ondelete="RESTRICT"),
        nullable=False,
    )
    step_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("nova_autonomy_workflow_steps.step_id", ondelete="RESTRICT"),
        nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result_ref_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NovaAutonomyOrgFlag(Base):
    """Per-organization Phase 2 switches. Defaults remain OFF."""

    __tablename__ = "nova_autonomy_org_flags"

    organization_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phase2_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaAutonomyJob(Base):
    """Phase 2H supervised queue row. No background runner claims these automatically."""

    __tablename__ = "nova_autonomy_jobs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "workflow_id",
            "step_id",
            "action_type",
            name="uq_nova_autonomy_job_idemp",
        ),
        Index("ix_nova_autonomy_job_org_status", "organization_id", "status"),
        Index("ix_nova_autonomy_job_org_workflow", "organization_id", "workflow_id"),
        Index("ix_nova_autonomy_job_org_available", "organization_id", "available_at"),
    )

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_job_id)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workflow_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("nova_autonomy_workflows.workflow_id", ondelete="RESTRICT"),
        nullable=False,
    )
    step_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("nova_autonomy_workflow_steps.step_id", ondelete="RESTRICT"),
        nullable=False,
    )
    correlation_id: Mapped[str] = mapped_column(String(80), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_module: Mapped[str] = mapped_column(String(40), nullable=False)
    risk_class: Mapped[str] = mapped_column(String(16), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    result_ref_id: Mapped[str | None] = mapped_column(String(80), nullable=True)


class AutonomyIntentCreate(BaseModel):
    action_type: str = Field(min_length=2, max_length=64)
    source_module: Literal["workspace", "communications", "government", "business", "link", "autonomy"] = "autonomy"
    source_ref_id: str = Field(min_length=1, max_length=80)
    title: str = Field(default="Autonomy intent", max_length=240)
    organization_id: str | None = None
    correlation_id: str | None = Field(default=None, max_length=80)
    today_action_id: str | None = Field(default=None, max_length=32)
    hours: int | None = None
    draft_to: list[str] = Field(default_factory=list)
    draft_subject: str | None = Field(default=None, max_length=512)
    task_title: str | None = Field(default=None, max_length=220)
    confidence: float | None = None
    recommendation_strength: float | None = None


class AutonomyApproveRequest(BaseModel):
    organization_id: str | None = None
    hours: int | None = None
    draft_to: list[str] = Field(default_factory=list)
    draft_subject: str | None = Field(default=None, max_length=512)
    task_title: str | None = Field(default=None, max_length=220)


class AutonomyIntentOut(BaseModel):
    audit_id: str
    correlation_id: str
    action_type: str
    source_module: str
    source_ref_id: str
    target: str | None = None
    result_ref_id: str | None = None
    today_action_id: str | None = None
    risk_class: str
    approval_state: str
    executed: bool
    actor_user_id: str
    actor_role: str
    organization_id: str
    timestamp: datetime
    result: str
    verification_result: str | None = None
    href: str | None = None
    mutated_external: bool = False

    @classmethod
    def from_row(cls, row: NovaAutonomyLedger, **extra: Any) -> "AutonomyIntentOut":
        return cls(
            audit_id=row.audit_id,
            correlation_id=row.correlation_id,
            action_type=row.action_type,
            source_module=row.source_module,
            source_ref_id=row.source_ref_id,
            target=row.target,
            result_ref_id=row.result_ref_id,
            today_action_id=row.today_action_id,
            risk_class=row.risk_class,
            approval_state=row.approval_state,
            executed=bool(row.executed),
            actor_user_id=row.actor_user_id,
            actor_role=row.actor_role,
            organization_id=row.organization_id,
            timestamp=row.created_at,
            result=row.result,
            verification_result=row.verification_result,
            href=extra.get("href"),
            mutated_external=bool(extra.get("mutated_external", False)),
        )


class AutonomyWorkflowCreate(BaseModel):
    """Phase 2B header-only create. organization_id is never trusted from the client."""

    workflow_type: str = Field(min_length=2, max_length=64)
    initiating_module: str = Field(min_length=2, max_length=40)
    source_ref_id: str = Field(min_length=1, max_length=80)
    action_type: str | None = Field(default=None, max_length=64)
    organization_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)
    step_count: int | None = Field(default=None, ge=1, le=3)


class AutonomyWorkflowApproveRequest(BaseModel):
    organization_id: str | None = None
    step_count: int | None = Field(default=None, ge=1, le=3)


class AutonomyWorkflowStepOut(BaseModel):
    step_id: str
    workflow_id: str
    organization_id: str
    sequence_number: int
    source_module: str
    target_module: str
    action_type: str
    risk_class: str
    status: str
    result_ref_id: str | None = None
    executed_at: datetime | None = None


class AutonomyApprovalOut(BaseModel):
    approval_id: str
    workflow_id: str
    step_id: str | None = None
    organization_id: str
    approver_user_id: str
    approval_scope: str
    status: str
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime


class AutonomyOrgFlagOut(BaseModel):
    organization_id: str
    phase2_enabled: bool = False
    emergency_stop: bool = False
    disabled_at: datetime | None = None
    disabled_by: str | None = None


class AutonomyJobQueueRequest(BaseModel):
    workflow_id: str = Field(min_length=3, max_length=32)
    step_id: str = Field(min_length=3, max_length=32)
    organization_id: str | None = None


class AutonomyJobOut(BaseModel):
    job_id: str
    organization_id: str
    workflow_id: str
    step_id: str
    correlation_id: str
    action_type: str
    target_module: str
    risk_class: str
    approval_id: str | None = None
    status: str
    attempt_count: int = 0
    created_at: datetime
    updated_at: datetime
    available_at: datetime
    locked_at: datetime | None = None
    completed_at: datetime | None = None
    last_error: str | None = None
    result_ref_id: str | None = None
    executed: bool = False
    mutated_external: bool = False

    @classmethod
    def from_row(cls, row: "NovaAutonomyJob") -> "AutonomyJobOut":
        return cls(
            job_id=row.job_id,
            organization_id=row.organization_id,
            workflow_id=row.workflow_id,
            step_id=row.step_id,
            correlation_id=row.correlation_id,
            action_type=row.action_type,
            target_module=row.target_module,
            risk_class=row.risk_class,
            approval_id=row.approval_id,
            status=row.status,
            attempt_count=int(row.attempt_count or 0),
            created_at=row.created_at,
            updated_at=row.updated_at,
            available_at=row.available_at,
            locked_at=row.locked_at,
            completed_at=row.completed_at,
            last_error=row.last_error,
            result_ref_id=row.result_ref_id,
            executed=bool(row.status == "succeeded" and row.result_ref_id),
            mutated_external=False,
        )


class AutonomyProcessOneOut(BaseModel):
    processed: int = 0
    released_stale_locks: int = 0
    mutated_external: bool = False
    phase2_enabled: bool = False
    verification_result: str | None = None
    job: AutonomyJobOut | None = None


class AutonomyBatchJobResult(BaseModel):
    job_id: str
    status: str
    verification_result: str | None = None
    mutated_external: bool = False


class AutonomyProcessBatchOut(BaseModel):
    requested_max_jobs: int = 1
    processed_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    stopped_reason: str = "no_eligible_jobs"
    processed_job_ids: list[str] = Field(default_factory=list)
    jobs: list[AutonomyBatchJobResult] = Field(default_factory=list)
    mutated_external: bool = False
    phase2_enabled: bool = False
    released_stale_locks: int = 0


class AutonomyWorkflowOut(BaseModel):
    workflow_id: str
    organization_id: str
    owner_user_id: str
    correlation_id: str
    workflow_type: str
    initiating_module: str
    source_ref_id: str
    status: str
    current_step: str | None = None
    retry_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    executed: bool = False
    mutated_external: bool = False
    steps: list[AutonomyWorkflowStepOut] = Field(default_factory=list)
    approvals: list[AutonomyApprovalOut] = Field(default_factory=list)

    @classmethod
    def from_row(
        cls,
        row: NovaAutonomyWorkflow,
        *,
        steps: list[NovaAutonomyWorkflowStep] | None = None,
        approvals: list[NovaAutonomyApproval] | None = None,
    ) -> "AutonomyWorkflowOut":
        return cls(
            workflow_id=row.workflow_id,
            organization_id=row.organization_id,
            owner_user_id=row.owner_user_id,
            correlation_id=row.correlation_id,
            workflow_type=row.workflow_type,
            initiating_module=row.initiating_module,
            source_ref_id=row.source_ref_id,
            status=row.status,
            current_step=row.current_step,
            retry_count=int(row.retry_count or 0),
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at,
            cancelled_at=row.cancelled_at,
            executed=any(
                step.action_type == "internal_test" and step.executed_at is not None
                for step in (steps or [])
            ),
            mutated_external=False,
            steps=[
                AutonomyWorkflowStepOut(
                    step_id=step.step_id,
                    workflow_id=step.workflow_id,
                    organization_id=step.organization_id,
                    sequence_number=step.sequence_number,
                    source_module=step.source_module,
                    target_module=step.target_module,
                    action_type=step.action_type,
                    risk_class=step.risk_class,
                    status=step.status,
                    result_ref_id=step.result_ref_id,
                    executed_at=step.executed_at,
                )
                for step in (steps or [])
            ],
            approvals=[
                AutonomyApprovalOut(
                    approval_id=item.approval_id,
                    workflow_id=item.workflow_id,
                    step_id=item.step_id,
                    organization_id=item.organization_id,
                    approver_user_id=item.approver_user_id,
                    approval_scope=item.approval_scope,
                    status=item.status,
                    expires_at=item.expires_at,
                    revoked_at=item.revoked_at,
                    created_at=item.created_at,
                )
                for item in (approvals or [])
            ],
        )
