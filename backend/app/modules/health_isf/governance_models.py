"""Pydantic contracts for enterprise AI governance outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GovernanceAuditRecord(BaseModel):
    id: str
    organization_id: str
    event_type: str
    actor_user_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class GovernanceStatusResponse(BaseModel):
    organization_id: str
    confidence_threshold: float
    approval_required: bool
    rollback_required: bool
    tenant_scoped: bool
    append_only_audit: bool
    audit_count: int
    approval_count: int
    reasoning_count: int
    prediction_count: int
    execution_count: int
    websocket_health: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)


class GovernanceApprovalResponse(BaseModel):
    id: str
    organization_id: str
    action_type: str
    action_payload: dict[str, Any] = Field(default_factory=dict)
    approval_required: bool
    approved_by: str | None = None
    approved_by_user_id: str | None = None
    approval_timestamp: datetime | None = None
    approval_token: str | None = None
    approval_token_hash: str | None = None
    rollback_available: bool
    execution_expiration: datetime | None = None
    status: str
    confidence_score: float | None = None
    tenant_scope: str
    created_at: datetime
    updated_at: datetime


class GovernanceTimelineItem(BaseModel):
    event_id: str
    event_type: str
    organization_id: str
    tenant_scope: str
    timestamp: datetime
    confidence: float | None = None
    related_incidents: list[dict[str, Any]] = Field(default_factory=list)
    related_predictions: list[dict[str, Any]] = Field(default_factory=list)
    related_executions: list[dict[str, Any]] = Field(default_factory=list)
    rollback_references: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class GovernanceCorrelationItem(BaseModel):
    correlation_id: str
    organization_id: str
    tenant_scope: str
    confidence: float
    summary: str
    incidents: list[dict[str, Any]] = Field(default_factory=list)
    predictions: list[dict[str, Any]] = Field(default_factory=list)
    memory: list[dict[str, Any]] = Field(default_factory=list)
    realtime: dict[str, Any] = Field(default_factory=dict)
    executions: list[dict[str, Any]] = Field(default_factory=list)
    rollback_references: list[str] = Field(default_factory=list)


class GovernanceValidationItem(BaseModel):
    name: str
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)
