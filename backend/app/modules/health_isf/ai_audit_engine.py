"""AI audit and explainability engine for autonomous enterprise actions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.models import HealthISFWorkflowAuditLog
from app.modules.health_isf.security_service import SecurityAuditService


class AIAuditEngine:
    @staticmethod
    def _decision_hash(payload: dict[str, Any]) -> str:
        material = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @classmethod
    def record_decision(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        decision: dict[str, Any],
        supporting_signals: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        explainability = {
            "why_this_action": decision.get("reasoning_summary") or "Operational reasoning path selected by AI decision engine.",
            "supporting_signals": supporting_signals or [],
            "risk_evaluation": decision.get("risk_level", "unknown"),
            "rollback_available": bool(decision.get("requires_human_approval", False) is False),
        }
        payload = {
            "decision": decision,
            "explainability": explainability,
            "decision_hash": cls._decision_hash(decision),
            "recorded_at": now().isoformat(),
        }
        row = HealthISFWorkflowAuditLog(
            id=str(uuid4()),
            organization_id=organization_id,
            workflow_execution_id=None,
            incident_id=None,
            escalation_id=None,
            event_type="ai.decision.recorded",
            actor_user_id=actor_user_id,
            payload=json.dumps(payload, separators=(",", ":"), default=str),
            created_at=now(),
        )
        db.add(row)
        SecurityAuditService.log_action(
            db,
            organization_id=organization_id,
            action_type="ai_decision_recorded",
            actor_user_id=actor_user_id,
            details={"decision_id": decision.get("decision_id"), "risk_level": decision.get("risk_level")},
        )
        db.commit()
        return explainability

    @classmethod
    def record_action(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        action_payload: dict[str, Any],
        explainability: dict[str, Any],
        rollback_reference: str | None,
    ) -> None:
        payload = {
            "action": action_payload,
            "explainability": {
                **explainability,
                "rollback_available": bool(rollback_reference),
                "rollback_reference": rollback_reference,
            },
            "recorded_at": now().isoformat(),
        }
        row = HealthISFWorkflowAuditLog(
            id=str(uuid4()),
            organization_id=organization_id,
            workflow_execution_id=None,
            incident_id=None,
            escalation_id=None,
            event_type="ai.action.executed",
            actor_user_id=actor_user_id,
            payload=json.dumps(payload, separators=(",", ":"), default=str),
            created_at=now(),
        )
        db.add(row)
        SecurityAuditService.log_action(
            db,
            organization_id=organization_id,
            action_type="ai_action_executed",
            actor_user_id=actor_user_id,
            details={
                "action_type": action_payload.get("action_type"),
                "rollback_reference": rollback_reference,
            },
        )
        db.commit()

    @classmethod
    def recent_audit_events(
        cls,
        db: Session,
        *,
        organization_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(HealthISFWorkflowAuditLog.organization_id == organization_id)
            .filter(HealthISFWorkflowAuditLog.event_type.like("ai.%"))
            .order_by(HealthISFWorkflowAuditLog.created_at.desc())
            .limit(limit)
            .all()
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row.payload or "{}")
            except Exception:
                payload = {"raw": row.payload}
            out.append(
                {
                    "event_type": row.event_type,
                    "created_at": row.created_at.isoformat(),
                    "actor_user_id": row.actor_user_id,
                    "payload": payload,
                }
            )
        return out
