"""Controlled AI action execution layer with tenant/RBAC/audit safeguards."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.auth import ROLE_ADMIN, ROLE_DISPATCHER, ROLE_SUPER_ADMIN_SUPPORT, UserContext
from app.helpers import now, uuid4
from app.modules.health_isf.ai_audit_engine import AIAuditEngine
from app.modules.health_isf.ai_governance_engine import AIGovernanceEngine
from app.modules.health_isf.memory_service import OperationalMemoryService
from app.modules.health_isf.enterprise_feature_flags import is_feature_enabled
from app.modules.health_isf.security import ensure_write_access, enforce_tenant_scope
from app.modules.health_isf.workflow_engine import WorkflowOrchestrationService


class AIActionExecutor:
    @staticmethod
    def _ensure_authority(user: UserContext, organization_id: str) -> None:
        ensure_write_access(user)
        enforce_tenant_scope(user, organization_id)
        if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER}:
            raise PermissionError("Role not authorized for autonomous execution")

    @classmethod
    async def execute(
        cls,
        db: Session,
        *,
        user: UserContext,
        organization_id: str,
        action_type: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        if not is_feature_enabled("AI_AUTONOMOUS_MODE", role=user.role):
            raise PermissionError("AI autonomous mode is disabled")
        if not is_feature_enabled("ENABLE_AUTONOMOUS_ACTIONS", role=user.role):
            raise PermissionError("Autonomous actions are disabled by enterprise policy")

        approval_id = parameters.get("approval_id")
        approval_token = parameters.get("approval_token")
        if approval_id or approval_token:
            AIGovernanceEngine.validate_execution_policy(
                db,
                user=user,
                organization_id=organization_id,
                action_type=str(action_type or "").strip().lower(),
                confidence_score=float(parameters.get("confidence_score") or 0.0),
                approval_token=str(approval_token) if approval_token else None,
                approval_id=str(approval_id) if approval_id else None,
            )

        cls._ensure_authority(user, organization_id)

        action_type = str(action_type or "").strip().lower()
        rollback_reference = f"rollback_{uuid4()}"
        executed_at = now().isoformat()
        result: dict[str, Any]

        if action_type == "run_recovery":
            result = await WorkflowOrchestrationService.run_recovery(
                db,
                organization_id=organization_id,
                ride_id=parameters.get("ride_id"),
                actor_user_id=user.user_id,
                note=parameters.get("note"),
                dry_run=bool(parameters.get("dry_run", False)),
            )
        elif action_type == "reassign_ride":
            result = await WorkflowOrchestrationService.run_reassign(
                db,
                organization_id=organization_id,
                ride_id=str(parameters.get("ride_id") or ""),
                actor_user_id=user.user_id,
                driver_id=parameters.get("driver_id"),
                suggest_only=bool(parameters.get("suggest_only", False)),
                approval_override=bool(parameters.get("approval_override", False)),
            )
        elif action_type == "replay_dead_letters":
            result = await WorkflowOrchestrationService.replay_dead_letters(
                db,
                organization_id=organization_id,
                actor_user_id=user.user_id,
                limit=int(parameters.get("limit", 25)),
            )
        elif action_type == "escalate_incident":
            if not is_feature_enabled("AI_AUTO_ESCALATION", role=user.role):
                raise PermissionError("AI auto escalation is disabled")
            result = await WorkflowOrchestrationService.escalate_incident(
                db,
                organization_id=organization_id,
                actor_user_id=user.user_id,
                incident_id=parameters.get("incident_id"),
                ride_id=parameters.get("ride_id"),
                summary=parameters.get("summary"),
                severity=str(parameters.get("severity") or "high"),
                target_role=str(parameters.get("target_role") or "dispatcher"),
                escalation_level=int(parameters.get("escalation_level") or 1),
                details=parameters.get("details") or {},
            )
        else:
            raise ValueError(f"Unsupported action_type: {action_type}")

        explainability = {
            "why_this_action": f"Action {action_type} requested by autonomous command center.",
            "supporting_signals": [
                {"organization_id": organization_id},
                {"requested_by": user.user_id},
            ],
            "risk_evaluation": "guarded_execution",
            "rollback_available": True,
        }

        AIAuditEngine.record_action(
            db,
            organization_id=organization_id,
            actor_user_id=user.user_id,
            action_payload={
                "action_type": action_type,
                "parameters": parameters,
                "executed_at": executed_at,
            },
            explainability=explainability,
            rollback_reference=rollback_reference,
        )

        OperationalMemoryService.record_execution(
            db,
            organization_id=organization_id,
            actor_user_id=user.user_id,
            execution={
                "action_type": action_type,
                "organization_id": organization_id,
                "parameters": parameters,
                "executed_at": executed_at,
                "result": result,
                "rollback_reference": rollback_reference,
            },
            replay_hint=f"execution:{organization_id}:{action_type}:{executed_at}",
        )

        return {
            "action_type": action_type,
            "organization_id": organization_id,
            "executed_at": executed_at,
            "result": result,
            "rollback_reference": rollback_reference,
            "rollback_available": True,
            "tenant_isolated": True,
            "audited": True,
        }
