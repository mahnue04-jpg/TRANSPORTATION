"""Structured action model for approval-safe Nova execution orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """Categories of Nova operational actions."""
    DISPATCH_ESCALATION = "dispatch_escalation"
    PROVIDER_INCENTIVE_PUSH = "provider_incentive_push"
    RUNTIME_RECONNECT_RECOVERY = "runtime_reconnect_recovery"
    STAFFING_ALERT_ESCALATION = "staffing_alert_escalation"
    DEPLOYMENT_WARNING_ESCALATION = "deployment_warning_escalation"
    RECOMMENDATION_ACKNOWLEDGEMENT = "recommendation_acknowledgement"
    CONTINUITY_RECOVERY_ACTION = "continuity_recovery_action"
    OPERATIONAL_DECISION = "operational_decision"
    INCIDENT_MITIGATION = "incident_mitigation"
    WORKFLOW_REBALANCE = "workflow_rebalance"


class ActionCategory(str, Enum):
    """Execution categories."""
    OPERATIONAL = "operational"
    DEPLOYMENT = "deployment"
    RECOVERY = "recovery"
    WORKFLOW = "workflow"
    GOVERNANCE = "governance"


class ExecutionStatus(str, Enum):
    """Execution lifecycle states - all decisions remain human-controlled."""
    PROPOSED = "proposed"               # AI has identified, analyzed, and staged
    AWAITING_APPROVAL = "awaiting_approval"  # Ready for human approval
    APPROVED = "approved"               # Human approved, queued for execution
    EXECUTING = "executing"             # Currently executing
    COMPLETED = "completed"             # Execution completed successfully
    FAILED = "failed"                   # Execution failed
    ROLLED_BACK = "rolled_back"         # Rollback completed
    REJECTED = "rejected"               # Human rejected the action
    EXPIRED = "expired"                 # Action expiration timeout reached


class NovaAction(BaseModel):
    """Core Nova action structure with approval-safe lifecycle."""
    
    # Identity
    action_id: str = Field(..., description="Unique action identifier")
    correlation_id: str = Field(..., description="Links to source event/reasoning chain")
    
    # Classification
    action_type: ActionType = Field(..., description="Type of action")
    category: ActionCategory = Field(..., description="Operational category")
    source_event_ids: list[str] = Field(default_factory=list, description="Source events triggering this action")
    
    # Description
    title: str = Field(..., description="Human-readable action title")
    reason: str = Field(..., description="Why this action is proposed")
    impact: str = Field(..., description="Expected operational impact")
    
    # Scoring
    urgency: float = Field(ge=0.0, le=1.0, description="Urgency score (0-1)")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score (0-1)")
    
    # Execution Details
    suggested_execution: dict[str, Any] = Field(default_factory=dict, description="Proposed execution parameters")
    rollback_strategy: str = Field(..., description="How to rollback if execution fails")
    
    # Policy
    approval_required: bool = Field(default=True, description="Human approval mandatory")
    execution_timeout_seconds: int = Field(default=300, description="Max execution time")
    
    # Lifecycle
    execution_status: ExecutionStatus = Field(default=ExecutionStatus.PROPOSED, description="Current execution state")
    execution_timeline: dict[str, Any] = Field(default_factory=dict, description="Execution step timeline")
    
    # Temporal
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="When action was proposed")
    executed_at: datetime | None = Field(default=None, description="When execution started")
    completed_at: datetime | None = Field(default=None, description="When execution completed")
    expires_at: datetime | None = Field(default=None, description="Action expiration time")
    
    # Approval tracking
    approval_metadata: dict[str, Any] = Field(default_factory=dict, description="Approval decision details")
    operator_identity: str | None = Field(default=None, description="Who approved/rejected")
    approval_timestamp: datetime | None = Field(default=None, description="When approved/rejected")
    rejection_reason: str | None = Field(default=None, description="Why action was rejected")
    
    # Execution evidence
    execution_evidence: dict[str, Any] = Field(default_factory=dict, description="Execution results and diagnostics")
    recovery_attempts: list[dict[str, Any]] = Field(default_factory=list, description="Recovery step history")
    
    # Organization scope
    organization_id: str | None = Field(default=None, description="Tenant scope")
    
    class Config:
        use_enum_values = False


class ProposedAction(BaseModel):
    """Lightweight action proposal for initial staging."""
    action_type: ActionType
    category: ActionCategory
    title: str
    reason: str
    impact: str
    urgency: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_execution: dict[str, Any] = Field(default_factory=dict)
    rollback_strategy: str
    source_event_ids: list[str] = Field(default_factory=list)
    approval_required: bool = True
    execution_timeout_seconds: int = 300


class ApprovalRequest(BaseModel):
    """Operator approval for staged action."""
    action_id: str
    approved: bool
    approval_reason: str | None = None
    rejection_reason: str | None = None
    approval_metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """Execution result with evidence."""
    action_id: str
    status: ExecutionStatus
    evidence: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    recovery_attempted: bool = False
    recovery_successful: bool | None = None


class ActionTimeline(BaseModel):
    """Action execution timeline entry."""
    timestamp: datetime
    event_type: str  # proposed, approved, executing, completed, failed, rolled_back, etc.
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionQueryResponse(BaseModel):
    """Query response for pending/executing actions."""
    organization_id: str
    total_count: int
    by_status: dict[str, int] = Field(default_factory=dict)
    pending_actions: list[NovaAction] = Field(default_factory=list)
    executing_actions: list[NovaAction] = Field(default_factory=list)
    failed_actions: list[NovaAction] = Field(default_factory=list)
    recent_rollbacks: list[NovaAction] = Field(default_factory=list)
    average_execution_latency_ms: float = 0.0
