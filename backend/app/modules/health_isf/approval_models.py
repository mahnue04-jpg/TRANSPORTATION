"""Approval workflow request and state contracts for governed execution."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ApprovalProposalRequest(BaseModel):
    organization_id: str | None = None
    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence_score: float | None = None
    rollback_available: bool = True
    execution_expiration_minutes: int = 30
    tenant_scope: str | None = None


class ApprovalDecisionRequest(BaseModel):
    organization_id: str | None = None
    approval_id: str
    approved: bool = True
    approval_token: str | None = None
    approved_by: str | None = None
    tenant_scope: str | None = None


class GovernanceApprovalRequest(BaseModel):
    organization_id: str | None = None
    approval_id: str | None = None
    approval_token: str | None = None
    action_type: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence_score: float | None = None
    rollback_available: bool = True
    execution_expiration_minutes: int = 30
    tenant_scope: str | None = None
    approved: bool = False


class ApprovalContractRecord(BaseModel):
    id: str
    organization_id: str
    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    approval_required: bool = True
    approved_by: str | None = None
    approved_by_user_id: str | None = None
    approval_timestamp: datetime | None = None
    rollback_available: bool = True
    execution_expiration: datetime | None = None
    approval_token: str | None = None
    approval_token_hash: str | None = None
    status: str
    confidence_score: float | None = None
    tenant_scope: str
    created_at: datetime
    updated_at: datetime
