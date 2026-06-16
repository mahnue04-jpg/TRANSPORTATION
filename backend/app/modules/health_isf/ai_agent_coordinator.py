"""Multi-agent coordinator for deterministic autonomous enterprise operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.helpers import now
from app.modules.health_isf.ai_action_executor import AIActionExecutor
from app.modules.health_isf.ai_audit_engine import AIAuditEngine
from app.modules.health_isf.ai_decision_engine import AIDecisionEngine
from app.modules.health_isf.enterprise_feature_flags import is_feature_enabled
from app.modules.health_isf.enterprise_memory import EnterpriseMemoryLayer
from app.modules.health_isf.incident_detection_engine import IncidentDetectionEngine
from app.modules.health_isf.predictive_operations import PredictiveOperationsEngine
from app.modules.health_isf.realtime import SubscriptionType, get_broadcaster


@dataclass(frozen=True)
class AgentTask:
    agent_name: str
    action_type: str
    parameters: dict[str, Any]


class AIAgentCoordinator:
    _org_locks: dict[str, asyncio.Lock] = {}
    _execution_keys: set[str] = set()

    @classmethod
    def _lock(cls, organization_id: str) -> asyncio.Lock:
        lock = cls._org_locks.get(organization_id)
        if lock is None:
            lock = asyncio.Lock()
            cls._org_locks[organization_id] = lock
        return lock

    @classmethod
    async def orchestrate(
        cls,
        db: Session,
        *,
        organization_id: str,
        user: UserContext,
        telemetry: dict[str, Any],
        auto_execute: bool = False,
    ) -> dict[str, Any]:
        if not is_feature_enabled("AI_MULTI_AGENT_RUNTIME", role=user.role):
            return {
                "organization_id": organization_id,
                "enabled": False,
                "reason": "AI multi-agent runtime disabled",
                "agents": [],
                "decision": None,
                "executions": [],
            }

        async with cls._lock(organization_id):
            incidents = IncidentDetectionEngine.detect(db, organization_id=organization_id)
            predictions = PredictiveOperationsEngine.predict(db, organization_id=organization_id)

            task_candidates: list[AgentTask] = []
            for incident in incidents:
                incident_type = str(incident.get("incident_type") or "")
                if incident_type in {"dispatch_congestion", "sla_breach"} and is_feature_enabled("AI_INCIDENT_AUTORECOVERY", role=user.role):
                    task_candidates.append(AgentTask("DispatchAgent", "run_recovery", {"dry_run": True}))
                if incident_type in {"retry_spike", "realtime_feed_degradation"}:
                    task_candidates.append(AgentTask("RecoveryAgent", "replay_dead_letters", {"limit": 20}))
                if incident_type in {"provider_failure_spike", "driver_shortage"}:
                    task_candidates.append(AgentTask("EscalationAgent", "escalate_incident", {"summary": incident.get("incident_type")}))

            # Deterministic ordering prevents duplicate action drift.
            task_candidates = sorted(task_candidates, key=lambda t: (t.agent_name, t.action_type))
            deduped: list[AgentTask] = []
            seen = set()
            for task in task_candidates:
                key = f"{task.agent_name}:{task.action_type}:{str(sorted(task.parameters.items()))}"
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(task)

            candidate_actions = [
                {"agent": task.agent_name, "action_type": task.action_type, "parameters": task.parameters}
                for task in deduped
            ]
            decision = AIDecisionEngine.build_decision(
                organization_id=organization_id,
                incidents=incidents,
                predictions=predictions,
                telemetry=telemetry,
                candidate_actions=candidate_actions,
            )
            explainability = AIAuditEngine.record_decision(
                db,
                organization_id=organization_id,
                actor_user_id=user.user_id,
                decision=decision,
                supporting_signals=[
                    {"incidents": len(incidents)},
                    {"predictions": len(predictions)},
                ],
            )

            await EnterpriseMemoryLayer.write_memory(
                db,
                organization_id=organization_id,
                memory_type="ai_action_history",
                actor_user_id=user.user_id,
                ttl_seconds=14 * 24 * 3600,
                context={
                    "decision_id": decision["decision_id"],
                    "decision_type": decision["decision_type"],
                    "incident_count": len(incidents),
                    "prediction_count": len(predictions),
                },
                replay_key=decision["decision_id"],
            )
            await EnterpriseMemoryLayer.record_incident_history(
                db,
                organization_id=organization_id,
                actor_user_id=user.user_id,
                context={"incidents": incidents, "decision_id": decision["decision_id"]},
            )
            await EnterpriseMemoryLayer.record_workload_trend_memory(
                db,
                organization_id=organization_id,
                actor_user_id=user.user_id,
                context={"predictions": predictions, "decision_id": decision["decision_id"]},
            )

            executions: list[dict[str, Any]] = []
            if auto_execute and is_feature_enabled("AI_AUTONOMOUS_MODE", role=user.role):
                for action in decision.get("recommended_actions", []):
                    key = f"{organization_id}:{decision['decision_id']}:{action.get('action_type')}"
                    if key in cls._execution_keys:
                        continue
                    cls._execution_keys.add(key)
                    try:
                        execution = await AIActionExecutor.execute(
                            db,
                            user=user,
                            organization_id=organization_id,
                            action_type=str(action.get("action_type") or ""),
                            parameters=action.get("parameters") or {},
                        )
                        executions.append(execution)
                    finally:
                        cls._execution_keys.discard(key)

            broadcaster = get_broadcaster()
            await broadcaster.broadcast_event(
                event_type="ai_decision_update",
                payload={
                    "decision": decision,
                    "explainability": explainability,
                    "incident_count": len(incidents),
                    "prediction_count": len(predictions),
                    "execution_count": len(executions),
                    "generated_at": now().isoformat(),
                },
                organization_id=organization_id,
                subscription_types=[
                    SubscriptionType.WORKFLOW_EVENTS.value,
                    SubscriptionType.DISPATCHER_BOARD.value,
                ],
            )

            return {
                "organization_id": organization_id,
                "enabled": True,
                "agents": ["DispatchAgent", "IncidentAgent", "AnalyticsAgent", "RecoveryAgent", "EscalationAgent"],
                "incidents": incidents,
                "predictions": predictions,
                "decision": decision,
                "explainability": explainability,
                "executions": executions,
            }
