"""Central AI governance engine for tenant-scoped, explainable control."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.helpers import now, uuid4
from app.modules.health_isf.approval_contract import approve_approval_record, create_approval_proposal, validate_approval_record
from app.modules.health_isf.approval_models import ApprovalContractRecord
from app.modules.health_isf.enterprise_feature_flags import is_feature_enabled
from app.modules.health_isf.governance_registry import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    GOVERNANCE_APPROVAL_EVENT,
    GOVERNANCE_CORRELATION_EVENT,
    GOVERNANCE_EXECUTION_EVENT,
    GOVERNANCE_PREDICTION_EVENT,
    GOVERNANCE_PROPOSAL_EVENT,
    GOVERNANCE_REASONING_EVENT,
    GOVERNANCE_TIMELINE_EVENT,
    GOVERNANCE_POLICY,
    APPROVAL_ROLES,
    EXECUTION_ROLES,
    REVIEW_ROLES,
)
from app.modules.health_isf.models import HealthISFGovernanceApproval, HealthISFWorkflowAuditLog
from app.modules.health_isf.memory_service import OperationalMemoryService
from app.modules.health_isf.operations import build_operational_metrics
from app.modules.health_isf.realtime import get_broadcaster
from app.modules.health_isf.security import enforce_tenant_scope


class AIGovernanceEngine:
    @staticmethod
    def _stable_hash(payload: dict[str, Any]) -> str:
        material = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @classmethod
    def _audit_payload(cls, event_type: str, payload: dict[str, Any]) -> str:
        return json.dumps(
            {
                "event_type": event_type,
                "payload": payload,
                "recorded_at": now().isoformat(),
                "replay_safe_key": cls._stable_hash({"event_type": event_type, **payload}),
                "append_only": True,
            },
            separators=(",", ":"),
            default=str,
        )

    @classmethod
    def create_governance_audit(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> HealthISFWorkflowAuditLog:
        row = HealthISFWorkflowAuditLog(
            id=str(uuid4()),
            organization_id=organization_id,
            workflow_execution_id=None,
            incident_id=None,
            escalation_id=None,
            event_type=event_type,
            actor_user_id=actor_user_id,
            payload=cls._audit_payload(event_type, payload),
            created_at=now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @classmethod
    def enforce_confidence_threshold(cls, confidence: float | None, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> bool:
        value = float(confidence or 0.0)
        return value >= float(threshold)

    @classmethod
    def validate_tenant_scope(cls, user: UserContext, organization_id: str | None) -> str:
        return enforce_tenant_scope(user, organization_id)

    @classmethod
    def validate_role_scope(cls, user: UserContext, allowed_roles: set[str] | frozenset[str] | None = None) -> None:
        roles = set(allowed_roles or REVIEW_ROLES)
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Role not permitted for governance operation")

    @classmethod
    def register_reasoning_event(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        reasoning: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "reasoning": reasoning,
            "tenant_scope": organization_id,
            "confidence": reasoning.get("confidence"),
            "rollback_available": bool(reasoning.get("rollback_impact")),
        }
        cls.create_governance_audit(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=GOVERNANCE_REASONING_EVENT,
            payload=payload,
        )
        OperationalMemoryService.record_operation(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            operation={"operation_type": "governance_reasoning_registered", "payload": payload},
            replay_hint=cls._stable_hash(payload),
        )
        return payload

    @classmethod
    def register_prediction_event(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        prediction: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "prediction": prediction,
            "tenant_scope": organization_id,
            "confidence": prediction.get("confidence"),
            "rollback_available": True,
        }
        cls.create_governance_audit(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=GOVERNANCE_PREDICTION_EVENT,
            payload=payload,
        )
        OperationalMemoryService.record_prediction(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            prediction={"prediction_type": "governance_prediction_registered", **payload},
            replay_hint=cls._stable_hash(payload),
        )
        return payload

    @classmethod
    def validate_execution_policy(
        cls,
        db: Session,
        *,
        user: UserContext,
        organization_id: str,
        action_type: str,
        confidence_score: float | None,
        approval_token: str | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        effective_org_id = cls.validate_tenant_scope(user, organization_id)
        cls.validate_role_scope(user, EXECUTION_ROLES)
        approval: HealthISFGovernanceApproval | None = None
        if approval_id:
            approval = (
                db.query(HealthISFGovernanceApproval)
                .filter(HealthISFGovernanceApproval.id == approval_id)
                .filter(HealthISFGovernanceApproval.organization_id == effective_org_id)
                .first()
            )
        if approval is None:
            approval = (
                db.query(HealthISFGovernanceApproval)
                .filter(HealthISFGovernanceApproval.organization_id == effective_org_id)
                .filter(HealthISFGovernanceApproval.action_type == action_type)
                .order_by(HealthISFGovernanceApproval.created_at.desc())
                .first()
            )
        if approval is None:
            raise HTTPException(status_code=403, detail="Execution blocked without approval")
        validate_approval_record(approval, approval_token)
        if not cls.enforce_confidence_threshold(confidence_score):
            raise HTTPException(status_code=403, detail="Confidence threshold not met")

        audit = cls.create_governance_audit(
            db,
            organization_id=effective_org_id,
            actor_user_id=user.user_id,
            event_type=GOVERNANCE_EXECUTION_EVENT,
            payload={
                "action_type": action_type,
                "approval_id": approval.id,
                "confidence_score": confidence_score,
                "tenant_scope": effective_org_id,
                "rollback_available": approval.rollback_available,
            },
        )
        return {
            "organization_id": effective_org_id,
            "action_type": action_type,
            "approval_id": approval.id,
            "approval_required": True,
            "approved_by": approval.approved_by_user_id,
            "approval_timestamp": approval.approval_timestamp.isoformat() if approval.approval_timestamp else None,
            "rollback_available": approval.rollback_available,
            "execution_expiration": approval.execution_expiration.isoformat() if approval.execution_expiration else None,
            "confidence_threshold": GOVERNANCE_POLICY.confidence_threshold,
            "confidence_score": confidence_score,
            "audit_event_id": audit.id,
            "tenant_scope": effective_org_id,
        }

    @classmethod
    def create_approval_proposal(
        cls,
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
        contract = create_approval_proposal(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action_type=action_type,
            parameters=parameters,
            confidence_score=confidence_score,
            rollback_available=rollback_available,
            expiration_minutes=expiration_minutes,
            tenant_scope=tenant_scope,
        )
        cls.create_governance_audit(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=GOVERNANCE_PROPOSAL_EVENT,
            payload={
                "approval_id": contract.id,
                "action_type": action_type,
                "confidence_score": confidence_score,
                "rollback_available": rollback_available,
                "execution_expiration": contract.execution_expiration.isoformat() if contract.execution_expiration else None,
                "tenant_scope": tenant_scope,
            },
        )
        return contract

    @classmethod
    def approve_approval(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        approval_id: str,
        approval_token: str,
    ) -> ApprovalContractRecord:
        record = (
            db.query(HealthISFGovernanceApproval)
            .filter(HealthISFGovernanceApproval.id == approval_id)
            .filter(HealthISFGovernanceApproval.organization_id == organization_id)
            .first()
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Approval proposal not found")
        approved = approve_approval_record(db, record=record, actor_user_id=actor_user_id, approval_token=approval_token)
        cls.create_governance_audit(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=GOVERNANCE_APPROVAL_EVENT,
            payload={
                "approval_id": approved.id,
                "action_type": approved.action_type,
                "approved_by": approved.approved_by_user_id,
                "tenant_scope": approved.tenant_scope,
                "rollback_available": approved.rollback_available,
            },
        )
        return approved

    @classmethod
    def audit_snapshot(
        cls,
        db: Session,
        *,
        organization_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(HealthISFWorkflowAuditLog.organization_id == organization_id)
            .filter(HealthISFWorkflowAuditLog.event_type.like("ai.governance.%"))
            .order_by(HealthISFWorkflowAuditLog.created_at.desc())
            .limit(limit)
            .all()
        )
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row.payload or "{}")
            except Exception:
                payload = {"raw": row.payload}
            events.append(
                {
                    "id": row.id,
                    "organization_id": row.organization_id,
                    "event_type": row.event_type,
                    "actor_user_id": row.actor_user_id,
                    "payload": payload,
                    "created_at": row.created_at.isoformat(),
                }
            )
        return events

    @classmethod
    def approval_snapshot(
        cls,
        db: Session,
        *,
        organization_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = (
            db.query(HealthISFGovernanceApproval)
            .filter(HealthISFGovernanceApproval.organization_id == organization_id)
            .order_by(HealthISFGovernanceApproval.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": row.id,
                "organization_id": row.organization_id,
                "action_type": row.action_type,
                "action_payload": json.loads(row.action_payload_json or "{}") if str(row.action_payload_json or "").strip().startswith("{") else {"raw": row.action_payload_json},
                "approval_required": row.approval_required,
                "approved_by": row.approved_by_user_id,
                "approved_by_user_id": row.approved_by_user_id,
                "approval_timestamp": row.approval_timestamp.isoformat() if row.approval_timestamp else None,
                "rollback_available": row.rollback_available,
                "execution_expiration": row.execution_expiration.isoformat() if row.execution_expiration else None,
                "status": row.status,
                "confidence_score": row.confidence_score,
                "tenant_scope": row.tenant_scope,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ]
