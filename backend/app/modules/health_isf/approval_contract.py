"""Append-only approval contract helpers for governed autonomous execution."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.approval_models import ApprovalContractRecord
from app.modules.health_isf.models import HealthISFGovernanceApproval


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_approval_proposal(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: str | None,
    action_type: str,
    parameters: dict[str, Any],
    confidence_score: float | None,
    rollback_available: bool,
    expiration_minutes: int,
    tenant_scope: str,
) -> ApprovalContractRecord:
    approval_token = secrets.token_urlsafe(24)
    created_at = now()
    record = HealthISFGovernanceApproval(
        id=str(uuid4()),
        organization_id=organization_id,
        submitted_by_user_id=actor_user_id,
        approved_by_user_id=None,
        action_type=action_type,
        action_payload_json=json.dumps(parameters, separators=(",", ":"), default=str),
        approval_token_hash=_hash_token(approval_token),
        approval_required=True,
        approval_timestamp=None,
        execution_expiration=created_at + timedelta(minutes=max(1, expiration_minutes)),
        rollback_available=rollback_available,
        status="proposed",
        confidence_score=confidence_score,
        tenant_scope=tenant_scope,
        role_scope_json=None,
        audit_event_id=None,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return ApprovalContractRecord(
        id=record.id,
        organization_id=record.organization_id,
        action_type=record.action_type,
        parameters=parameters,
        approval_required=record.approval_required,
        approved_by=None,
        approved_by_user_id=None,
        approval_timestamp=None,
        rollback_available=record.rollback_available,
        execution_expiration=record.execution_expiration,
        approval_token=approval_token,
        approval_token_hash=record.approval_token_hash,
        status=record.status,
        confidence_score=record.confidence_score,
        tenant_scope=record.tenant_scope,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def validate_approval_record(record: HealthISFGovernanceApproval, approval_token: str | None) -> None:
    if not approval_token:
        raise HTTPException(status_code=403, detail="Approval token required")
    if record.status != "approved":
        raise HTTPException(status_code=403, detail="Execution blocked without approval")
    if record.execution_expiration and now() > record.execution_expiration:
        raise HTTPException(status_code=403, detail="Approval token expired")
    if _hash_token(approval_token) != record.approval_token_hash:
        raise HTTPException(status_code=403, detail="Approval token invalid")


def approve_approval_record(
    db: Session,
    *,
    record: HealthISFGovernanceApproval,
    actor_user_id: str | None,
    approval_token: str,
) -> ApprovalContractRecord:
    if _hash_token(approval_token) != record.approval_token_hash:
        raise HTTPException(status_code=403, detail="Approval token invalid")
    timestamp = now()
    record.approved_by_user_id = actor_user_id
    record.approval_timestamp = timestamp
    record.status = "approved"
    record.updated_at = timestamp
    db.commit()
    db.refresh(record)
    return ApprovalContractRecord(
        id=record.id,
        organization_id=record.organization_id,
        action_type=record.action_type,
        parameters=json.loads(record.action_payload_json or "{}") if str(record.action_payload_json or "").strip().startswith("{") else {"raw": record.action_payload_json},
        approval_required=record.approval_required,
        approved_by=record.approved_by_user_id,
        approved_by_user_id=record.approved_by_user_id,
        approval_timestamp=record.approval_timestamp,
        rollback_available=record.rollback_available,
        execution_expiration=record.execution_expiration,
        approval_token=None,
        approval_token_hash=record.approval_token_hash,
        status=record.status,
        confidence_score=record.confidence_score,
        tenant_scope=record.tenant_scope,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
