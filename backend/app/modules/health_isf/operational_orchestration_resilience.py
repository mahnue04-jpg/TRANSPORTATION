"""Automated operational orchestration and resilience management for Health ISF."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, desc, func
from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.approval_contract import create_approval_proposal
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    DriverStatus,
    HealthISFAutomationPolicy,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFDriverLocationPing,
    HealthISFRide,
    HealthISFRideRoutePlan,
    HealthISFWorkflowAuditLog,
    HealthISFWorkflowEscalation,
    HealthISFWorkflowIncident,
    OperationalAlertLog,
    RideStatus,
    WorkflowEscalationStatus,
    WorkflowIncidentStatus,
)
from app.modules.health_isf.operational_event_models import OperationalEventType
from app.modules.health_isf.operational_replay_service import OperationalReplayService
from app.modules.health_isf.operational_sync_engine import OperationalSynchronizationEngine
from app.modules.health_isf.realtime import get_broadcaster
from app.modules.health_isf.realtime_service import OperationalAlertService, RetryQueueService


_TERMINAL_RIDE_STATES = {
    RideStatus.COMPLETED.value,
    RideStatus.CANCELLED.value,
    RideStatus.FAILED.value,
}

_STATUS_RESOLVED_STATES = {
    WorkflowIncidentStatus.RESOLVED.value,
    WorkflowIncidentStatus.SUPPRESSED.value,
}


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return now().replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _minutes_since(value: datetime | None) -> float:
    return max(0.0, (_as_utc(now()) - _as_utc(value)).total_seconds() / 60.0)


def _status_text(value: Any) -> str:
    if hasattr(value, "value"):
        return str(getattr(value, "value") or "").lower()
    raw = str(value or "").strip().lower()
    if "." in raw:
        return raw.split(".")[-1]
    return raw


def _safe_json_load(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        parsed = json.loads(raw)
    except Exception:
        return fallback
    return parsed


class OperationalOrchestrationResilienceService:
    """Backend-authoritative automation for escalation, dispatch recommendations, and resilience."""

    DEFAULT_THRESHOLDS: dict[str, Any] = {
        "automation_enabled": True,
        "sla_escalation_minutes": 20,
        "delayed_pickup_minutes": 25,
        "unassigned_ride_minutes": 18,
        "inactive_driver_minutes": 15,
        "dispatcher_overload_ratio": 2.0,
        "reconnect_failure_disconnects_5m": 4,
        "repeated_cancellation_count_1h": 3,
        "escalation_dedup_minutes": 10,
        "recommendation_dedup_minutes": 8,
        "recovery_dedup_minutes": 8,
        "stale_workflow_minutes": 25,
        "predictive_window_minutes": 60,
        "predictive_forecast_dedup_minutes": 8,
        "predictive_recovery_dedup_minutes": 8,
        "predicted_sla_breach_risk_threshold": 0.6,
        "predicted_arrival_delay_risk_threshold": 0.58,
        "queue_pressure_risk_threshold": 0.6,
        "dispatcher_overload_projection_threshold": 2.3,
        "driver_shortage_projection_threshold": 0.35,
        "reconnect_instability_risk_threshold": 0.55,
        "driver_reliability_window_days": 14,
        "rider_risk_window_days": 30,
        "autonomous_decision_enabled": True,
        "autonomous_confidence_min": 0.65,
        "autonomous_max_execution_depth": 4,
        "autonomous_loop_window_minutes": 20,
        "autonomous_loop_max_same_action": 3,
        "autonomous_duplicate_suppression_minutes": 12,
        "autonomous_conflict_safety_enabled": True,
        "autonomous_sync_integrity_required": True,
        "autonomous_approval_expiration_minutes": 30,
        "multi_agent_consensus_min_confidence": 0.62,
        "multi_agent_duplicate_suppression_minutes": 10,
        "multi_agent_storm_max_actions": 8,
        "multi_agent_memory_snapshot_minutes": 12,
        "multi_agent_negotiation_round_limit": 6,
        "multi_agent_simulation_horizon_minutes": 45,
        "authority_session_ttl_minutes": 45,
        "authority_stale_replay_minutes": 90,
        "supervised_execution_risk_threshold": 0.72,
        "supervised_recovery_stage_limit": 3,
    }

    SEVERITY_ORDER: dict[str, int] = {
        "low": 1,
        "medium": 2,
        "high": 3,
        "critical": 4,
    }

    INCIDENT_ESCALATION_RULES: dict[str, dict[str, Any]] = {
        "sla_breach_monitoring": {
            "escalation_type": "automatic_sla_escalation",
            "min_severity": "high",
            "target_queue": "dispatch_supervision",
            "target_role": "supervisor",
            "required_occurrence": 1,
        },
        "missed_pickup_detection": {
            "escalation_type": "delayed_pickup_escalation",
            "min_severity": "high",
            "target_queue": "pickup_recovery",
            "target_role": "dispatcher",
            "required_occurrence": 1,
        },
        "orphaned_rides": {
            "escalation_type": "unassigned_ride_escalation",
            "min_severity": "high",
            "target_queue": "reassignment_queue",
            "target_role": "dispatcher",
            "required_occurrence": 1,
        },
        "inactive_driver_detection": {
            "escalation_type": "inactive_driver_escalation",
            "min_severity": "medium",
            "target_queue": "driver_recovery",
            "target_role": "driver",
            "required_occurrence": 1,
        },
        "dispatch_queue_congestion": {
            "escalation_type": "dispatcher_overload_escalation",
            "min_severity": "high",
            "target_queue": "operations_supervision",
            "target_role": "supervisor",
            "required_occurrence": 1,
        },
        "websocket_disconnect_degradation_alert": {
            "escalation_type": "reconnect_failure_escalation",
            "min_severity": "medium",
            "target_queue": "platform_resilience",
            "target_role": "command-center",
            "required_occurrence": 1,
        },
        "repeated_cancellation_escalation": {
            "escalation_type": "repeated_cancellation_escalation",
            "min_severity": "medium",
            "target_queue": "cancellation_risk",
            "target_role": "dispatcher",
            "required_occurrence": 1,
        },
    }

    CROSS_ROLE_SCOPE = [
        "dispatcher",
        "rider",
        "driver",
        "supervisor",
        "command-center",
        "admin",
        "staff",
        "provider",
    ]

    PREDICTIVE_AUDIT_TYPES = {
        "orchestration.prediction.generated",
        "orchestration.reliability.driver",
        "orchestration.rider_risk.detected",
        "orchestration.regional.forecast",
        "orchestration.recovery.proactive",
        "orchestration.resilience.transition",
        "orchestration.escalation.generated",
        "orchestration.recommendation.generated",
        "orchestration.recovery.performed",
    }

    AUTONOMOUS_AUDIT_TYPES = {
        "orchestration.autonomous.policy.evaluated",
        "orchestration.autonomous.decision.proposed",
        "orchestration.autonomous.decision.executed",
        "orchestration.autonomous.decision.denied",
        "orchestration.autonomous.decision.conflict",
        "orchestration.autonomous.approval.required",
        "orchestration.autonomous.override.persisted",
        "orchestration.autonomous.rollback.recorded",
        "orchestration.autonomous.recovery.executed",
    }

    MULTI_AGENT_AUDIT_TYPES = {
        "orchestration.multi_agent.coordination.generated",
        "orchestration.multi_agent.consensus.computed",
        "orchestration.multi_agent.consensus.executed",
        "orchestration.multi_agent.consensus.denied",
        "orchestration.multi_agent.consensus.conflict",
        "orchestration.multi_agent.negotiation.round",
        "orchestration.multi_agent.negotiation.resolved",
        "orchestration.multi_agent.arbitration.policy_conflict",
        "orchestration.multi_agent.storm.suppressed",
        "orchestration.multi_agent.simulation.generated",
        "orchestration.multi_agent.recovery.coordinated",
        "orchestration.multi_agent.memory.snapshot",
    }

    AUTHORITY_AUDIT_TYPES = {
        "orchestration.authority.session.issued",
        "orchestration.authority.session.validated",
        "orchestration.authority.session.revoked",
        "orchestration.authority.execution.requested",
        "orchestration.authority.execution.approved",
        "orchestration.authority.execution.denied",
        "orchestration.authority.execution.rollback_linked",
        "orchestration.authority.recovery.executed",
        "orchestration.authority.hydration.restored",
        "orchestration.authority.runtime.integrity",
    }

    OPERATIONAL_CAPABILITY_MATRIX: dict[str, set[str]] = {
        "dispatcher": {
            "dispatch.execute",
            "recovery.request",
            "escalation.request",
            "snapshot.read",
        },
        "admin": {
            "dispatch.execute",
            "recovery.execute",
            "escalation.execute",
            "rollback.execute",
            "snapshot.read",
            "snapshot.hydrate",
            "authority.escalate",
            "orchestration.activate",
        },
        "regional_supervisor": {
            "dispatch.execute",
            "recovery.execute",
            "escalation.execute",
            "snapshot.read",
            "orchestration.activate",
        },
        "provider_coordinator": {
            "dispatch.execute",
            "recovery.request",
            "snapshot.read",
        },
        "emergency_escalation": {
            "escalation.execute",
            "recovery.execute",
            "authority.escalate",
            "orchestration.activate",
        },
        "recovery_coordinator": {
            "recovery.execute",
            "rollback.execute",
            "snapshot.read",
            "snapshot.hydrate",
            "orchestration.activate",
        },
        "system_orchestrator": {
            "dispatch.execute",
            "recovery.execute",
            "escalation.execute",
            "rollback.execute",
            "snapshot.read",
            "snapshot.hydrate",
            "orchestration.activate",
            "authority.escalate",
        },
    }

    AUTHORITY_SIGNING_SALT = "health_isf_controlled_authority_v1"

    COORDINATED_AGENT_REGISTRY: dict[str, dict[str, Any]] = {
        "dispatch_intelligence_agent": {
            "weight": 1.0,
            "authority_priority": 8,
            "domains": ["dispatch", "queue_balancing"],
        },
        "sla_risk_agent": {
            "weight": 1.08,
            "authority_priority": 9,
            "domains": ["sla_risk", "breach_prevention"],
        },
        "recovery_coordination_agent": {
            "weight": 1.1,
            "authority_priority": 10,
            "domains": ["recovery", "workflow_repair"],
        },
        "overload_mitigation_agent": {
            "weight": 1.05,
            "authority_priority": 7,
            "domains": ["overload", "redistribution"],
        },
        "driver_balancing_agent": {
            "weight": 1.02,
            "authority_priority": 6,
            "domains": ["driver_balance", "coverage"],
        },
        "reconnect_stabilization_agent": {
            "weight": 1.12,
            "authority_priority": 11,
            "domains": ["reconnect", "state_stabilization"],
        },
        "escalation_coordination_agent": {
            "weight": 1.0,
            "authority_priority": 5,
            "domains": ["escalation", "triage"],
        },
        "regional_mobility_intelligence_agent": {
            "weight": 0.98,
            "authority_priority": 4,
            "domains": ["regional_mobility", "capacity_forecast"],
        },
    }

    @staticmethod
    def _severity_rank(severity: str | None) -> int:
        return int(OperationalOrchestrationResilienceService.SEVERITY_ORDER.get(str(severity or "medium").lower(), 2))

    @staticmethod
    def _bounded(value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, float(value)))

    @staticmethod
    def _region_key_for_ride(
        ride: HealthISFRide,
        route: HealthISFRideRoutePlan | None,
    ) -> str:
        if route is not None:
            return f"geo:{round(float(route.origin_latitude), 2)}:{round(float(route.origin_longitude), 2)}"
        pickup = str(ride.pickup_address or "").strip().lower()
        if pickup:
            return f"addr:{pickup.split(',')[0][:48]}"
        return "unknown_region"

    @staticmethod
    def _emit_predictive_sync(
        *,
        organization_id: str,
        payload: dict[str, Any],
        source_nonce: str,
        actor_user_id: str | None,
    ) -> None:
        OperationalSynchronizationEngine.publish_event(
            organization_id=organization_id,
            event_type=OperationalEventType.SUPERVISION_ALERT,
            payload={**payload, "predictive": True, "automated": True},
            role_scope=list(OperationalOrchestrationResilienceService.CROSS_ROLE_SCOPE),
            source_nonce=source_nonce,
            metadata={"actor_user_id": actor_user_id or "", "source": "operational_predictive_intelligence"},
        )

    @staticmethod
    def _thresholds(db: Session, organization_id: str) -> dict[str, Any]:
        thresholds = dict(OperationalOrchestrationResilienceService.DEFAULT_THRESHOLDS)
        policy = (
            db.query(HealthISFAutomationPolicy)
            .filter(
                HealthISFAutomationPolicy.organization_id == organization_id,
                HealthISFAutomationPolicy.is_enabled.is_(True),
            )
            .order_by(desc(HealthISFAutomationPolicy.updated_at))
            .first()
        )
        if policy is None:
            return thresholds

        thresholds["automation_enabled"] = bool(policy.is_enabled)
        thresholds["sla_escalation_minutes"] = int(policy.delayed_pickup_minutes or thresholds["sla_escalation_minutes"])
        thresholds["delayed_pickup_minutes"] = int(policy.delayed_pickup_minutes or thresholds["delayed_pickup_minutes"])

        policy_rules = _safe_json_load(policy.policy_rules, {})
        if isinstance(policy_rules, dict):
            for key, value in policy_rules.items():
                if key not in thresholds:
                    continue
                thresholds[key] = value

        return thresholds

    @staticmethod
    def _active_policy(db: Session, organization_id: str) -> HealthISFAutomationPolicy | None:
        return (
            db.query(HealthISFAutomationPolicy)
            .filter(
                HealthISFAutomationPolicy.organization_id == organization_id,
                HealthISFAutomationPolicy.is_enabled.is_(True),
            )
            .order_by(desc(HealthISFAutomationPolicy.updated_at))
            .first()
        )

    @staticmethod
    def _policy_rules(policy: HealthISFAutomationPolicy | None) -> dict[str, Any]:
        if policy is None:
            return {}
        parsed = _safe_json_load(policy.policy_rules, {})
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _stable_decision_id(
        *,
        organization_id: str,
        decision_type: str,
        material: dict[str, Any],
    ) -> str:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "organization_id": organization_id,
                    "decision_type": decision_type,
                    "material": material,
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:20]
        return f"auto_dec_{digest}"

    @staticmethod
    def _decision_confidence(candidate: dict[str, Any]) -> float:
        inputs = [
            float(candidate.get("confidence", 0.0) or 0.0),
            float(candidate.get("risk_score", 0.0) or 0.0),
            float(candidate.get("priority_score", 0.0) or 0.0),
        ]
        non_zero = [value for value in inputs if value > 0.0]
        if non_zero:
            return OperationalOrchestrationResilienceService._bounded(sum(non_zero) / len(non_zero))
        return 0.5

    @staticmethod
    def _evaluate_policy_gate(
        *,
        organization_id: str,
        thresholds: dict[str, Any],
        policy: HealthISFAutomationPolicy | None,
        decision_type: str,
        decision_confidence: float,
        execution_depth: int,
    ) -> dict[str, Any]:
        rules = OperationalOrchestrationResilienceService._policy_rules(policy)
        reasons: list[str] = []

        if not bool(thresholds.get("autonomous_decision_enabled", True)):
            reasons.append("autonomous_decision_disabled")

        confidence_min = float(
            rules.get("autonomous_confidence_min", thresholds.get("autonomous_confidence_min", 0.65))
            or thresholds.get("autonomous_confidence_min", 0.65)
        )
        if float(decision_confidence) < confidence_min:
            reasons.append("confidence_below_threshold")

        max_depth = int(
            rules.get("autonomous_max_execution_depth", thresholds.get("autonomous_max_execution_depth", 4))
            or thresholds.get("autonomous_max_execution_depth", 4)
        )
        if int(execution_depth) > max_depth:
            reasons.append("max_execution_depth_exceeded")

        if policy is not None:
            if decision_type == "automated_reassignment_execution" and not bool(policy.auto_reassign_enabled):
                reasons.append("auto_reassign_disabled")
            if decision_type == "automated_escalation_execution" and not bool(policy.auto_escalation_enabled):
                reasons.append("auto_escalation_disabled")

        denied_types: set[str] = set()
        denied_type_values = rules.get("autonomous_denied_decision_types")
        if isinstance(denied_type_values, list):
            for item in denied_type_values:
                denied_types.add(str(item))
        if decision_type in denied_types:
            reasons.append("decision_type_denied_by_policy")

        approval_required_types: set[str] = set()
        approval_required_values = rules.get("approval_required_decision_types")
        if isinstance(approval_required_values, list):
            for item in approval_required_values:
                approval_required_types.add(str(item))
        requires_approval = bool(policy.approval_required) if policy is not None else False
        if decision_type in approval_required_types:
            requires_approval = True

        return {
            "organization_id": organization_id,
            "decision_type": decision_type,
            "allowed": len(reasons) == 0,
            "requires_approval": requires_approval,
            "reasons": reasons,
            "confidence_min": confidence_min,
            "max_depth": max_depth,
        }

    @staticmethod
    def _autonomous_loop_detected(
        db: Session,
        *,
        organization_id: str,
        decision_type: str,
        thresholds: dict[str, Any],
    ) -> bool:
        window_minutes = int(thresholds.get("autonomous_loop_window_minutes", 20) or 20)
        max_same = int(thresholds.get("autonomous_loop_max_same_action", 3) or 3)
        cutoff = now() - timedelta(minutes=max(1, window_minutes))
        count = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type == "orchestration.autonomous.decision.executed",
                HealthISFWorkflowAuditLog.created_at >= cutoff,
                HealthISFWorkflowAuditLog.payload.like(f'%"decision_type":"{decision_type}"%'),
            )
            .count()
        )
        return int(count) >= max(1, max_same)

    @staticmethod
    def _recent_duplicate_decision(
        db: Session,
        *,
        organization_id: str,
        dedup_key: str,
        thresholds: dict[str, Any],
    ) -> bool:
        return OperationalOrchestrationResilienceService._has_recent_audit_key(
            db,
            organization_id=organization_id,
            event_type="orchestration.autonomous.decision.executed",
            dedup_key=dedup_key,
            minutes=int(thresholds.get("autonomous_duplicate_suppression_minutes", 12) or 12),
        )

    @staticmethod
    def _audit(
        db: Session,
        *,
        organization_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_user_id: str | None = None,
        incident_id: str | None = None,
        escalation_id: str | None = None,
    ) -> HealthISFWorkflowAuditLog:
        row = HealthISFWorkflowAuditLog(
            id=str(uuid4()),
            organization_id=organization_id,
            workflow_execution_id=None,
            incident_id=incident_id,
            escalation_id=escalation_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            payload=json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str),
            created_at=now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def _has_recent_audit_key(
        db: Session,
        *,
        organization_id: str,
        event_type: str,
        dedup_key: str,
        minutes: int,
    ) -> bool:
        cutoff = now() - timedelta(minutes=max(1, int(minutes)))
        row = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type == event_type,
                HealthISFWorkflowAuditLog.created_at >= cutoff,
                HealthISFWorkflowAuditLog.payload.like(f'%"dedup_key":"{dedup_key}"%'),
            )
            .order_by(desc(HealthISFWorkflowAuditLog.created_at))
            .first()
        )
        return row is not None

    @staticmethod
    def _signature_material(payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _authority_secret(*, organization_id: str, policy: HealthISFAutomationPolicy | None) -> str:
        seed = {
            "organization_id": organization_id,
            "policy_id": str(policy.id) if policy is not None else "none",
            "salt": OperationalOrchestrationResilienceService.AUTHORITY_SIGNING_SALT,
        }
        return hashlib.sha256(
            OperationalOrchestrationResilienceService._signature_material(seed).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _sign_payload(*, secret: str, payload: dict[str, Any]) -> str:
        return hmac.new(
            secret.encode("utf-8"),
            OperationalOrchestrationResilienceService._signature_material(payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _verify_payload_signature(*, secret: str, payload: dict[str, Any], signature: str | None) -> bool:
        if not signature:
            return False
        expected = OperationalOrchestrationResilienceService._sign_payload(secret=secret, payload=payload)
        return hmac.compare_digest(expected, str(signature))

    @staticmethod
    def _resolve_capabilities(*, role: str, requested_capabilities: list[str] | None) -> set[str]:
        role_capabilities = set(
            OperationalOrchestrationResilienceService.OPERATIONAL_CAPABILITY_MATRIX.get(role, set())
        )
        if not requested_capabilities:
            return role_capabilities
        requested = {str(item) for item in requested_capabilities}
        return role_capabilities.intersection(requested)

    @staticmethod
    def issue_authenticated_operational_session(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str,
        role: str,
        requested_capabilities: list[str] | None = None,
        ttl_minutes: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        policy = OperationalOrchestrationResilienceService._active_policy(db, organization_id)
        ttl = int(
            ttl_minutes
            or thresholds.get("authority_session_ttl_minutes", 45)
            or 45
        )
        issued_at = _as_utc(now())
        expires_at = issued_at + timedelta(minutes=max(5, ttl))
        resolved_role = role if role in OperationalOrchestrationResilienceService.OPERATIONAL_CAPABILITY_MATRIX else "dispatcher"
        capabilities = sorted(
            OperationalOrchestrationResilienceService._resolve_capabilities(
                role=resolved_role,
                requested_capabilities=requested_capabilities,
            )
        )
        session_payload = {
            "session_id": str(uuid4()),
            "organization_id": organization_id,
            "actor_user_id": actor_user_id,
            "role": resolved_role,
            "capabilities": capabilities,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "nonce": str(uuid4()),
            "context": context or {},
            "state": "active",
        }
        secret = OperationalOrchestrationResilienceService._authority_secret(
            organization_id=organization_id,
            policy=policy,
        )
        signature_payload = {
            "session_id": session_payload["session_id"],
            "organization_id": organization_id,
            "actor_user_id": actor_user_id,
            "role": resolved_role,
            "capabilities": capabilities,
            "issued_at": session_payload["issued_at"],
            "expires_at": session_payload["expires_at"],
            "nonce": session_payload["nonce"],
        }
        session_payload["signature"] = OperationalOrchestrationResilienceService._sign_payload(
            secret=secret,
            payload=signature_payload,
        )
        session_payload["signature_material"] = signature_payload
        OperationalOrchestrationResilienceService._audit(
            db,
            organization_id=organization_id,
            event_type="orchestration.authority.session.issued",
            payload={
                "session_id": session_payload["session_id"],
                "actor_user_id": actor_user_id,
                "role": resolved_role,
                "capabilities": capabilities,
                "issued_at": session_payload["issued_at"],
                "expires_at": session_payload["expires_at"],
                "dedup_key": f"{organization_id}:authority_session:{session_payload['session_id']}",
            },
            actor_user_id=actor_user_id,
        )
        return session_payload

    @staticmethod
    def validate_authenticated_operational_session(
        db: Session,
        *,
        organization_id: str,
        session_payload: dict[str, Any],
        required_capability: str | None = None,
    ) -> dict[str, Any]:
        policy = OperationalOrchestrationResilienceService._active_policy(db, organization_id)
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        reasons: list[str] = []

        if str(session_payload.get("organization_id") or "") != organization_id:
            reasons.append("session_org_mismatch")

        expires_at_raw = session_payload.get("expires_at")
        try:
            expires_at = _as_utc(datetime.fromisoformat(str(expires_at_raw)))
        except Exception:
            expires_at = _as_utc(now()) - timedelta(minutes=1)
            reasons.append("session_expiration_invalid")

        if _as_utc(now()) > expires_at:
            reasons.append("session_expired")

        signature_material = session_payload.get("signature_material")
        signature = session_payload.get("signature")
        if not isinstance(signature_material, dict):
            reasons.append("session_signature_material_invalid")
        else:
            secret = OperationalOrchestrationResilienceService._authority_secret(
                organization_id=organization_id,
                policy=policy,
            )
            if not OperationalOrchestrationResilienceService._verify_payload_signature(
                secret=secret,
                payload=signature_material,
                signature=str(signature or ""),
            ):
                reasons.append("session_signature_invalid")

        role = str(session_payload.get("role") or "dispatcher")
        capabilities = set(str(item) for item in list(session_payload.get("capabilities") or []))
        allowed = OperationalOrchestrationResilienceService.OPERATIONAL_CAPABILITY_MATRIX.get(role, set())
        if not capabilities.issubset(allowed):
            reasons.append("capability_scope_violation")
        if required_capability and required_capability not in capabilities:
            reasons.append("required_capability_missing")

        issued_at_raw = session_payload.get("issued_at")
        try:
            issued_at = _as_utc(datetime.fromisoformat(str(issued_at_raw)))
        except Exception:
            issued_at = _as_utc(now())
            reasons.append("session_issue_timestamp_invalid")
        stale_minutes = int(thresholds.get("authority_stale_replay_minutes", 90) or 90)
        if (_as_utc(now()) - issued_at).total_seconds() > (stale_minutes * 60):
            reasons.append("stale_authority_session")

        result = {
            "valid": len(reasons) == 0,
            "reasons": reasons,
            "role": role,
            "capabilities": sorted(capabilities),
            "session_id": str(session_payload.get("session_id") or ""),
            "actor_user_id": str(session_payload.get("actor_user_id") or ""),
            "organization_id": organization_id,
            "validated_at": now().isoformat(),
            "required_capability": required_capability,
            "replay_safe": "stale_authority_session" not in reasons,
            "deterministic": True,
        }
        OperationalOrchestrationResilienceService._audit(
            db,
            organization_id=organization_id,
            event_type="orchestration.authority.session.validated",
            payload=result,
            actor_user_id=result.get("actor_user_id") or None,
        )
        return result

    @staticmethod
    def build_signed_orchestration_action(
        db: Session,
        *,
        organization_id: str,
        authority_session: dict[str, Any],
        action_type: str,
        action_payload: dict[str, Any],
        rollback_required: bool,
    ) -> dict[str, Any]:
        policy = OperationalOrchestrationResilienceService._active_policy(db, organization_id)
        action = {
            "action_id": OperationalOrchestrationResilienceService._stable_decision_id(
                organization_id=organization_id,
                decision_type=f"authority_action:{action_type}",
                material={
                    "session_id": str(authority_session.get("session_id") or ""),
                    "action_type": action_type,
                    "payload_digest": hashlib.sha256(
                        OperationalOrchestrationResilienceService._signature_material(action_payload).encode("utf-8")
                    ).hexdigest()[:16],
                },
            ),
            "organization_id": organization_id,
            "session_id": str(authority_session.get("session_id") or ""),
            "actor_user_id": str(authority_session.get("actor_user_id") or ""),
            "role": str(authority_session.get("role") or "dispatcher"),
            "action_type": action_type,
            "payload": dict(action_payload),
            "rollback_required": bool(rollback_required),
            "requested_at": now().isoformat(),
            "nonce": str(uuid4()),
        }
        signature_material = {
            "action_id": action["action_id"],
            "organization_id": organization_id,
            "session_id": action["session_id"],
            "role": action["role"],
            "action_type": action_type,
            "nonce": action["nonce"],
        }
        secret = OperationalOrchestrationResilienceService._authority_secret(
            organization_id=organization_id,
            policy=policy,
        )
        action["signature"] = OperationalOrchestrationResilienceService._sign_payload(
            secret=secret,
            payload=signature_material,
        )
        action["signature_material"] = signature_material
        action["dedup_key"] = f"{organization_id}:authority_action:{action['action_id']}"
        OperationalOrchestrationResilienceService._audit(
            db,
            organization_id=organization_id,
            event_type="orchestration.authority.execution.requested",
            payload=action,
            actor_user_id=action["actor_user_id"] or None,
        )
        return action

    @staticmethod
    def activate_supervised_execution(
        db: Session,
        *,
        organization_id: str,
        authority_session: dict[str, Any],
        action_type: str,
        action_payload: dict[str, Any],
        required_capability: str,
        actor_user_id: str | None,
        risk_score: float,
        rollback_required: bool,
    ) -> dict[str, Any]:
        validation = OperationalOrchestrationResilienceService.validate_authenticated_operational_session(
            db,
            organization_id=organization_id,
            session_payload=authority_session,
            required_capability=required_capability,
        )
        if not bool(validation.get("valid")):
            denied = {
                "action_type": action_type,
                "reason": "authority_validation_failed",
                "validation": validation,
                "generated_at": now().isoformat(),
            }
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.authority.execution.denied",
                payload=denied,
                actor_user_id=actor_user_id,
            )
            return {
                "activated": False,
                "approval_required": False,
                "denied": denied,
                "rollback_link": None,
                "staged_authority_escalation": False,
            }

        signed_action = OperationalOrchestrationResilienceService.build_signed_orchestration_action(
            db,
            organization_id=organization_id,
            authority_session=authority_session,
            action_type=action_type,
            action_payload=action_payload,
            rollback_required=rollback_required,
        )

        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        approval_required = float(risk_score) >= float(
            thresholds.get("supervised_execution_risk_threshold", 0.72) or 0.72
        )
        staged_escalation = False
        approval_payload: dict[str, Any] | None = None
        if approval_required:
            approval = create_approval_proposal(
                db,
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action_type=action_type,
                parameters={
                    "signed_action": signed_action,
                    "required_capability": required_capability,
                },
                confidence_score=OperationalOrchestrationResilienceService._bounded(risk_score),
                rollback_available=rollback_required,
                expiration_minutes=int(thresholds.get("autonomous_approval_expiration_minutes", 30) or 30),
                tenant_scope=organization_id,
            )
            approval_payload = {
                "approval_id": str(approval.id),
                "status": str(approval.status),
                "approval_required": True,
                "signed_action_id": signed_action.get("action_id"),
            }
            staged_escalation = True

        if approval_payload is not None:
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.authority.execution.denied",
                payload={
                    "action_type": action_type,
                    "reason": "approval_gated_execution",
                    "approval": approval_payload,
                    "signed_action_id": signed_action.get("action_id"),
                },
                actor_user_id=actor_user_id,
            )
            return {
                "activated": False,
                "approval_required": True,
                "approval": approval_payload,
                "signed_action": signed_action,
                "rollback_link": None,
                "staged_authority_escalation": staged_escalation,
            }

        rollback_link = None
        if rollback_required:
            rollback_link = {
                "rollback_id": str(uuid4()),
                "linked_action_id": signed_action.get("action_id"),
                "linked_at": now().isoformat(),
                "reversible": True,
                "dedup_key": f"rollback:{signed_action.get('action_id')}",
            }
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.authority.execution.rollback_linked",
                payload=rollback_link,
                actor_user_id=actor_user_id,
            )

        activated_payload = {
            "action_type": action_type,
            "signed_action": signed_action,
            "rollback_link": rollback_link,
            "activated_at": now().isoformat(),
            "supervised": True,
            "backend_authoritative": True,
        }
        OperationalOrchestrationResilienceService._audit(
            db,
            organization_id=organization_id,
            event_type="orchestration.authority.execution.approved",
            payload=activated_payload,
            actor_user_id=actor_user_id,
        )
        return {
            "activated": True,
            "approval_required": False,
            "signed_action": signed_action,
            "rollback_link": rollback_link,
            "staged_authority_escalation": staged_escalation,
        }

    @staticmethod
    def execute_controlled_recovery_execution(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        authority_session: dict[str, Any],
        recovery_actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        executed: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        denied: list[dict[str, Any]] = []
        stages = 0
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        stage_limit = int(thresholds.get("supervised_recovery_stage_limit", 3) or 3)

        for item in recovery_actions:
            if stages >= max(1, stage_limit):
                denied.append(
                    {
                        "action_type": "recovery.execute",
                        "reason": "supervised_stage_limit_reached",
                        "payload": item,
                    }
                )
                continue
            risk_score = float(item.get("risk_score", 0.0) or 0.0)
            activation = OperationalOrchestrationResilienceService.activate_supervised_execution(
                db,
                organization_id=organization_id,
                authority_session=authority_session,
                action_type="recovery.execute",
                action_payload=item,
                required_capability="recovery.execute",
                actor_user_id=actor_user_id,
                risk_score=risk_score,
                rollback_required=True,
            )
            stages += 1
            if bool(activation.get("activated")):
                executed.append(activation)
            elif bool(activation.get("approval_required")):
                pending.append(activation)
            else:
                denied.append(activation.get("denied") or {"reason": "recovery_activation_denied", "payload": item})

        lineage = {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "executed": executed,
            "pending_approval": pending,
            "denied": denied,
            "execution_count": len(executed),
            "pending_count": len(pending),
            "denial_count": len(denied),
            "supervised_recovery": True,
            "deterministic": True,
            "lineage_reconstructable": True,
        }
        OperationalOrchestrationResilienceService._audit(
            db,
            organization_id=organization_id,
            event_type="orchestration.authority.recovery.executed",
            payload=lineage,
            actor_user_id=actor_user_id,
        )
        return lineage

    @staticmethod
    def run_authenticated_hydration_recovery(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        authority_session: dict[str, Any],
    ) -> dict[str, Any]:
        validation = OperationalOrchestrationResilienceService.validate_authenticated_operational_session(
            db,
            organization_id=organization_id,
            session_payload=authority_session,
            required_capability="snapshot.hydrate",
        )
        if not bool(validation.get("valid")):
            return {
                "hydrated": False,
                "reason": "unauthenticated_hydration",
                "validation": validation,
                "replay_safe": False,
                "deterministic": True,
            }

        row = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type == "orchestration.multi_agent.memory.snapshot",
            )
            .order_by(desc(HealthISFWorkflowAuditLog.created_at), desc(HealthISFWorkflowAuditLog.id))
            .first()
        )
        payload = _safe_json_load(row.payload, {}) if row is not None else {}
        snapshot = payload if isinstance(payload, dict) else {}
        hydrated = {
            "hydrated": True,
            "organization_id": organization_id,
            "session_id": str(authority_session.get("session_id") or ""),
            "actor_user_id": actor_user_id,
            "role": str(authority_session.get("role") or "dispatcher"),
            "snapshot": snapshot,
            "snapshot_audit_id": str(row.id) if row is not None else None,
            "restored_at": now().isoformat(),
            "role_scoped": True,
            "replay_safe": True,
            "deterministic": True,
            "timeline_linked_rebuild": True,
        }
        OperationalOrchestrationResilienceService._audit(
            db,
            organization_id=organization_id,
            event_type="orchestration.authority.hydration.restored",
            payload=hydrated,
            actor_user_id=actor_user_id,
        )
        return hydrated

    @staticmethod
    def validate_runtime_integrity_protection(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        authority_session: dict[str, Any],
        distributed_rebuild: dict[str, Any],
    ) -> dict[str, Any]:
        validation = OperationalOrchestrationResilienceService.validate_authenticated_operational_session(
            db,
            organization_id=organization_id,
            session_payload=authority_session,
            required_capability="orchestration.activate",
        )
        integrity = {
            "organization_id": organization_id,
            "validated_at": now().isoformat(),
            "authority_validation": validation,
            "orchestration_tamper_detected": not bool(validation.get("valid")),
            "invalid_replay_rejected": bool(distributed_rebuild.get("replay_safe", False)),
            "stale_timeline_suppressed": "stale_authority_session" not in list(validation.get("reasons") or []),
            "distributed_integrity_checks": {
                "event_count": int(distributed_rebuild.get("event_count", 0) or 0),
                "replay_digest": str(distributed_rebuild.get("replay_digest") or ""),
                "sequence_ordered": bool(distributed_rebuild.get("sequence_ordered", False)),
            },
            "deterministic": True,
            "replay_safe": bool(distributed_rebuild.get("replay_safe", False)) and bool(validation.get("valid", False)),
        }
        OperationalOrchestrationResilienceService._audit(
            db,
            organization_id=organization_id,
            event_type="orchestration.authority.runtime.integrity",
            payload=integrity,
            actor_user_id=actor_user_id,
        )
        return integrity

    @staticmethod
    def _ensure_workflow_incident(
        db: Session,
        *,
        organization_id: str,
        incident_type: str,
        severity: str,
        summary: str,
        details: dict[str, Any],
        ride_id: str | None,
        driver_id: str | None,
    ) -> HealthISFWorkflowIncident:
        row = (
            db.query(HealthISFWorkflowIncident)
            .filter(
                HealthISFWorkflowIncident.organization_id == organization_id,
                HealthISFWorkflowIncident.incident_type == incident_type,
                HealthISFWorkflowIncident.ride_id == ride_id,
                HealthISFWorkflowIncident.driver_id == driver_id,
                HealthISFWorkflowIncident.status.notin_(list(_STATUS_RESOLVED_STATES)),
            )
            .order_by(desc(HealthISFWorkflowIncident.created_at))
            .first()
        )
        if row is not None:
            row.severity = severity
            row.summary = summary
            row.details = json.dumps(details, separators=(",", ":"), sort_keys=True, default=str)
            row.updated_at = now()
            db.commit()
            db.refresh(row)
            return row

        row = HealthISFWorkflowIncident(
            id=str(uuid4()),
            organization_id=organization_id,
            workflow_execution_id=None,
            ride_id=ride_id,
            driver_id=driver_id,
            incident_type=incident_type,
            severity=severity,
            status=WorkflowIncidentStatus.OPEN.value,
            summary=summary,
            details=json.dumps(details, separators=(",", ":"), sort_keys=True, default=str),
            created_at=now(),
            updated_at=now(),
            resolved_at=None,
            escalated_at=None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def _append_alert_chain(
        db: Session,
        *,
        organization_id: str,
        incident_key: str,
        actor_user_id: str | None,
        summary: str,
    ) -> OperationalAlertLog | None:
        alert = (
            db.query(OperationalAlertLog)
            .filter(
                OperationalAlertLog.organization_id == organization_id,
                OperationalAlertLog.incident_key == incident_key,
            )
            .order_by(desc(OperationalAlertLog.created_at))
            .first()
        )
        if alert is None:
            return None
        return OperationalAlertService.escalate_alert(
            db,
            organization_id=organization_id,
            alert_id=alert.id,
            escalated_by_user_id=actor_user_id,
            summary=summary,
        )

    @staticmethod
    def _open_escalation_exists(
        db: Session,
        *,
        organization_id: str,
        incident_id: str,
        target_role: str,
        dedup_minutes: int,
    ) -> bool:
        cutoff = now() - timedelta(minutes=max(1, int(dedup_minutes)))
        row = (
            db.query(HealthISFWorkflowEscalation)
            .filter(
                HealthISFWorkflowEscalation.organization_id == organization_id,
                HealthISFWorkflowEscalation.incident_id == incident_id,
                HealthISFWorkflowEscalation.target_role == target_role,
                HealthISFWorkflowEscalation.created_at >= cutoff,
                HealthISFWorkflowEscalation.status.in_(
                    [
                        WorkflowEscalationStatus.QUEUED.value,
                        WorkflowEscalationStatus.ROUTED.value,
                        WorkflowEscalationStatus.ACKNOWLEDGED.value,
                    ]
                ),
            )
            .first()
        )
        return row is not None

    @staticmethod
    def _next_escalation_level(db: Session, *, organization_id: str, incident_id: str) -> int:
        max_level = (
            db.query(func.max(HealthISFWorkflowEscalation.escalation_level))
            .filter(
                HealthISFWorkflowEscalation.organization_id == organization_id,
                HealthISFWorkflowEscalation.incident_id == incident_id,
            )
            .scalar()
        )
        return int(max_level or 0) + 1

    @staticmethod
    def _resolve_repeated_cancellation_incident(
        db: Session,
        *,
        organization_id: str,
        threshold_count: int,
    ) -> dict[str, Any] | None:
        rides = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.organization_id == organization_id)
            .all()
        )
        now_utc = _as_utc(now())
        cutoff = now_utc - timedelta(hours=1)
        cancelled = [
            row
            for row in rides
            if _status_text(row.status) == RideStatus.CANCELLED.value and _as_utc(row.updated_at) >= cutoff
        ]
        if len(cancelled) < max(1, int(threshold_count)):
            return None

        details = {
            "count_last_hour": len(cancelled),
            "ride_ids": [str(item.id) for item in cancelled[:25]],
            "window_minutes": 60,
        }
        digest = hashlib.sha256(
            f"{organization_id}:repeated_cancellation:{json.dumps(details, sort_keys=True, separators=(',', ':'), default=str)}".encode("utf-8")
        ).hexdigest()[:24]
        return {
            "incident_type": "repeated_cancellation_escalation",
            "incident_key": f"repeated_cancellation_escalation:{digest}",
            "severity": "high" if len(cancelled) >= max(5, threshold_count + 1) else "medium",
            "message": f"Repeated cancellation trend detected ({len(cancelled)} in 60m).",
            "details": details,
            "role_targets": ["dispatcher", "supervisor", "command-center"],
        }

    @staticmethod
    def generate_automated_escalations(
        db: Session,
        *,
        organization_id: str,
        incidents: list[dict[str, Any]],
        actor_user_id: str | None,
    ) -> list[dict[str, Any]]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        if not bool(thresholds.get("automation_enabled", True)):
            return []

        working_incidents = list(incidents)
        repeated_cancel = OperationalOrchestrationResilienceService._resolve_repeated_cancellation_incident(
            db,
            organization_id=organization_id,
            threshold_count=int(thresholds.get("repeated_cancellation_count_1h", 3) or 3),
        )
        if repeated_cancel is not None:
            working_incidents.append(repeated_cancel)

        output: list[dict[str, Any]] = []
        dedup_minutes = int(thresholds.get("escalation_dedup_minutes", 10) or 10)

        for incident in working_incidents:
            incident_type = str(incident.get("incident_type") or "")
            rule = OperationalOrchestrationResilienceService.INCIDENT_ESCALATION_RULES.get(incident_type)
            if rule is None:
                continue

            severity = str(incident.get("severity") or "medium").lower()
            if OperationalOrchestrationResilienceService._severity_rank(severity) < OperationalOrchestrationResilienceService._severity_rank(str(rule.get("min_severity") or "medium")):
                continue

            details = dict(incident.get("details") or {})
            incident_key = str(incident.get("incident_key") or "")
            role_targets = [str(item) for item in (incident.get("role_targets") or []) if str(item)]
            target_role = str(role_targets[0] if role_targets else rule.get("target_role") or "dispatcher")
            dedup_key = f"{incident_key}:{target_role}:{rule.get('escalation_type')}"

            if OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.escalation.generated",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                continue

            ride_id = str((details.get("ride_ids") or [""])[0] or "") or None
            driver_id = str((details.get("driver_ids") or [""])[0] or "") or None
            workflow_incident = OperationalOrchestrationResilienceService._ensure_workflow_incident(
                db,
                organization_id=organization_id,
                incident_type=incident_type,
                severity=severity,
                summary=str(incident.get("message") or incident_type),
                details={
                    "incident_key": incident_key,
                    "incident": incident,
                },
                ride_id=ride_id,
                driver_id=driver_id,
            )

            if OperationalOrchestrationResilienceService._open_escalation_exists(
                db,
                organization_id=organization_id,
                incident_id=str(workflow_incident.id),
                target_role=target_role,
                dedup_minutes=dedup_minutes,
            ):
                continue

            level = OperationalOrchestrationResilienceService._next_escalation_level(
                db,
                organization_id=organization_id,
                incident_id=str(workflow_incident.id),
            )
            escalation = HealthISFWorkflowEscalation(
                id=str(uuid4()),
                organization_id=organization_id,
                workflow_execution_id=None,
                incident_id=str(workflow_incident.id),
                escalation_level=level,
                target_queue=str(rule.get("target_queue") or "operations"),
                target_role=target_role,
                status=WorkflowEscalationStatus.QUEUED.value,
                summary=f"{rule.get('escalation_type')} for {incident_type}",
                details=json.dumps(
                    {
                        "incident_key": incident_key,
                        "dedup_key": dedup_key,
                        "severity": severity,
                        "incident_type": incident_type,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                created_at=now(),
                acknowledged_at=None,
                resolved_at=None,
            )
            db.add(escalation)

            workflow_incident.status = WorkflowIncidentStatus.ACKNOWLEDGED.value
            workflow_incident.escalated_at = now()
            workflow_incident.updated_at = now()
            db.commit()
            db.refresh(escalation)
            db.refresh(workflow_incident)

            OperationalOrchestrationResilienceService._append_alert_chain(
                db,
                organization_id=organization_id,
                incident_key=incident_key,
                actor_user_id=actor_user_id,
                summary=str(rule.get("escalation_type") or "automated_escalation"),
            )

            audit_payload = {
                "dedup_key": dedup_key,
                "incident_type": incident_type,
                "incident_key": incident_key,
                "severity": severity,
                "target_role": target_role,
                "target_queue": escalation.target_queue,
                "escalation_level": level,
                "escalation_id": str(escalation.id),
            }
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.escalation.generated",
                payload=audit_payload,
                actor_user_id=actor_user_id,
                incident_id=str(workflow_incident.id),
                escalation_id=str(escalation.id),
            )

            OperationalSynchronizationEngine.publish_event(
                organization_id=organization_id,
                event_type=OperationalEventType.ESCALATION,
                payload={
                    "incident_type": incident_type,
                    "incident_key": incident_key,
                    "severity": severity,
                    "escalation_level": level,
                    "escalation_id": str(escalation.id),
                    "target_role": target_role,
                    "dedup_key": dedup_key,
                    "automated": True,
                },
                role_scope=list(OperationalOrchestrationResilienceService.CROSS_ROLE_SCOPE),
                source_nonce=f"automation_escalation:{organization_id}:{dedup_key}",
                metadata={"actor_user_id": actor_user_id or "", "source": "operational_orchestration_engine"},
            )

            output.append(
                {
                    "escalation_id": str(escalation.id),
                    "incident_id": str(workflow_incident.id),
                    "incident_type": incident_type,
                    "incident_key": incident_key,
                    "escalation_type": str(rule.get("escalation_type") or "automated_escalation"),
                    "target_role": target_role,
                    "target_queue": escalation.target_queue,
                    "severity": severity,
                    "escalation_level": level,
                    "dedup_key": dedup_key,
                    "generated_at": now().isoformat(),
                }
            )

        return output

    @staticmethod
    def _distance_proxy_miles(
        pickup_lat: float,
        pickup_lng: float,
        driver_lat: float,
        driver_lng: float,
    ) -> float:
        # Lightweight deterministic approximation for short intra-city ranking.
        return (((pickup_lat - driver_lat) ** 2 + (pickup_lng - driver_lng) ** 2) ** 0.5) * 69.0

    @staticmethod
    def generate_dispatch_recommendations(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        if not bool(thresholds.get("automation_enabled", True)):
            return []

        rides = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.organization_id == organization_id)
            .order_by(HealthISFRide.requested_at.asc())
            .all()
        )
        drivers = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == organization_id)
            .all()
        )
        routes = {
            str(item.ride_id): item
            for item in (
                db.query(HealthISFRideRoutePlan)
                .filter(HealthISFRideRoutePlan.organization_id == organization_id)
                .all()
            )
        }

        candidate_rides = [
            row
            for row in rides
            if _status_text(row.status) in {RideStatus.REQUESTED.value, RideStatus.QUEUED.value, RideStatus.PENDING.value, RideStatus.ASSIGNED.value}
        ][: max(1, int(limit))]
        active_drivers = [
            row
            for row in drivers
            if bool(row.is_active)
            and _status_text(row.status) in {DriverStatus.AVAILABLE.value, DriverStatus.ASSIGNED.value}
        ]

        workload_map: dict[str, int] = {}
        for row in rides:
            if row.driver_id and _status_text(row.status) not in _TERMINAL_RIDE_STATES:
                workload_map[str(row.driver_id)] = int(workload_map.get(str(row.driver_id), 0) + 1)

        location_rows = (
            db.query(HealthISFDriverLocationPing)
            .filter(HealthISFDriverLocationPing.organization_id == organization_id)
            .order_by(desc(HealthISFDriverLocationPing.created_at))
            .all()
        )
        latest_location: dict[str, HealthISFDriverLocationPing] = {}
        for row in location_rows:
            driver_id = str(row.driver_id)
            if driver_id not in latest_location:
                latest_location[driver_id] = row

        recommendations: list[dict[str, Any]] = []
        dedup_minutes = int(thresholds.get("recommendation_dedup_minutes", 8) or 8)
        sla_minutes = float(thresholds.get("sla_escalation_minutes", 20) or 20)

        if candidate_rides and not active_drivers:
            dedup_key = f"{organization_id}:queue_pressure_reduction:no_available_drivers:{len(candidate_rides)}"
            if not OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.recommendation.generated",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                recommendation = {
                    "recommendation_type": "queue_pressure_reduction",
                    "ride_id": None,
                    "recommended_driver_id": None,
                    "recommended_driver_name": None,
                    "score": 1.0,
                    "score_breakdown": {
                        "pending_rides": len(candidate_rides),
                        "active_drivers": 0,
                        "reason": "no_available_drivers",
                    },
                    "strategy": [
                        "queue_pressure_reduction",
                        "recovery_reassignment_suggestion",
                    ],
                    "generated_at": now().isoformat(),
                    "dedup_key": dedup_key,
                }
                OperationalOrchestrationResilienceService._audit(
                    db,
                    organization_id=organization_id,
                    event_type="orchestration.recommendation.generated",
                    payload=recommendation,
                    actor_user_id=actor_user_id,
                )
                recommendations.append(recommendation)
            return recommendations

        for ride in candidate_rides:
            if not active_drivers:
                continue

            route = routes.get(str(ride.id))
            pickup_lat = float(route.origin_latitude) if route is not None else 0.0
            pickup_lng = float(route.origin_longitude) if route is not None else 0.0

            ranked: list[tuple[float, HealthISFDriver, dict[str, Any]]] = []
            for driver in active_drivers:
                loc = latest_location.get(str(driver.id))
                if loc is not None and route is not None:
                    distance = OperationalOrchestrationResilienceService._distance_proxy_miles(
                        pickup_lat,
                        pickup_lng,
                        float(loc.latitude),
                        float(loc.longitude),
                    )
                    proximity_score = max(0.0, 1.0 - min(1.0, distance / 15.0))
                else:
                    distance = None
                    proximity_score = 0.5

                workload = float(workload_map.get(str(driver.id), 0))
                workload_score = max(0.0, 1.0 - min(1.0, workload / 4.0))
                utilization_score = max(0.0, 1.0 - min(1.0, float(driver.total_trips or 0) / 500.0))
                ride_age = _minutes_since(ride.requested_at)
                sla_risk = min(1.0, max(0.0, ride_age / max(1.0, sla_minutes)))

                total_score = round(
                    (proximity_score * 0.45) + (workload_score * 0.25) + (utilization_score * 0.15) + (sla_risk * 0.15),
                    6,
                )
                ranked.append(
                    (
                        total_score,
                        driver,
                        {
                            "distance_proxy_miles": distance,
                            "proximity_score": round(proximity_score, 6),
                            "workload_score": round(workload_score, 6),
                            "utilization_score": round(utilization_score, 6),
                            "sla_risk_score": round(sla_risk, 6),
                            "open_workload": int(workload),
                        },
                    )
                )

            ranked.sort(key=lambda item: item[0], reverse=True)
            best_score, best_driver, score_breakdown = ranked[0]

            recommendation_type = "nearest_qualified_driver_recommendation"
            if ride.driver_id and str(ride.driver_id) != str(best_driver.id):
                recommendation_type = "recovery_reassignment_suggestion"
            elif _minutes_since(ride.requested_at) >= sla_minutes:
                recommendation_type = "sla_risk_aware_dispatching"
            elif float(score_breakdown.get("open_workload", 0.0) or 0.0) > 1.0:
                recommendation_type = "workload_balanced_assignment_recommendation"

            dedup_key = f"{organization_id}:{recommendation_type}:{ride.id}:{best_driver.id}"
            if OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.recommendation.generated",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                continue

            recommendation = {
                "recommendation_type": recommendation_type,
                "ride_id": str(ride.id),
                "recommended_driver_id": str(best_driver.id),
                "recommended_driver_name": str(best_driver.name),
                "score": float(best_score),
                "score_breakdown": score_breakdown,
                "strategy": [
                    "nearest_qualified_driver_recommendation",
                    "workload_balanced_assignment_recommendation",
                    "sla_risk_aware_dispatching",
                    "driver_utilization_balancing",
                    "queue_pressure_reduction",
                ],
                "generated_at": now().isoformat(),
                "dedup_key": dedup_key,
            }

            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.recommendation.generated",
                payload=recommendation,
                actor_user_id=actor_user_id,
            )

            OperationalSynchronizationEngine.publish_event(
                organization_id=organization_id,
                event_type=OperationalEventType.DISPATCH_RECOMMENDATION,
                payload={
                    "ride_id": recommendation["ride_id"],
                    "recommended_driver_id": recommendation["recommended_driver_id"],
                    "recommendation_type": recommendation_type,
                    "score": recommendation["score"],
                    "score_breakdown": recommendation["score_breakdown"],
                    "dedup_key": dedup_key,
                    "automated": True,
                },
                role_scope=list(OperationalOrchestrationResilienceService.CROSS_ROLE_SCOPE),
                source_nonce=f"automation_recommendation:{dedup_key}",
                metadata={"actor_user_id": actor_user_id or "", "source": "operational_orchestration_engine"},
            )

            recommendations.append(recommendation)

        pending_count = len(candidate_rides)
        available_count = len(active_drivers)
        overload_ratio = float(pending_count) / max(1.0, float(available_count))
        if pending_count >= 1 and overload_ratio >= float(thresholds.get("dispatcher_overload_ratio", 2.0) or 2.0):
            dedup_key = f"{organization_id}:queue_pressure_reduction:{pending_count}:{available_count}"
            if not OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.recommendation.generated",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                recommendation = {
                    "recommendation_type": "queue_pressure_reduction",
                    "ride_id": None,
                    "recommended_driver_id": None,
                    "recommended_driver_name": None,
                    "score": round(min(1.0, overload_ratio / 4.0), 6),
                    "score_breakdown": {
                        "pending_rides": pending_count,
                        "active_drivers": available_count,
                        "overload_ratio": round(overload_ratio, 6),
                    },
                    "strategy": ["queue_pressure_reduction"],
                    "generated_at": now().isoformat(),
                    "dedup_key": dedup_key,
                }
                OperationalOrchestrationResilienceService._audit(
                    db,
                    organization_id=organization_id,
                    event_type="orchestration.recommendation.generated",
                    payload=recommendation,
                    actor_user_id=actor_user_id,
                )
                recommendations.append(recommendation)

        return recommendations

    @staticmethod
    def generate_predictive_sla_risk_engine(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        incidents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        if not bool(thresholds.get("automation_enabled", True)):
            return []

        rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id).all()
        drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == organization_id).all()
        routes = {
            str(item.ride_id): item
            for item in (
                db.query(HealthISFRideRoutePlan)
                .filter(HealthISFRideRoutePlan.organization_id == organization_id)
                .all()
            )
        }

        active_rides = [row for row in rides if _status_text(row.status) not in _TERMINAL_RIDE_STATES]
        pending_rides = [
            row
            for row in rides
            if _status_text(row.status)
            in {
                RideStatus.REQUESTED.value,
                RideStatus.QUEUED.value,
                RideStatus.PENDING.value,
                RideStatus.ASSIGNED.value,
            }
        ]
        enroute_rides = [
            row
            for row in rides
            if _status_text(row.status)
            in {
                RideStatus.ASSIGNED.value,
                RideStatus.DRIVER_EN_ROUTE.value,
                RideStatus.ACCEPTED.value,
            }
        ]
        active_drivers = [
            row
            for row in drivers
            if bool(row.is_active)
            and _status_text(row.status) in {DriverStatus.AVAILABLE.value, DriverStatus.ASSIGNED.value}
        ]

        ws_stats = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
        window_minutes = int(thresholds.get("predictive_window_minutes", 60) or 60)
        dedup_minutes = int(thresholds.get("predictive_forecast_dedup_minutes", 8) or 8)
        sla_minutes = float(thresholds.get("sla_escalation_minutes", 20) or 20)
        queue_ratio = float(len(pending_rides)) / max(1.0, float(len(active_drivers)))
        dispatcher_load_ratio = float(len(active_rides)) / max(1.0, float(len(active_drivers)))

        pending_ages = [_minutes_since(item.requested_at) for item in pending_rides]
        near_breach_count = sum(1 for age in pending_ages if age >= sla_minutes * 0.75)
        avg_pending_age = sum(pending_ages) / max(1, len(pending_ages))
        sla_breach_risk = OperationalOrchestrationResilienceService._bounded(
            ((near_breach_count / max(1, len(pending_rides))) * 0.65) + ((avg_pending_age / max(1.0, sla_minutes)) * 0.35)
        )

        arrival_delay_values: list[float] = []
        for ride in enroute_rides:
            route = routes.get(str(ride.id))
            expected = float(route.estimated_duration_minutes) if route is not None else float(ride.estimated_duration_minutes or 0)
            if expected <= 0:
                continue
            elapsed = _minutes_since(ride.accepted_at or ride.requested_at)
            arrival_delay_values.append(max(0.0, (elapsed - expected) / max(1.0, expected)))
        arrival_delay_risk = OperationalOrchestrationResilienceService._bounded(
            sum(arrival_delay_values) / max(1, len(arrival_delay_values))
        )

        queue_pressure_risk = OperationalOrchestrationResilienceService._bounded(
            queue_ratio / max(1.0, float(thresholds.get("dispatcher_overload_ratio", 2.0) or 2.0))
        )
        overload_risk = OperationalOrchestrationResilienceService._bounded(
            dispatcher_load_ratio / max(1.0, float(thresholds.get("dispatcher_overload_projection_threshold", 2.3) or 2.3))
        )
        driver_shortage_risk = OperationalOrchestrationResilienceService._bounded(
            max(0.0, float(len(pending_rides) - len(active_drivers))) / max(1.0, float(len(pending_rides) or 1))
        )
        reconnect_risk = OperationalOrchestrationResilienceService._bounded(
            float(int(ws_stats.get("disconnects_last_5m", 0) or 0))
            / max(1.0, float(thresholds.get("reconnect_failure_disconnects_5m", 4) or 4))
        )

        incident_pressure = sum(1 for item in incidents if str(item.get("severity") or "").lower() in {"high", "critical"})

        forecast_specs = [
            {
                "prediction_type": "predicted_pickup_sla_breach",
                "risk_score": sla_breach_risk,
                "threshold": float(thresholds.get("predicted_sla_breach_risk_threshold", 0.6) or 0.6),
                "projected_value": round(avg_pending_age, 3),
                "projected_unit": "minutes",
                "evidence": {
                    "near_breach_count": int(near_breach_count),
                    "pending_rides": len(pending_rides),
                    "sla_minutes": sla_minutes,
                },
            },
            {
                "prediction_type": "predicted_arrival_delay",
                "risk_score": arrival_delay_risk,
                "threshold": float(thresholds.get("predicted_arrival_delay_risk_threshold", 0.58) or 0.58),
                "projected_value": round(arrival_delay_risk * 100.0, 3),
                "projected_unit": "delay_percent",
                "evidence": {"evaluated_enroute_rides": len(arrival_delay_values)},
            },
            {
                "prediction_type": "escalating_queue_pressure",
                "risk_score": queue_pressure_risk,
                "threshold": float(thresholds.get("queue_pressure_risk_threshold", 0.6) or 0.6),
                "projected_value": round(queue_ratio, 3),
                "projected_unit": "pending_per_driver",
                "evidence": {"pending_rides": len(pending_rides), "active_drivers": len(active_drivers)},
            },
            {
                "prediction_type": "projected_dispatcher_overload",
                "risk_score": overload_risk,
                "threshold": 0.55,
                "projected_value": round(dispatcher_load_ratio, 3),
                "projected_unit": "active_rides_per_active_driver",
                "evidence": {"active_rides": len(active_rides), "active_drivers": len(active_drivers)},
            },
            {
                "prediction_type": "projected_driver_shortage",
                "risk_score": driver_shortage_risk,
                "threshold": float(thresholds.get("driver_shortage_projection_threshold", 0.35) or 0.35),
                "projected_value": max(0, int(len(pending_rides) - len(active_drivers))),
                "projected_unit": "drivers",
                "evidence": {"pending_rides": len(pending_rides), "active_drivers": len(active_drivers)},
            },
            {
                "prediction_type": "projected_reconnect_instability",
                "risk_score": reconnect_risk,
                "threshold": float(thresholds.get("reconnect_instability_risk_threshold", 0.55) or 0.55),
                "projected_value": int(ws_stats.get("disconnects_last_5m", 0) or 0),
                "projected_unit": "disconnects_5m",
                "evidence": {
                    "disconnects_last_5m": int(ws_stats.get("disconnects_last_5m", 0) or 0),
                    "high_severity_incident_count": int(incident_pressure),
                },
            },
        ]

        forecasts: list[dict[str, Any]] = []
        for spec in forecast_specs:
            confidence = OperationalOrchestrationResilienceService._bounded(
                (0.45 * float(spec["risk_score"]))
                + (0.35 * min(1.0, float(len(active_rides)) / 40.0))
                + (0.2 * min(1.0, float(incident_pressure) / 4.0))
            )
            threshold = float(spec["threshold"])
            dedup_key = (
                f"{organization_id}:{spec['prediction_type']}:"
                f"{int(float(spec['risk_score']) * 100)}:{int(confidence * 100)}:{window_minutes}"
            )
            if OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.prediction.generated",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                continue

            payload = {
                "prediction_type": str(spec["prediction_type"]),
                "risk_score": round(float(spec["risk_score"]), 6),
                "threshold": round(threshold, 6),
                "threshold_exceeded": bool(float(spec["risk_score"]) >= threshold),
                "confidence": round(confidence, 6),
                "projected_value": spec["projected_value"],
                "projected_unit": spec["projected_unit"],
                "rolling_window_minutes": int(window_minutes),
                "evidence": dict(spec.get("evidence") or {}),
                "dedup_key": dedup_key,
                "generated_at": now().isoformat(),
            }
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.prediction.generated",
                payload=payload,
                actor_user_id=actor_user_id,
            )
            OperationalOrchestrationResilienceService._emit_predictive_sync(
                organization_id=organization_id,
                payload=payload,
                source_nonce=f"predictive_forecast:{dedup_key}",
                actor_user_id=actor_user_id,
            )
            forecasts.append(payload)

        return forecasts

    @staticmethod
    def generate_driver_reliability_intelligence(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
    ) -> list[dict[str, Any]]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        reliability_window_days = int(thresholds.get("driver_reliability_window_days", 14) or 14)
        cutoff = now() - timedelta(days=max(1, reliability_window_days))
        dedup_minutes = int(thresholds.get("predictive_forecast_dedup_minutes", 8) or 8)

        drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == organization_id).all()
        rides = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.organization_id == organization_id, HealthISFRide.created_at >= cutoff)
            .all()
        )
        assignments = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.organization_id == organization_id, HealthISFDispatchAssignment.created_at >= cutoff)
            .all()
        )
        latest_location_rows = (
            db.query(HealthISFDriverLocationPing)
            .filter(HealthISFDriverLocationPing.organization_id == organization_id)
            .order_by(desc(HealthISFDriverLocationPing.created_at))
            .all()
        )
        latest_location_by_driver: dict[str, HealthISFDriverLocationPing] = {}
        for row in latest_location_rows:
            driver_id = str(row.driver_id)
            if driver_id not in latest_location_by_driver:
                latest_location_by_driver[driver_id] = row

        rides_by_driver: dict[str, list[HealthISFRide]] = {}
        for row in rides:
            if row.driver_id:
                rides_by_driver.setdefault(str(row.driver_id), []).append(row)
        assignments_by_driver: dict[str, list[HealthISFDispatchAssignment]] = {}
        for row in assignments:
            if row.driver_id:
                assignments_by_driver.setdefault(str(row.driver_id), []).append(row)

        snapshots: list[dict[str, Any]] = []
        for driver in drivers:
            driver_id = str(driver.id)
            d_rides = rides_by_driver.get(driver_id, [])
            d_assignments = assignments_by_driver.get(driver_id, [])

            completed = sum(1 for item in d_rides if _status_text(item.status) == RideStatus.COMPLETED.value)
            cancelled = sum(1 for item in d_rides if _status_text(item.status) == RideStatus.CANCELLED.value)
            failed = sum(1 for item in d_rides if _status_text(item.status) == RideStatus.FAILED.value)
            late_arrivals = sum(1 for item in d_rides if _minutes_since(item.requested_at) >= float(thresholds.get("delayed_pickup_minutes", 25) or 25))

            offered = sum(1 for item in d_assignments if item.offered_at is not None)
            accepted = sum(1 for item in d_assignments if item.accepted_at is not None)
            response_latencies = [
                max(0.0, (_as_utc(item.accepted_at) - _as_utc(item.offered_at)).total_seconds() / 60.0)
                for item in d_assignments
                if item.offered_at is not None and item.accepted_at is not None
            ]
            avg_response_minutes = sum(response_latencies) / max(1, len(response_latencies))

            latest_ping = latest_location_by_driver.get(driver_id)
            ping_age_minutes = _minutes_since(latest_ping.created_at) if latest_ping is not None else float(thresholds.get("inactive_driver_minutes", 15) or 15) * 2.0

            late_arrival_frequency = OperationalOrchestrationResilienceService._bounded(late_arrivals / max(1.0, float(len(d_rides) or 1)))
            cancellation_patterns = OperationalOrchestrationResilienceService._bounded(cancelled / max(1.0, float(len(d_rides) or 1)))
            reconnect_instability = OperationalOrchestrationResilienceService._bounded(
                ping_age_minutes / max(1.0, float(thresholds.get("inactive_driver_minutes", 15) or 15))
            )
            assignment_acceptance_reliability = OperationalOrchestrationResilienceService._bounded(accepted / max(1.0, float(offered or 1)))
            trip_completion_consistency = OperationalOrchestrationResilienceService._bounded(
                completed / max(1.0, float(completed + cancelled + failed or 1))
            )
            operational_responsiveness = OperationalOrchestrationResilienceService._bounded(
                1.0 - (avg_response_minutes / 20.0)
            )

            reliability_score = OperationalOrchestrationResilienceService._bounded(
                (0.22 * (1.0 - late_arrival_frequency))
                + (0.18 * (1.0 - cancellation_patterns))
                + (0.15 * (1.0 - reconnect_instability))
                + (0.2 * assignment_acceptance_reliability)
                + (0.15 * trip_completion_consistency)
                + (0.1 * operational_responsiveness)
            )

            payload = {
                "driver_id": driver_id,
                "driver_name": str(driver.name),
                "rolling_window_days": reliability_window_days,
                "late_arrival_frequency": round(late_arrival_frequency, 6),
                "cancellation_patterns": round(cancellation_patterns, 6),
                "reconnect_instability": round(reconnect_instability, 6),
                "assignment_acceptance_reliability": round(assignment_acceptance_reliability, 6),
                "trip_completion_consistency": round(trip_completion_consistency, 6),
                "operational_responsiveness": round(operational_responsiveness, 6),
                "reliability_score": round(reliability_score, 6),
                "confidence": round(
                    OperationalOrchestrationResilienceService._bounded(
                        0.35 + (0.45 * min(1.0, float(len(d_rides)) / 12.0)) + (0.2 * min(1.0, float(offered) / 10.0))
                    ),
                    6,
                ),
                "generated_at": now().isoformat(),
            }

            dedup_key = f"{organization_id}:driver_reliability:{driver_id}:{int(payload['reliability_score'] * 100)}"
            payload["dedup_key"] = dedup_key
            if OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.reliability.driver",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                snapshots.append(payload)
                continue

            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.reliability.driver",
                payload=payload,
                actor_user_id=actor_user_id,
            )
            OperationalOrchestrationResilienceService._emit_predictive_sync(
                organization_id=organization_id,
                payload={"driver_reliability": payload},
                source_nonce=f"driver_reliability:{dedup_key}",
                actor_user_id=actor_user_id,
            )
            snapshots.append(payload)

        snapshots.sort(key=lambda item: float(item.get("reliability_score", 0.0) or 0.0), reverse=True)
        return snapshots

    @staticmethod
    def generate_rider_operational_risk_detection(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
    ) -> list[dict[str, Any]]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        window_days = int(thresholds.get("rider_risk_window_days", 30) or 30)
        cutoff = now() - timedelta(days=max(1, window_days))
        dedup_minutes = int(thresholds.get("predictive_forecast_dedup_minutes", 8) or 8)

        rides = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.organization_id == organization_id, HealthISFRide.created_at >= cutoff)
            .all()
        )
        grouped: dict[str, list[HealthISFRide]] = {}
        for row in rides:
            rider_key = str(row.passenger_phone or "").strip() or str(row.passenger_name or "").strip().lower()
            if not rider_key:
                continue
            grouped.setdefault(rider_key, []).append(row)

        payloads: list[dict[str, Any]] = []
        for rider_key, items in grouped.items():
            if len(items) < 2:
                continue
            total = len(items)
            cancelled = sum(1 for row in items if _status_text(row.status) == RideStatus.CANCELLED.value)
            failed = sum(1 for row in items if _status_text(row.status) == RideStatus.FAILED.value)
            delayed = sum(1 for row in items if _minutes_since(row.requested_at) >= float(thresholds.get("delayed_pickup_minutes", 25) or 25))
            support_level = sum(
                1
                for row in items
                if str(row.service_type or "").lower() in {"wheelchair", "stretcher", "critical_care", "medical_transport"}
                or bool(row.is_emergency)
            )

            sorted_items = sorted(items, key=lambda row: _as_utc(row.appointment_time or row.requested_at))
            scheduling_conflicts = 0
            for idx in range(1, len(sorted_items)):
                prev = _as_utc(sorted_items[idx - 1].appointment_time or sorted_items[idx - 1].requested_at)
                cur = _as_utc(sorted_items[idx].appointment_time or sorted_items[idx].requested_at)
                if (cur - prev).total_seconds() <= 90 * 60:
                    scheduling_conflicts += 1

            repeated_no_show_likelihood = OperationalOrchestrationResilienceService._bounded(failed / max(1.0, float(total)))
            repeated_cancellation_likelihood = OperationalOrchestrationResilienceService._bounded(cancelled / max(1.0, float(total)))
            chronic_delay_patterns = OperationalOrchestrationResilienceService._bounded(delayed / max(1.0, float(total)))
            high_support_risk = OperationalOrchestrationResilienceService._bounded(support_level / max(1.0, float(total)))
            recurring_scheduling_conflict = OperationalOrchestrationResilienceService._bounded(
                scheduling_conflicts / max(1.0, float(total - 1))
            )

            risk_score = OperationalOrchestrationResilienceService._bounded(
                (0.24 * repeated_no_show_likelihood)
                + (0.24 * repeated_cancellation_likelihood)
                + (0.2 * chronic_delay_patterns)
                + (0.16 * high_support_risk)
                + (0.16 * recurring_scheduling_conflict)
            )

            if risk_score < 0.35:
                continue

            payload = {
                "rider_key": rider_key,
                "rolling_window_days": window_days,
                "repeated_no_show_likelihood": round(repeated_no_show_likelihood, 6),
                "repeated_cancellation_likelihood": round(repeated_cancellation_likelihood, 6),
                "chronic_delay_patterns": round(chronic_delay_patterns, 6),
                "high_support_transportation_risk": round(high_support_risk, 6),
                "recurring_scheduling_conflict_detection": round(recurring_scheduling_conflict, 6),
                "risk_score": round(risk_score, 6),
                "confidence": round(
                    OperationalOrchestrationResilienceService._bounded(0.4 + min(0.6, float(total) / 15.0)),
                    6,
                ),
                "sample_size": total,
                "generated_at": now().isoformat(),
            }
            dedup_key = f"{organization_id}:rider_risk:{hashlib.sha256(rider_key.encode('utf-8')).hexdigest()[:10]}:{int(risk_score * 100)}"
            payload["dedup_key"] = dedup_key

            if OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.rider_risk.detected",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                payloads.append(payload)
                continue

            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.rider_risk.detected",
                payload=payload,
                actor_user_id=actor_user_id,
            )
            OperationalOrchestrationResilienceService._emit_predictive_sync(
                organization_id=organization_id,
                payload={"rider_risk": payload},
                source_nonce=f"rider_risk:{dedup_key}",
                actor_user_id=actor_user_id,
            )
            payloads.append(payload)

        payloads.sort(key=lambda item: float(item.get("risk_score", 0.0) or 0.0), reverse=True)
        return payloads

    @staticmethod
    def generate_regional_mobility_intelligence(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        incidents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        window_minutes = int(thresholds.get("predictive_window_minutes", 60) or 60)
        cutoff = now() - timedelta(minutes=max(15, window_minutes))
        dedup_minutes = int(thresholds.get("predictive_forecast_dedup_minutes", 8) or 8)

        rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id).all()
        routes = {
            str(item.ride_id): item
            for item in (
                db.query(HealthISFRideRoutePlan)
                .filter(HealthISFRideRoutePlan.organization_id == organization_id)
                .all()
            )
        }
        location_rows = (
            db.query(HealthISFDriverLocationPing)
            .filter(HealthISFDriverLocationPing.organization_id == organization_id)
            .order_by(desc(HealthISFDriverLocationPing.created_at))
            .all()
        )
        latest_location_by_driver: dict[str, HealthISFDriverLocationPing] = {}
        for row in location_rows:
            driver_id = str(row.driver_id)
            if driver_id not in latest_location_by_driver:
                latest_location_by_driver[driver_id] = row

        demand_by_region: dict[str, int] = {}
        congestion_by_region: dict[str, list[float]] = {}
        sla_late_by_region: dict[str, int] = {}
        total_by_region: dict[str, int] = {}
        rides_by_id = {str(item.id): item for item in rides}
        for ride in rides:
            region = OperationalOrchestrationResilienceService._region_key_for_ride(ride, routes.get(str(ride.id)))
            total_by_region[region] = int(total_by_region.get(region, 0) + 1)
            if _as_utc(ride.requested_at) >= _as_utc(cutoff):
                demand_by_region[region] = int(demand_by_region.get(region, 0) + 1)
            route = routes.get(str(ride.id))
            if route is not None:
                congestion_by_region.setdefault(region, []).append(float(route.traffic_multiplier or 1.0))
            if _minutes_since(ride.requested_at) >= float(thresholds.get("delayed_pickup_minutes", 25) or 25):
                sla_late_by_region[region] = int(sla_late_by_region.get(region, 0) + 1)

        driver_by_region: dict[str, int] = {}
        for row in latest_location_by_driver.values():
            region = f"geo:{round(float(row.latitude), 2)}:{round(float(row.longitude), 2)}"
            driver_by_region[region] = int(driver_by_region.get(region, 0) + 1)

        incident_cluster: dict[str, int] = {}
        for incident in incidents:
            details = dict(incident.get("details") or {})
            ride_ids = [str(item) for item in (details.get("ride_ids") or []) if str(item)]
            mapped = False
            for ride_id in ride_ids:
                ride = rides_by_id.get(ride_id)
                if ride is None:
                    continue
                region = OperationalOrchestrationResilienceService._region_key_for_ride(ride, routes.get(str(ride.id)))
                incident_cluster[region] = int(incident_cluster.get(region, 0) + 1)
                mapped = True
            if not mapped and demand_by_region:
                largest_region = max(demand_by_region.items(), key=lambda item: item[1])[0]
                incident_cluster[largest_region] = int(incident_cluster.get(largest_region, 0) + 1)

        regions = set(total_by_region) | set(driver_by_region)
        forecasts: list[dict[str, Any]] = []
        for region in regions:
            demand = int(demand_by_region.get(region, 0) or 0)
            drivers = int(driver_by_region.get(region, 0) or 0)
            congestion_pressure = OperationalOrchestrationResilienceService._bounded(
                (sum(congestion_by_region.get(region, [1.0])) / max(1, len(congestion_by_region.get(region, [1.0])))) - 1.0
            )
            area_driver_imbalance = OperationalOrchestrationResilienceService._bounded(
                max(0.0, float(demand - drivers)) / max(1.0, float(demand or 1))
            )
            regional_sla_degradation_risk = OperationalOrchestrationResilienceService._bounded(
                float(sla_late_by_region.get(region, 0) or 0) / max(1.0, float(total_by_region.get(region, 0) or 1))
            )
            hotspot_demand_prediction = OperationalOrchestrationResilienceService._bounded(float(demand) / 12.0)
            coverage_gap = bool(demand > drivers)
            incident_clustering = int(incident_cluster.get(region, 0) or 0)
            risk_score = OperationalOrchestrationResilienceService._bounded(
                (0.2 * congestion_pressure)
                + (0.25 * area_driver_imbalance)
                + (0.2 * regional_sla_degradation_risk)
                + (0.2 * hotspot_demand_prediction)
                + (0.15 * min(1.0, incident_clustering / 4.0))
            )

            payload = {
                "region_key": region,
                "rolling_window_minutes": window_minutes,
                "congestion_pressure_analysis": round(congestion_pressure, 6),
                "area_level_driver_imbalance": round(area_driver_imbalance, 6),
                "regional_sla_degradation_risk": round(regional_sla_degradation_risk, 6),
                "hotspot_demand_prediction": round(hotspot_demand_prediction, 6),
                "transportation_coverage_gaps": coverage_gap,
                "active_operational_incident_clustering": int(incident_clustering),
                "demand": demand,
                "drivers": drivers,
                "risk_score": round(risk_score, 6),
                "confidence": round(
                    OperationalOrchestrationResilienceService._bounded(
                        0.4 + min(0.4, float(total_by_region.get(region, 0) or 0) / 20.0) + min(0.2, float(demand) / 20.0)
                    ),
                    6,
                ),
                "generated_at": now().isoformat(),
            }
            dedup_key = f"{organization_id}:regional:{hashlib.sha256(region.encode('utf-8')).hexdigest()[:10]}:{int(risk_score * 100)}"
            payload["dedup_key"] = dedup_key

            if OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.regional.forecast",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                forecasts.append(payload)
                continue

            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.regional.forecast",
                payload=payload,
                actor_user_id=actor_user_id,
            )
            OperationalOrchestrationResilienceService._emit_predictive_sync(
                organization_id=organization_id,
                payload={"regional_mobility_intelligence": payload},
                source_nonce=f"regional_forecast:{dedup_key}",
                actor_user_id=actor_user_id,
            )
            forecasts.append(payload)

        forecasts.sort(key=lambda item: float(item.get("risk_score", 0.0) or 0.0), reverse=True)
        return forecasts

    @staticmethod
    def generate_predictive_recovery_coordination(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        forecasts: list[dict[str, Any]],
        driver_reliability: list[dict[str, Any]],
        regional_forecasts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        dedup_minutes = int(thresholds.get("predictive_recovery_dedup_minutes", 8) or 8)

        rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id).all()
        reliability_map = {
            str(item.get("driver_id") or ""): float(item.get("reliability_score", 0.0) or 0.0)
            for item in driver_reliability
            if str(item.get("driver_id") or "")
        }
        forecast_by_type = {str(item.get("prediction_type") or ""): item for item in forecasts}

        actions: list[dict[str, Any]] = []

        sla_forecast = forecast_by_type.get("predicted_pickup_sla_breach")
        if sla_forecast and bool(sla_forecast.get("threshold_exceeded")):
            candidates = [
                row
                for row in rides
                if _status_text(row.status)
                in {
                    RideStatus.REQUESTED.value,
                    RideStatus.PENDING.value,
                    RideStatus.ASSIGNED.value,
                }
                and _minutes_since(row.requested_at) >= float(thresholds.get("sla_escalation_minutes", 20) or 20) * 0.75
            ]
            if candidates:
                ride = sorted(candidates, key=lambda item: _minutes_since(item.requested_at), reverse=True)[0]
                driver_score = reliability_map.get(str(ride.driver_id), 0.5) if ride.driver_id else 0.5
                payload = {
                    "operation_type": "preemptive_reassignment_recommendation",
                    "ride_id": str(ride.id),
                    "current_driver_id": str(ride.driver_id) if ride.driver_id else None,
                    "current_driver_reliability": round(float(driver_score), 6),
                    "reason": "predicted_sla_breach",
                    "priority": "high",
                    "generated_at": now().isoformat(),
                }
                payload["dedup_key"] = f"{organization_id}:predictive_reassignment:{ride.id}:{int(float(sla_forecast.get('risk_score', 0.0)) * 100)}"
                actions.append(payload)

        overload = forecast_by_type.get("projected_dispatcher_overload")
        if overload and bool(overload.get("threshold_exceeded")):
            payload = {
                "operation_type": "projected_overload_mitigation",
                "action": "dispatch_pool_sharding",
                "reason": "projected_dispatcher_overload",
                "projected_value": overload.get("projected_value"),
                "priority": "high",
                "generated_at": now().isoformat(),
                "dedup_key": f"{organization_id}:overload_mitigation:{int(float(overload.get('risk_score', 0.0)) * 100)}",
            }
            actions.append(payload)

        queue_forecast = forecast_by_type.get("escalating_queue_pressure")
        if queue_forecast and bool(queue_forecast.get("threshold_exceeded")):
            payload = {
                "operation_type": "queue_balancing_before_sla_breach",
                "action": "rebalance_pending_queue",
                "reason": "escalating_queue_pressure",
                "projected_value": queue_forecast.get("projected_value"),
                "priority": "medium",
                "generated_at": now().isoformat(),
                "dedup_key": f"{organization_id}:queue_balancing:{int(float(queue_forecast.get('risk_score', 0.0)) * 100)}",
            }
            actions.append(payload)

        reconnect = forecast_by_type.get("projected_reconnect_instability")
        if reconnect and bool(reconnect.get("threshold_exceeded")):
            payload = {
                "operation_type": "resilience_preparation_before_degradation_state",
                "action": "prewarm_reconnect_replay_buffers",
                "reason": "projected_reconnect_instability",
                "projected_value": reconnect.get("projected_value"),
                "priority": "high",
                "generated_at": now().isoformat(),
                "dedup_key": f"{organization_id}:resilience_prep:{int(float(reconnect.get('risk_score', 0.0)) * 100)}",
            }
            actions.append(payload)

        highest_region = regional_forecasts[0] if regional_forecasts else None
        if highest_region and bool(highest_region.get("transportation_coverage_gaps")):
            payload = {
                "operation_type": "proactive_driver_redistribution",
                "action": "shift_available_driver_supply",
                "region_key": str(highest_region.get("region_key") or "unknown_region"),
                "reason": "transportation_coverage_gap",
                "priority": "medium",
                "generated_at": now().isoformat(),
                "dedup_key": f"{organization_id}:driver_redistribution:{hashlib.sha256(str(highest_region.get('region_key')).encode('utf-8')).hexdigest()[:10]}:{int(float(highest_region.get('risk_score', 0.0)) * 100)}",
            }
            actions.append(payload)

        emitted: list[dict[str, Any]] = []
        for payload in actions:
            dedup_key = str(payload.get("dedup_key") or "")
            if OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.recovery.proactive",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                emitted.append(payload)
                continue

            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.recovery.proactive",
                payload=payload,
                actor_user_id=actor_user_id,
            )

            OperationalSynchronizationEngine.publish_event(
                organization_id=organization_id,
                event_type=OperationalEventType.COORDINATION_RECOMMENDATION,
                payload={**payload, "predictive": True, "automated": True},
                role_scope=list(OperationalOrchestrationResilienceService.CROSS_ROLE_SCOPE),
                source_nonce=f"predictive_recovery:{dedup_key}",
                metadata={"actor_user_id": actor_user_id or "", "source": "operational_predictive_intelligence"},
            )
            emitted.append(payload)

        return emitted

    @staticmethod
    def build_autonomous_decision_candidates(
        *,
        organization_id: str,
        escalations: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        recovery_operations: list[dict[str, Any]],
        predictive_recovery: list[dict[str, Any]],
        forecasts: list[dict[str, Any]],
        resilience_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        forecast_map = {str(item.get("prediction_type") or ""): item for item in forecasts}
        state = str(resilience_state.get("state") or "healthy")
        candidates: list[dict[str, Any]] = []

        for item in escalations[:50]:
            confidence = OperationalOrchestrationResilienceService._bounded(
                0.55 + (0.15 * float(OperationalOrchestrationResilienceService._severity_rank(str(item.get("severity") or "medium")) / 4.0))
            )
            dedup_key = f"{organization_id}:auto_escalation:{item.get('dedup_key') or item.get('escalation_id') or ''}"
            candidates.append(
                {
                    "decision_type": "automated_escalation_execution",
                    "priority_score": 0.9,
                    "confidence": confidence,
                    "risk_score": confidence,
                    "dedup_key": dedup_key,
                    "payload": dict(item),
                    "ride_id": item.get("ride_id"),
                    "requires_rollback_record": False,
                }
            )

        for item in recommendations[:80]:
            decision_type = "automated_queue_balancing_decision"
            if str(item.get("recommendation_type") or "") in {
                "recovery_reassignment_suggestion",
                "nearest_qualified_driver_recommendation",
                "sla_risk_aware_dispatching",
            }:
                decision_type = "automated_reassignment_execution"
            confidence = OperationalOrchestrationResilienceService._decision_confidence(item)
            candidates.append(
                {
                    "decision_type": decision_type,
                    "priority_score": float(item.get("score", 0.0) or 0.0),
                    "confidence": confidence,
                    "risk_score": float(item.get("score", 0.0) or 0.0),
                    "dedup_key": f"{organization_id}:auto_decision:{item.get('dedup_key') or ''}:{decision_type}",
                    "payload": dict(item),
                    "ride_id": item.get("ride_id"),
                    "requires_rollback_record": decision_type == "automated_reassignment_execution",
                }
            )

        for item in predictive_recovery[:50]:
            op_type = str(item.get("operation_type") or "")
            decision_type = "automated_recovery_workflow_activation"
            if op_type == "projected_overload_mitigation":
                decision_type = "automated_overload_mitigation"
            elif op_type == "resilience_preparation_before_degradation_state":
                decision_type = "automated_degraded_state_stabilization_action"
            confidence = OperationalOrchestrationResilienceService._decision_confidence(item)
            candidates.append(
                {
                    "decision_type": decision_type,
                    "priority_score": confidence,
                    "confidence": confidence,
                    "risk_score": float(item.get("projected_value", 0.0) or 0.0),
                    "dedup_key": f"{organization_id}:predictive_autonomy:{item.get('dedup_key') or op_type}",
                    "payload": dict(item),
                    "ride_id": item.get("ride_id"),
                    "requires_rollback_record": decision_type in {"automated_overload_mitigation", "automated_reassignment_execution"},
                }
            )

        for item in recovery_operations[:40]:
            candidates.append(
                {
                    "decision_type": "automated_recovery_workflow_activation",
                    "priority_score": 0.72,
                    "confidence": 0.72,
                    "risk_score": 0.72,
                    "dedup_key": f"{organization_id}:recovery_activation:{item.get('dedup_key') or item.get('operation_type')}",
                    "payload": dict(item),
                    "ride_id": item.get("ride_id"),
                    "requires_rollback_record": False,
                }
            )

        reconnect = forecast_map.get("projected_reconnect_instability")
        if reconnect and bool(reconnect.get("threshold_exceeded")) and state in {"degraded", "critical", "synchronization_risk", "replay_repair"}:
            confidence = OperationalOrchestrationResilienceService._decision_confidence(reconnect)
            candidates.append(
                {
                    "decision_type": "automated_degraded_state_stabilization_action",
                    "priority_score": confidence,
                    "confidence": confidence,
                    "risk_score": float(reconnect.get("risk_score", 0.0) or 0.0),
                    "dedup_key": f"{organization_id}:degraded_stabilization:{reconnect.get('dedup_key')}",
                    "payload": {
                        "operation_type": "degraded_state_stabilization",
                        "reason": "reconnect_instability_and_resilience_state",
                        "forecast": reconnect,
                    },
                    "ride_id": None,
                    "requires_rollback_record": False,
                }
            )

        for item in candidates:
            item["decision_id"] = OperationalOrchestrationResilienceService._stable_decision_id(
                organization_id=organization_id,
                decision_type=str(item.get("decision_type") or "autonomous_decision"),
                material={
                    "dedup_key": str(item.get("dedup_key") or ""),
                    "ride_id": str(item.get("ride_id") or ""),
                    "priority_score": round(float(item.get("priority_score", 0.0) or 0.0), 6),
                },
            )

        candidates.sort(
            key=lambda item: (
                float(item.get("priority_score", 0.0) or 0.0),
                float(item.get("confidence", 0.0) or 0.0),
                str(item.get("decision_type") or ""),
                str(item.get("decision_id") or ""),
            ),
            reverse=True,
        )
        return candidates

    @staticmethod
    def execute_autonomous_recovery_coordinator(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        resilience_state: dict[str, Any],
        recovery_operations: list[dict[str, Any]],
        predictive_recovery: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        state = str(resilience_state.get("state") or "healthy")
        chain: list[dict[str, Any]] = []
        chain.extend({"operation_type": str(item.get("operation_type") or "recovery"), "source": "reactive", **item} for item in recovery_operations)
        chain.extend({"operation_type": str(item.get("operation_type") or "predictive_recovery"), "source": "predictive", **item} for item in predictive_recovery)

        if state in {"degraded", "critical", "synchronization_risk", "replay_repair"}:
            stabilized = {
                "operation_type": "autonomous_recovery_stabilization_chain",
                "source": "autonomous_recovery_coordinator",
                "state": state,
                "action": "degraded_websocket_stabilization_and_state_reconciliation",
                "generated_at": now().isoformat(),
                "dedup_key": f"{organization_id}:recovery_chain:{state}:{len(chain)}",
            }
            if not OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.autonomous.recovery.executed",
                dedup_key=stabilized["dedup_key"],
                minutes=8,
            ):
                OperationalOrchestrationResilienceService._audit(
                    db,
                    organization_id=organization_id,
                    event_type="orchestration.autonomous.recovery.executed",
                    payload=stabilized,
                    actor_user_id=actor_user_id,
                )
                OperationalSynchronizationEngine.publish_event(
                    organization_id=organization_id,
                    event_type=OperationalEventType.WORKFLOW_TRANSITION,
                    payload={**stabilized, "autonomous": True, "predictive": True},
                    role_scope=list(OperationalOrchestrationResilienceService.CROSS_ROLE_SCOPE),
                    source_nonce=f"autonomous_recovery_chain:{stabilized['dedup_key']}",
                    metadata={"actor_user_id": actor_user_id or "", "source": "autonomous_recovery_coordinator"},
                )
            chain.append(stabilized)

        return chain

    @staticmethod
    def execute_autonomous_decision_engine(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        escalations: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        recovery_operations: list[dict[str, Any]],
        predictive_recovery: list[dict[str, Any]],
        forecasts: list[dict[str, Any]],
        resilience_state: dict[str, Any],
    ) -> dict[str, Any]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        policy = OperationalOrchestrationResilienceService._active_policy(db, organization_id)
        policy_rules = OperationalOrchestrationResilienceService._policy_rules(policy)
        execution_depth = int(policy_rules.get("execution_depth", 1) or 1)

        candidates = OperationalOrchestrationResilienceService.build_autonomous_decision_candidates(
            organization_id=organization_id,
            escalations=escalations,
            recommendations=recommendations,
            recovery_operations=recovery_operations,
            predictive_recovery=predictive_recovery,
            forecasts=forecasts,
            resilience_state=resilience_state,
        )

        executed: list[dict[str, Any]] = []
        denied: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        approvals: list[dict[str, Any]] = []
        rollbacks: list[dict[str, Any]] = []
        conflict_by_ride: dict[str, dict[str, Any]] = {}

        for candidate in candidates:
            decision_type = str(candidate.get("decision_type") or "autonomous_decision")
            decision_confidence = OperationalOrchestrationResilienceService._decision_confidence(candidate)
            dedup_key = str(candidate.get("dedup_key") or "")

            policy_gate = OperationalOrchestrationResilienceService._evaluate_policy_gate(
                organization_id=organization_id,
                thresholds=thresholds,
                policy=policy,
                decision_type=decision_type,
                decision_confidence=decision_confidence,
                execution_depth=execution_depth,
            )
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.autonomous.policy.evaluated",
                payload={
                    "decision_id": candidate.get("decision_id"),
                    "decision_type": decision_type,
                    "dedup_key": dedup_key,
                    "policy_gate": policy_gate,
                },
                actor_user_id=actor_user_id,
            )

            if OperationalOrchestrationResilienceService._autonomous_loop_detected(
                db,
                organization_id=organization_id,
                decision_type=decision_type,
                thresholds=thresholds,
            ):
                denial = {
                    "decision_id": candidate.get("decision_id"),
                    "decision_type": decision_type,
                    "reason": "escalation_loop_prevention",
                    "dedup_key": dedup_key,
                }
                OperationalOrchestrationResilienceService._audit(
                    db,
                    organization_id=organization_id,
                    event_type="orchestration.autonomous.decision.denied",
                    payload=denial,
                    actor_user_id=actor_user_id,
                )
                denied.append(denial)
                continue

            if OperationalOrchestrationResilienceService._recent_duplicate_decision(
                db,
                organization_id=organization_id,
                dedup_key=dedup_key,
                thresholds=thresholds,
            ):
                denial = {
                    "decision_id": candidate.get("decision_id"),
                    "decision_type": decision_type,
                    "reason": "duplicate_automation_suppression",
                    "dedup_key": dedup_key,
                }
                OperationalOrchestrationResilienceService._audit(
                    db,
                    organization_id=organization_id,
                    event_type="orchestration.autonomous.decision.denied",
                    payload=denial,
                    actor_user_id=actor_user_id,
                )
                denied.append(denial)
                continue

            ride_id = str(candidate.get("ride_id") or "")
            if bool(thresholds.get("autonomous_conflict_safety_enabled", True)) and ride_id:
                current = conflict_by_ride.get(ride_id)
                if current is not None and str(current.get("dedup_key")) != dedup_key:
                    conflict = {
                        "ride_id": ride_id,
                        "decision_id": candidate.get("decision_id"),
                        "conflicting_decision_id": current.get("decision_id"),
                        "decision_type": decision_type,
                        "reason": "operational_conflict_detection",
                        "dedup_key": dedup_key,
                    }
                    OperationalOrchestrationResilienceService._audit(
                        db,
                        organization_id=organization_id,
                        event_type="orchestration.autonomous.decision.conflict",
                        payload=conflict,
                        actor_user_id=actor_user_id,
                    )
                    conflicts.append(conflict)
                    continue
                conflict_by_ride[ride_id] = candidate

            if not bool(policy_gate.get("allowed", True)):
                denial = {
                    "decision_id": candidate.get("decision_id"),
                    "decision_type": decision_type,
                    "reason": "policy_constrained_automation_denial",
                    "policy_reasons": list(policy_gate.get("reasons") or []),
                    "dedup_key": dedup_key,
                }
                OperationalOrchestrationResilienceService._audit(
                    db,
                    organization_id=organization_id,
                    event_type="orchestration.autonomous.decision.denied",
                    payload=denial,
                    actor_user_id=actor_user_id,
                )
                denied.append(denial)
                continue

            if bool(policy_gate.get("requires_approval", False)):
                approval = create_approval_proposal(
                    db,
                    organization_id=organization_id,
                    actor_user_id=actor_user_id,
                    action_type=decision_type,
                    parameters={
                        "decision_id": candidate.get("decision_id"),
                        "decision_type": decision_type,
                        "payload": dict(candidate.get("payload") or {}),
                        "dedup_key": dedup_key,
                    },
                    confidence_score=decision_confidence,
                    rollback_available=bool(candidate.get("requires_rollback_record", False)),
                    expiration_minutes=int(thresholds.get("autonomous_approval_expiration_minutes", 30) or 30),
                    tenant_scope=organization_id,
                )
                approval_payload = {
                    "decision_id": candidate.get("decision_id"),
                    "decision_type": decision_type,
                    "approval_id": approval.id,
                    "approval_required": True,
                    "status": approval.status,
                    "confidence": round(decision_confidence, 6),
                    "dedup_key": dedup_key,
                }
                OperationalOrchestrationResilienceService._audit(
                    db,
                    organization_id=organization_id,
                    event_type="orchestration.autonomous.approval.required",
                    payload=approval_payload,
                    actor_user_id=actor_user_id,
                )
                OperationalSynchronizationEngine.publish_event(
                    organization_id=organization_id,
                    event_type=OperationalEventType.SUPERVISION_ALERT,
                    payload={**approval_payload, "autonomous": True, "supervisor_intervention_required": True},
                    role_scope=["supervisor", "command-center", "admin", "staff", "provider"],
                    source_nonce=f"autonomous_approval:{approval.id}",
                    metadata={"actor_user_id": actor_user_id or "", "source": "autonomous_decision_engine"},
                )
                approvals.append(approval_payload)
                continue

            decision_payload = {
                "decision_id": candidate.get("decision_id"),
                "decision_type": decision_type,
                "dedup_key": dedup_key,
                "confidence": round(decision_confidence, 6),
                "priority_score": round(float(candidate.get("priority_score", 0.0) or 0.0), 6),
                "risk_score": round(float(candidate.get("risk_score", 0.0) or 0.0), 6),
                "payload": dict(candidate.get("payload") or {}),
                "execution_depth": execution_depth,
                "safety_enforced": True,
                "generated_at": now().isoformat(),
            }
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.autonomous.decision.executed",
                payload=decision_payload,
                actor_user_id=actor_user_id,
            )
            OperationalSynchronizationEngine.publish_event(
                organization_id=organization_id,
                event_type=OperationalEventType.COORDINATION_RECOMMENDATION,
                payload={**decision_payload, "autonomous": True, "executed": True},
                role_scope=list(OperationalOrchestrationResilienceService.CROSS_ROLE_SCOPE),
                source_nonce=f"autonomous_executed:{dedup_key}",
                metadata={"actor_user_id": actor_user_id or "", "source": "autonomous_decision_engine"},
            )
            executed.append(decision_payload)

            if bool(candidate.get("requires_rollback_record", False)):
                rollback = {
                    "decision_id": candidate.get("decision_id"),
                    "decision_type": decision_type,
                    "authorization": "required",
                    "status": "available",
                    "dedup_key": f"rollback:{dedup_key}",
                    "generated_at": now().isoformat(),
                }
                OperationalOrchestrationResilienceService._audit(
                    db,
                    organization_id=organization_id,
                    event_type="orchestration.autonomous.rollback.recorded",
                    payload=rollback,
                    actor_user_id=actor_user_id,
                )
                rollbacks.append(rollback)

        recovery_chain = OperationalOrchestrationResilienceService.execute_autonomous_recovery_coordinator(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            resilience_state=resilience_state,
            recovery_operations=recovery_operations,
            predictive_recovery=predictive_recovery,
        )

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "deterministic_execution": True,
            "policy_constrained": True,
            "safety_enforced": True,
            "executed": executed,
            "denied": denied,
            "approval_required": approvals,
            "conflicts": conflicts,
            "rollback_records": rollbacks,
            "autonomous_recovery_chain": recovery_chain,
            "decision_count": len(candidates),
            "execution_count": len(executed),
            "denial_count": len(denied),
            "approval_count": len(approvals),
            "conflict_count": len(conflicts),
        }

    @staticmethod
    def _build_agent_recommendation(
        *,
        organization_id: str,
        agent_id: str,
        decision_type: str,
        action_key: str,
        confidence: float,
        priority_score: float,
        risk_score: float,
        ride_id: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        recommendation_id = OperationalOrchestrationResilienceService._stable_decision_id(
            organization_id=organization_id,
            decision_type=f"agent:{agent_id}:{decision_type}",
            material={
                "action_key": action_key,
                "ride_id": str(ride_id or ""),
                "confidence": round(float(confidence), 6),
                "priority_score": round(float(priority_score), 6),
            },
        )
        return {
            "recommendation_id": recommendation_id,
            "agent_id": agent_id,
            "decision_type": decision_type,
            "action_key": action_key,
            "confidence": OperationalOrchestrationResilienceService._bounded(confidence),
            "priority_score": OperationalOrchestrationResilienceService._bounded(priority_score),
            "risk_score": OperationalOrchestrationResilienceService._bounded(risk_score),
            "ride_id": ride_id,
            "payload": payload,
            "generated_at": now().isoformat(),
        }

    @staticmethod
    def build_multi_agent_operational_coordination_layer(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        escalations: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        recovery_operations: list[dict[str, Any]],
        proactive_recovery: list[dict[str, Any]],
        forecasts: list[dict[str, Any]],
        driver_reliability: list[dict[str, Any]],
        regional_forecasts: list[dict[str, Any]],
        resilience_state: dict[str, Any],
    ) -> dict[str, Any]:
        agent_recommendations: list[dict[str, Any]] = []
        state = str(resilience_state.get("state") or "healthy")

        for item in recommendations[:80]:
            rec_type = str(item.get("recommendation_type") or "dispatch_recommendation")
            ride_id = str(item.get("ride_id")) if item.get("ride_id") else None
            score = float(item.get("score", 0.0) or 0.0)
            agent_recommendations.append(
                OperationalOrchestrationResilienceService._build_agent_recommendation(
                    organization_id=organization_id,
                    agent_id="dispatch_intelligence_agent",
                    decision_type="dispatch_orchestration",
                    action_key=f"dispatch:{rec_type}:{ride_id or 'none'}",
                    confidence=max(0.55, score),
                    priority_score=max(0.55, score),
                    risk_score=score,
                    ride_id=ride_id,
                    payload=dict(item),
                )
            )

        for item in forecasts[:80]:
            prediction_type = str(item.get("prediction_type") or "")
            risk = float(item.get("risk_score", 0.0) or 0.0)
            if prediction_type in {"projected_sla_breach", "projected_arrival_delay"}:
                agent_recommendations.append(
                    OperationalOrchestrationResilienceService._build_agent_recommendation(
                        organization_id=organization_id,
                        agent_id="sla_risk_agent",
                        decision_type="sla_mitigation",
                        action_key=f"sla:{prediction_type}:{item.get('ride_id') or 'none'}",
                        confidence=max(0.6, risk),
                        priority_score=max(0.6, risk),
                        risk_score=risk,
                        ride_id=str(item.get("ride_id")) if item.get("ride_id") else None,
                        payload=dict(item),
                    )
                )
            if prediction_type == "projected_dispatcher_overload":
                agent_recommendations.append(
                    OperationalOrchestrationResilienceService._build_agent_recommendation(
                        organization_id=organization_id,
                        agent_id="overload_mitigation_agent",
                        decision_type="overload_redistribution",
                        action_key=f"overload:{int(risk * 100)}",
                        confidence=max(0.58, risk),
                        priority_score=max(0.58, risk),
                        risk_score=risk,
                        ride_id=None,
                        payload=dict(item),
                    )
                )
            if prediction_type == "projected_reconnect_instability" and state in {"degraded", "critical", "synchronization_risk", "replay_repair"}:
                agent_recommendations.append(
                    OperationalOrchestrationResilienceService._build_agent_recommendation(
                        organization_id=organization_id,
                        agent_id="reconnect_stabilization_agent",
                        decision_type="reconnect_stabilization",
                        action_key=f"reconnect:{int(risk * 100)}:{state}",
                        confidence=max(0.65, risk),
                        priority_score=max(0.65, risk),
                        risk_score=risk,
                        ride_id=None,
                        payload={"state": state, **dict(item)},
                    )
                )

        for item in recovery_operations[:50]:
            op_type = str(item.get("operation_type") or "recovery")
            agent_recommendations.append(
                OperationalOrchestrationResilienceService._build_agent_recommendation(
                    organization_id=organization_id,
                    agent_id="recovery_coordination_agent",
                    decision_type="recovery_coordination",
                    action_key=f"recovery:{op_type}:{item.get('ride_id') or 'none'}",
                    confidence=0.72,
                    priority_score=0.72,
                    risk_score=0.72,
                    ride_id=str(item.get("ride_id")) if item.get("ride_id") else None,
                    payload=dict(item),
                )
            )

        for item in proactive_recovery[:50]:
            op_type = str(item.get("operation_type") or "proactive_recovery")
            score = float(item.get("projected_value", 0.0) or 0.0)
            agent_recommendations.append(
                OperationalOrchestrationResilienceService._build_agent_recommendation(
                    organization_id=organization_id,
                    agent_id="recovery_coordination_agent",
                    decision_type="predictive_recovery_coordination",
                    action_key=f"predictive_recovery:{op_type}",
                    confidence=max(0.6, OperationalOrchestrationResilienceService._bounded(score)),
                    priority_score=max(0.6, OperationalOrchestrationResilienceService._bounded(score)),
                    risk_score=OperationalOrchestrationResilienceService._bounded(score),
                    ride_id=str(item.get("ride_id")) if item.get("ride_id") else None,
                    payload=dict(item),
                )
            )

        for item in escalations[:50]:
            severity = str(item.get("severity") or "medium")
            severity_score = OperationalOrchestrationResilienceService._bounded(
                OperationalOrchestrationResilienceService._severity_rank(severity) / 4.0
            )
            agent_recommendations.append(
                OperationalOrchestrationResilienceService._build_agent_recommendation(
                    organization_id=organization_id,
                    agent_id="escalation_coordination_agent",
                    decision_type="escalation_priority_coordination",
                    action_key=f"escalation:{item.get('dedup_key') or item.get('escalation_id')}",
                    confidence=max(0.58, severity_score),
                    priority_score=max(0.58, severity_score),
                    risk_score=severity_score,
                    ride_id=str(item.get("ride_id")) if item.get("ride_id") else None,
                    payload=dict(item),
                )
            )

        for item in driver_reliability[:40]:
            if bool(item.get("high_reliability_risk")):
                risk = float(item.get("risk_score", 0.0) or 0.0)
                agent_recommendations.append(
                    OperationalOrchestrationResilienceService._build_agent_recommendation(
                        organization_id=organization_id,
                        agent_id="driver_balancing_agent",
                        decision_type="driver_redistribution",
                        action_key=f"driver_balance:{item.get('driver_id') or 'unknown'}",
                        confidence=max(0.58, risk),
                        priority_score=max(0.58, risk),
                        risk_score=risk,
                        ride_id=str(item.get("ride_id")) if item.get("ride_id") else None,
                        payload=dict(item),
                    )
                )

        for item in regional_forecasts[:40]:
            risk = float(item.get("risk_score", 0.0) or 0.0)
            region_key = str(item.get("region_key") or "unknown_region")
            agent_recommendations.append(
                OperationalOrchestrationResilienceService._build_agent_recommendation(
                    organization_id=organization_id,
                    agent_id="regional_mobility_intelligence_agent",
                    decision_type="regional_mobility_stabilization",
                    action_key=f"regional_mobility:{region_key}",
                    confidence=max(0.56, risk),
                    priority_score=max(0.56, risk),
                    risk_score=risk,
                    ride_id=None,
                    payload=dict(item),
                )
            )

        by_agent: dict[str, int] = {}
        for item in agent_recommendations:
            by_agent[str(item.get("agent_id") or "unknown_agent")] = by_agent.get(str(item.get("agent_id") or "unknown_agent"), 0) + 1

        coordination_payload = {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "resilience_state": state,
            "agents": dict(OperationalOrchestrationResilienceService.COORDINATED_AGENT_REGISTRY),
            "agent_recommendations": agent_recommendations,
            "recommendation_count": len(agent_recommendations),
            "agent_activity": by_agent,
            "deterministic_synchronization": True,
            "shared_operational_truth": True,
            "conflict_safe_orchestration": True,
            "replay_safe_coordination_state": True,
        }
        OperationalOrchestrationResilienceService._audit(
            db,
            organization_id=organization_id,
            event_type="orchestration.multi_agent.coordination.generated",
            payload={
                "dedup_key": f"{organization_id}:coordination:{len(agent_recommendations)}:{state}",
                "recommendation_count": len(agent_recommendations),
                "resilience_state": state,
                "agent_activity": by_agent,
            },
            actor_user_id=actor_user_id,
        )
        return coordination_payload

    @staticmethod
    def execute_agent_consensus_infrastructure(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        coordination_layer: dict[str, Any],
        resilience_state: dict[str, Any],
    ) -> dict[str, Any]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        policy = OperationalOrchestrationResilienceService._active_policy(db, organization_id)
        recommendations = [
            item for item in list(coordination_layer.get("agent_recommendations") or []) if isinstance(item, dict)
        ]
        min_confidence = float(thresholds.get("multi_agent_consensus_min_confidence", 0.62) or 0.62)

        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in recommendations:
            grouped.setdefault(str(item.get("action_key") or "unknown_action"), []).append(item)

        computed: list[dict[str, Any]] = []
        denied: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []

        for action_key, group in grouped.items():
            ranked: list[tuple[float, int, dict[str, Any]]] = []
            weighted_sum = 0.0
            weight_total = 0.0
            for item in group:
                agent_id = str(item.get("agent_id") or "")
                registry = OperationalOrchestrationResilienceService.COORDINATED_AGENT_REGISTRY.get(agent_id, {})
                weight = float(registry.get("weight", 1.0) or 1.0)
                authority = int(registry.get("authority_priority", 0) or 0)
                confidence = float(item.get("confidence", 0.0) or 0.0)
                weighted = confidence * weight
                weighted_sum += weighted
                weight_total += weight
                ranked.append((weighted, authority, item))
            ranked.sort(key=lambda row: (row[0], row[1], str((row[2] or {}).get("recommendation_id") or "")), reverse=True)
            primary = ranked[0][2] if ranked else {}
            consensus_confidence = weighted_sum / max(weight_total, 1e-6)
            consensus_score = OperationalOrchestrationResilienceService._bounded(
                (consensus_confidence + float(primary.get("priority_score", 0.0) or 0.0)) / 2.0
            )
            decision_type = str(primary.get("decision_type") or "coordinated_action")
            policy_gate = OperationalOrchestrationResilienceService._evaluate_policy_gate(
                organization_id=organization_id,
                thresholds=thresholds,
                policy=policy,
                decision_type=decision_type,
                decision_confidence=consensus_score,
                execution_depth=1,
            )

            if consensus_score < min_confidence:
                denied.append(
                    {
                        "action_key": action_key,
                        "decision_type": decision_type,
                        "reason": "consensus_below_threshold",
                        "consensus_score": round(consensus_score, 6),
                        "supporting_agents": [str(item.get("agent_id") or "") for item in group],
                    }
                )
                continue

            if not bool(policy_gate.get("allowed", True)):
                denial = {
                    "action_key": action_key,
                    "decision_type": decision_type,
                    "reason": "policy_constrained_arbitration",
                    "policy_reasons": list(policy_gate.get("reasons") or []),
                    "consensus_score": round(consensus_score, 6),
                }
                denied.append(denial)
                OperationalOrchestrationResilienceService._audit(
                    db,
                    organization_id=organization_id,
                    event_type="orchestration.multi_agent.arbitration.policy_conflict",
                    payload=denial,
                    actor_user_id=actor_user_id,
                )
                continue

            computed.append(
                {
                    "consensus_id": OperationalOrchestrationResilienceService._stable_decision_id(
                        organization_id=organization_id,
                        decision_type=f"consensus:{decision_type}",
                        material={
                            "action_key": action_key,
                            "supporting_agents": sorted([str(item.get("agent_id") or "") for item in group]),
                            "score": round(consensus_score, 6),
                        },
                    ),
                    "action_key": action_key,
                    "decision_type": decision_type,
                    "supporting_agents": [str(item.get("agent_id") or "") for item in group],
                    "consensus_score": round(consensus_score, 6),
                    "weighted_confidence": round(consensus_confidence, 6),
                    "priority_score": round(float(primary.get("priority_score", 0.0) or 0.0), 6),
                    "risk_score": round(float(primary.get("risk_score", 0.0) or 0.0), 6),
                    "ride_id": primary.get("ride_id"),
                    "payload": dict(primary.get("payload") or {}),
                    "dedup_key": f"{organization_id}:consensus:{action_key}:{decision_type}",
                }
            )

        computed.sort(
            key=lambda item: (
                float(item.get("consensus_score", 0.0) or 0.0),
                float(item.get("weighted_confidence", 0.0) or 0.0),
                str(item.get("consensus_id") or ""),
            ),
            reverse=True,
        )

        accepted: list[dict[str, Any]] = []
        ride_lock: dict[str, dict[str, Any]] = {}
        for item in computed:
            ride_id = str(item.get("ride_id") or "")
            if ride_id:
                existing = ride_lock.get(ride_id)
                if existing is not None and str(existing.get("action_key")) != str(item.get("action_key")):
                    conflicts.append(
                        {
                            "ride_id": ride_id,
                            "action_key": item.get("action_key"),
                            "conflicting_action_key": existing.get("action_key"),
                            "reason": "consensus_conflict_resolution",
                        }
                    )
                    continue
                ride_lock[ride_id] = item
            accepted.append(item)

        storm_limit = int(thresholds.get("multi_agent_storm_max_actions", 8) or 8)
        if len(accepted) > max(1, storm_limit):
            suppressed = accepted[storm_limit:]
            accepted = accepted[:storm_limit]
            suppression_payload = {
                "reason": "orchestration_storm_suppression",
                "suppressed_count": len(suppressed),
                "accepted_count": len(accepted),
                "dedup_key": f"{organization_id}:storm_suppression:{len(suppressed)}:{len(accepted)}",
            }
            denied.extend(
                {
                    "action_key": item.get("action_key"),
                    "decision_type": item.get("decision_type"),
                    "reason": "orchestration_storm_suppression",
                }
                for item in suppressed
            )
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.multi_agent.storm.suppressed",
                payload=suppression_payload,
                actor_user_id=actor_user_id,
            )

        executed: list[dict[str, Any]] = []
        for item in accepted:
            dedup_key = str(item.get("dedup_key") or "")
            if OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.multi_agent.consensus.executed",
                dedup_key=dedup_key,
                minutes=int(thresholds.get("multi_agent_duplicate_suppression_minutes", 10) or 10),
            ):
                denied.append(
                    {
                        "action_key": item.get("action_key"),
                        "decision_type": item.get("decision_type"),
                        "reason": "duplicate_execution_suppression",
                    }
                )
                continue
            payload = {
                **item,
                "resilience_state": str(resilience_state.get("state") or "healthy"),
                "generated_at": now().isoformat(),
                "deterministic": True,
            }
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.multi_agent.consensus.executed",
                payload=payload,
                actor_user_id=actor_user_id,
            )
            OperationalSynchronizationEngine.publish_event(
                organization_id=organization_id,
                event_type=OperationalEventType.COORDINATION_RECOMMENDATION,
                payload={**payload, "multi_agent": True, "consensus_executed": True},
                role_scope=list(OperationalOrchestrationResilienceService.CROSS_ROLE_SCOPE),
                source_nonce=f"multi_agent_consensus:{dedup_key}",
                metadata={"actor_user_id": actor_user_id or "", "source": "multi_agent_consensus_engine"},
            )
            executed.append(payload)

        summary = {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "executed": executed,
            "denied": denied,
            "conflicts": conflicts,
            "execution_count": len(executed),
            "denial_count": len(denied),
            "conflict_count": len(conflicts),
            "consensus_deterministic": True,
            "policy_constrained_arbitration": True,
            "tie_break_authority_rules": True,
            "race_condition_safety": True,
        }
        OperationalOrchestrationResilienceService._audit(
            db,
            organization_id=organization_id,
            event_type="orchestration.multi_agent.consensus.computed",
            payload={
                "dedup_key": f"{organization_id}:consensus_summary:{len(executed)}:{len(denied)}:{len(conflicts)}",
                "execution_count": len(executed),
                "denial_count": len(denied),
                "conflict_count": len(conflicts),
            },
            actor_user_id=actor_user_id,
        )
        for item in denied:
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.multi_agent.consensus.denied",
                payload=item,
                actor_user_id=actor_user_id,
            )
        for item in conflicts:
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.multi_agent.consensus.conflict",
                payload=item,
                actor_user_id=actor_user_id,
            )
        return summary

    @staticmethod
    def execute_autonomous_negotiation_framework(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        coordination_layer: dict[str, Any],
        consensus: dict[str, Any],
    ) -> dict[str, Any]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        round_limit = int(thresholds.get("multi_agent_negotiation_round_limit", 6) or 6)
        executed = [item for item in list(consensus.get("executed") or []) if isinstance(item, dict)]
        negotiations: list[dict[str, Any]] = []

        negotiation_domains = {
            "dispatcher_load_negotiation": ["dispatch_orchestration", "overload_redistribution"],
            "driver_redistribution_negotiation": ["driver_redistribution", "regional_mobility_stabilization"],
            "sla_mitigation_prioritization": ["sla_mitigation", "predictive_recovery_coordination"],
            "queue_balancing_coordination": ["dispatch_orchestration"],
            "escalation_priority_arbitration": ["escalation_priority_coordination"],
            "resource_contention_resolution": ["recovery_coordination", "reconnect_stabilization"],
        }

        for domain, decision_types in negotiation_domains.items():
            contenders = [item for item in executed if str(item.get("decision_type") or "") in decision_types]
            if not contenders:
                continue
            contenders.sort(
                key=lambda item: (
                    float(item.get("consensus_score", 0.0) or 0.0),
                    float(item.get("weighted_confidence", 0.0) or 0.0),
                    str(item.get("consensus_id") or ""),
                ),
                reverse=True,
            )
            winner = contenders[0]
            round_payload = {
                "negotiation_id": OperationalOrchestrationResilienceService._stable_decision_id(
                    organization_id=organization_id,
                    decision_type=f"negotiation:{domain}",
                    material={
                        "winner": winner.get("consensus_id"),
                        "contenders": [item.get("consensus_id") for item in contenders[: max(1, round_limit)]],
                    },
                ),
                "domain": domain,
                "winner_consensus_id": winner.get("consensus_id"),
                "winning_action_key": winner.get("action_key"),
                "contenders": [item.get("consensus_id") for item in contenders[: max(1, round_limit)]],
                "round_count": min(len(contenders), max(1, round_limit)),
                "resolved": True,
                "generated_at": now().isoformat(),
                "dedup_key": f"{organization_id}:negotiation:{domain}:{winner.get('consensus_id')}",
            }
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.multi_agent.negotiation.round",
                payload=round_payload,
                actor_user_id=actor_user_id,
            )
            negotiations.append(round_payload)

        resolution_payload = {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "negotiations": negotiations,
            "negotiation_count": len(negotiations),
            "stability": "stable" if not negotiations else "coordinated",
            "autonomous_negotiation": True,
        }
        OperationalOrchestrationResilienceService._audit(
            db,
            organization_id=organization_id,
            event_type="orchestration.multi_agent.negotiation.resolved",
            payload={
                "dedup_key": f"{organization_id}:negotiation_resolved:{len(negotiations)}",
                "negotiation_count": len(negotiations),
            },
            actor_user_id=actor_user_id,
        )
        return resolution_payload

    @staticmethod
    def run_operational_simulation_engine(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        incidents: list[dict[str, Any]],
        forecasts: list[dict[str, Any]],
        resilience_state: dict[str, Any],
        recommendations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        horizon_minutes = int(thresholds.get("multi_agent_simulation_horizon_minutes", 45) or 45)
        forecast_map = {str(item.get("prediction_type") or ""): item for item in forecasts}
        overload = forecast_map.get("projected_dispatcher_overload", {})
        sla = forecast_map.get("projected_sla_breach", {})
        reconnect = forecast_map.get("projected_reconnect_instability", {})

        simulations = [
            {
                "simulation_type": "projected_overload_simulation",
                "projected_value": round(float(overload.get("projected_value", 0.0) or 0.0), 6),
                "risk_score": round(float(overload.get("risk_score", 0.0) or 0.0), 6),
            },
            {
                "simulation_type": "sla_breach_simulation",
                "projected_value": round(float(sla.get("projected_value", 0.0) or 0.0), 6),
                "risk_score": round(float(sla.get("risk_score", 0.0) or 0.0), 6),
            },
            {
                "simulation_type": "recovery_outcome_simulation",
                "projected_value": round(float(len(recommendations)) / max(1.0, float(len(incidents) or 1)), 6),
                "risk_score": round(float(len(incidents)) / max(1.0, float(len(recommendations) + 1)), 6),
            },
            {
                "simulation_type": "reassignment_outcome_prediction",
                "projected_value": round(
                    float(
                        sum(
                            1
                            for item in recommendations
                            if str(item.get("recommendation_type") or "")
                            in {"recovery_reassignment_suggestion", "nearest_qualified_driver_recommendation"}
                        )
                    ),
                    6,
                ),
                "risk_score": round(float(sla.get("risk_score", 0.0) or 0.0), 6),
            },
            {
                "simulation_type": "degraded_network_behavior_simulation",
                "projected_value": round(float(reconnect.get("projected_value", 0.0) or 0.0), 6),
                "risk_score": round(float(reconnect.get("risk_score", 0.0) or 0.0), 6),
                "state": str(resilience_state.get("state") or "healthy"),
            },
            {
                "simulation_type": "regional_congestion_modeling",
                "projected_value": round(
                    float(sum(float(item.get("risk_score", 0.0) or 0.0) for item in forecasts[:20]))
                    / max(1.0, float(len(forecasts[:20]) or 1)),
                    6,
                ),
                "risk_score": round(float(overload.get("risk_score", 0.0) or 0.0), 6),
            },
        ]

        payload = {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "horizon_minutes": horizon_minutes,
            "simulations": simulations,
            "deterministic_replay": True,
            "timeline_persisted": True,
            "policy_aware_projections": True,
            "audit_reconstructable": True,
            "dedup_key": f"{organization_id}:simulation:{horizon_minutes}:{len(simulations)}",
        }
        OperationalOrchestrationResilienceService._audit(
            db,
            organization_id=organization_id,
            event_type="orchestration.multi_agent.simulation.generated",
            payload=payload,
            actor_user_id=actor_user_id,
        )
        return payload

    @staticmethod
    def execute_cross_agent_recovery_coordination(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        resilience_state: dict[str, Any],
        autonomous_recovery_chain: list[dict[str, Any]],
        consensus: dict[str, Any],
        negotiation: dict[str, Any],
    ) -> dict[str, Any]:
        state = str(resilience_state.get("state") or "healthy")
        executed = [item for item in list(consensus.get("executed") or []) if isinstance(item, dict)]
        recovery_actions = [item for item in executed if "recovery" in str(item.get("decision_type") or "") or "stabilization" in str(item.get("decision_type") or "")]
        coordinated = {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "state": state,
            "coordinated_degraded_state_response": state in {"degraded", "critical", "synchronization_risk", "replay_repair"},
            "reconnect_recovery_synchronization": any(
                "reconnect" in str(item.get("decision_type") or "") for item in recovery_actions
            ),
            "overload_redistribution_coordination": any(
                str(item.get("decision_type") or "") == "overload_redistribution" for item in executed
            ),
            "orphaned_workflow_recovery_arbitration": any(
                "orphaned" in json.dumps(item.get("payload") or {}, sort_keys=True, default=str) for item in recovery_actions
            ),
            "escalation_suppression_coordination": int(consensus.get("denial_count", 0) or 0) > 0,
            "multi_region_stabilization_logic": any(
                "regional" in str(item.get("decision_type") or "") for item in executed
            ),
            "autonomous_recovery_chain": autonomous_recovery_chain,
            "consensus_recovery_actions": recovery_actions,
            "negotiation_resolution": dict(negotiation),
            "dedup_key": f"{organization_id}:cross_agent_recovery:{state}:{len(recovery_actions)}",
        }
        OperationalOrchestrationResilienceService._audit(
            db,
            organization_id=organization_id,
            event_type="orchestration.multi_agent.recovery.coordinated",
            payload=coordinated,
            actor_user_id=actor_user_id,
        )
        OperationalSynchronizationEngine.publish_event(
            organization_id=organization_id,
            event_type=OperationalEventType.WORKFLOW_TRANSITION,
            payload={**coordinated, "multi_agent": True, "recovery_coordination": True},
            role_scope=list(OperationalOrchestrationResilienceService.CROSS_ROLE_SCOPE),
            source_nonce=f"cross_agent_recovery:{coordinated['dedup_key']}",
            metadata={"actor_user_id": actor_user_id or "", "source": "cross_agent_recovery_coordination"},
        )
        return coordinated

    @staticmethod
    def build_shared_operational_memory_layer(
        *,
        organization_id: str,
        incidents: list[dict[str, Any]],
        resilience_state: dict[str, Any],
        forecasts: list[dict[str, Any]],
        driver_reliability: list[dict[str, Any]],
        regional_forecasts: list[dict[str, Any]],
        proactive_recovery: list[dict[str, Any]],
        consensus: dict[str, Any],
        simulations: dict[str, Any],
        cross_agent_recovery: dict[str, Any],
    ) -> dict[str, Any]:
        active_incidents = [dict(item) for item in incidents[:100] if isinstance(item, dict)]
        regional_degradation = [
            dict(item)
            for item in regional_forecasts[:120]
            if isinstance(item, dict) and float(item.get("risk_score", 0.0) or 0.0) >= 0.5
        ]
        historical_recovery = [dict(item) for item in proactive_recovery[:120] if isinstance(item, dict)]
        sla_risk = [
            dict(item)
            for item in forecasts[:120]
            if isinstance(item, dict)
            and str(item.get("prediction_type") or "") in {"projected_sla_breach", "projected_arrival_delay"}
        ]
        driver_history = [dict(item) for item in driver_reliability[:120] if isinstance(item, dict)]
        overload_trends = [
            dict(item)
            for item in forecasts[:120]
            if isinstance(item, dict)
            and str(item.get("prediction_type") or "") == "projected_dispatcher_overload"
        ]
        memory = {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "active_incident_memory": active_incidents,
            "regional_degradation_memory": regional_degradation,
            "historical_recovery_outcomes": historical_recovery,
            "sla_risk_persistence": sla_risk,
            "driver_reliability_history": driver_history,
            "overload_trend_persistence": overload_trends,
            "coordination_consensus_memory": {
                "executed": list(consensus.get("executed") or []),
                "denied": list(consensus.get("denied") or []),
                "conflicts": list(consensus.get("conflicts") or []),
            },
            "simulation_memory": list(simulations.get("simulations") or []),
            "cross_agent_recovery_memory": dict(cross_agent_recovery),
            "resilience_state": dict(resilience_state),
            "deterministic": True,
            "reconstructable": True,
            "sequence_ordered": True,
            "backend_authoritative": True,
        }
        digest = hashlib.sha256(
            json.dumps(memory, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()[:24]
        memory["snapshot_digest"] = digest
        memory["dedup_key"] = f"{organization_id}:shared_memory:{digest}"
        return memory

    @staticmethod
    def persist_shared_operational_memory_snapshot(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        memory_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        dedup_key = str(memory_snapshot.get("dedup_key") or "")
        if not OperationalOrchestrationResilienceService._has_recent_audit_key(
            db,
            organization_id=organization_id,
            event_type="orchestration.multi_agent.memory.snapshot",
            dedup_key=dedup_key,
            minutes=int(thresholds.get("multi_agent_memory_snapshot_minutes", 12) or 12),
        ):
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.multi_agent.memory.snapshot",
                payload=memory_snapshot,
                actor_user_id=actor_user_id,
            )
        return memory_snapshot

    @staticmethod
    def replayable_distributed_coordination_rebuild(
        db: Session,
        *,
        organization_id: str,
        limit: int = 500,
    ) -> dict[str, Any]:
        rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type.in_(list(OperationalOrchestrationResilienceService.MULTI_AGENT_AUDIT_TYPES)),
            )
            .order_by(HealthISFWorkflowAuditLog.created_at.asc(), HealthISFWorkflowAuditLog.id.asc())
            .limit(max(1, int(limit)))
            .all()
        )
        events: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            payload = _safe_json_load(row.payload, {})
            events.append(
                {
                    "replay_sequence": index,
                    "audit_id": str(row.id),
                    "event_type": str(row.event_type),
                    "payload": payload if isinstance(payload, dict) else {},
                    "created_at": _as_utc(row.created_at).isoformat() if row.created_at else _as_utc(now()).isoformat(),
                }
            )
        digest = hashlib.sha256(
            json.dumps(
                {
                    "organization_id": organization_id,
                    "event_count": len(events),
                    "first_event": events[0].get("audit_id") if events else None,
                    "last_event": events[-1].get("audit_id") if events else None,
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:24]
        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "event_count": len(events),
            "replay_digest": digest,
            "events": events,
            "replay_safe": True,
            "deterministic": True,
            "sequence_ordered": True,
            "audit_reconstructable": True,
            "timestamp_normalized": True,
        }

    @staticmethod
    def replayable_authority_rebuild(
        db: Session,
        *,
        organization_id: str,
        limit: int = 500,
    ) -> dict[str, Any]:
        rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type.in_(
                    list(OperationalOrchestrationResilienceService.AUTHORITY_AUDIT_TYPES)
                ),
            )
            .order_by(HealthISFWorkflowAuditLog.created_at.asc(), HealthISFWorkflowAuditLog.id.asc())
            .limit(max(1, int(limit)))
            .all()
        )
        events: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            payload = _safe_json_load(row.payload, {})
            events.append(
                {
                    "replay_sequence": index,
                    "audit_id": str(row.id),
                    "event_type": str(row.event_type),
                    "payload": payload if isinstance(payload, dict) else {},
                    "created_at": _as_utc(row.created_at).isoformat() if row.created_at else _as_utc(now()).isoformat(),
                }
            )

        replay_digest = hashlib.sha256(
            json.dumps(
                {
                    "organization_id": organization_id,
                    "event_count": len(events),
                    "first_event": events[0].get("audit_id") if events else None,
                    "last_event": events[-1].get("audit_id") if events else None,
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:24]

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "event_count": len(events),
            "replay_digest": replay_digest,
            "events": events,
            "replay_safe": True,
            "sequence_ordered": True,
            "timestamp_normalized": True,
            "audit_reconstructable": True,
            "append_only": True,
        }

    @staticmethod
    def build_operational_intelligence_timeline(
        db: Session,
        *,
        organization_id: str,
        limit: int = 300,
    ) -> dict[str, Any]:
        rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type.in_(
                    list(
                        OperationalOrchestrationResilienceService.PREDICTIVE_AUDIT_TYPES
                        | OperationalOrchestrationResilienceService.AUTONOMOUS_AUDIT_TYPES
                        | OperationalOrchestrationResilienceService.MULTI_AGENT_AUDIT_TYPES
                        | OperationalOrchestrationResilienceService.AUTHORITY_AUDIT_TYPES
                    )
                ),
            )
            .order_by(HealthISFWorkflowAuditLog.created_at.asc(), HealthISFWorkflowAuditLog.id.asc())
            .limit(max(1, int(limit)))
            .all()
        )

        timeline_entries: list[dict[str, Any]] = []
        confidence_points: dict[str, list[float]] = {}
        for sequence, row in enumerate(rows, start=1):
            payload = _safe_json_load(row.payload, {})
            normalized_payload = payload if isinstance(payload, dict) else {}
            prediction_type = str(normalized_payload.get("prediction_type") or normalized_payload.get("operation_type") or row.event_type)
            confidence = float(normalized_payload.get("confidence", 0.0) or 0.0)
            confidence_points.setdefault(prediction_type, []).append(confidence)
            timeline_entries.append(
                {
                    "timeline_sequence": sequence,
                    "audit_id": str(row.id),
                    "event_type": str(row.event_type),
                    "timeline_category": "autonomous_decision"
                    if str(row.event_type).startswith("orchestration.autonomous.")
                    else "multi_agent_coordination"
                    if str(row.event_type).startswith("orchestration.multi_agent.")
                    else "authenticated_authority"
                    if str(row.event_type).startswith("orchestration.authority.")
                    else "predictive_intelligence",
                    "prediction_type": prediction_type,
                    "confidence": round(confidence, 6),
                    "payload": normalized_payload,
                    "timestamp": _as_utc(row.created_at).isoformat() if row.created_at else _as_utc(now()).isoformat(),
                }
            )

        confidence_trends: list[dict[str, Any]] = []
        for key, values in confidence_points.items():
            if not values:
                continue
            trend = 0.0
            if len(values) >= 2:
                trend = float(values[-1] - values[0])
            confidence_trends.append(
                {
                    "signal": key,
                    "latest_confidence": round(values[-1], 6),
                    "average_confidence": round(sum(values) / len(values), 6),
                    "trend_delta": round(trend, 6),
                }
            )

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "timeline": timeline_entries,
            "confidence_trends": sorted(confidence_trends, key=lambda item: float(item.get("latest_confidence", 0.0)), reverse=True),
            "autonomous_decisions": [
                item for item in timeline_entries if str(item.get("timeline_category") or "") == "autonomous_decision"
            ],
            "approval_events": [
                item for item in timeline_entries if str(item.get("event_type") or "") == "orchestration.autonomous.approval.required"
            ],
            "rollback_events": [
                item for item in timeline_entries if str(item.get("event_type") or "") == "orchestration.autonomous.rollback.recorded"
            ],
            "policy_evaluations": [
                item for item in timeline_entries if str(item.get("event_type") or "") == "orchestration.autonomous.policy.evaluated"
            ],
            "automation_denials": [
                item for item in timeline_entries if str(item.get("event_type") or "") == "orchestration.autonomous.decision.denied"
            ],
            "orchestration_conflicts": [
                item for item in timeline_entries if str(item.get("event_type") or "") == "orchestration.autonomous.decision.conflict"
            ],
            "recovery_execution_chains": [
                item for item in timeline_entries if str(item.get("event_type") or "") == "orchestration.autonomous.recovery.executed"
            ],
            "agent_decisions": [
                item
                for item in timeline_entries
                if str(item.get("event_type") or "")
                in {
                    "orchestration.multi_agent.coordination.generated",
                    "orchestration.multi_agent.consensus.executed",
                }
            ],
            "consensus_events": [
                item
                for item in timeline_entries
                if str(item.get("event_type") or "")
                in {
                    "orchestration.multi_agent.consensus.computed",
                    "orchestration.multi_agent.consensus.executed",
                    "orchestration.multi_agent.consensus.denied",
                    "orchestration.multi_agent.consensus.conflict",
                }
            ],
            "negotiation_chains": [
                item
                for item in timeline_entries
                if str(item.get("event_type") or "")
                in {
                    "orchestration.multi_agent.negotiation.round",
                    "orchestration.multi_agent.negotiation.resolved",
                }
            ],
            "arbitration_outcomes": [
                item
                for item in timeline_entries
                if str(item.get("event_type") or "")
                in {
                    "orchestration.multi_agent.consensus.executed",
                    "orchestration.multi_agent.consensus.denied",
                    "orchestration.multi_agent.consensus.conflict",
                }
            ],
            "simulation_projections": [
                item for item in timeline_entries if str(item.get("event_type") or "") == "orchestration.multi_agent.simulation.generated"
            ],
            "policy_conflicts": [
                item for item in timeline_entries if str(item.get("event_type") or "") == "orchestration.multi_agent.arbitration.policy_conflict"
            ],
            "recovery_coordination_chains": [
                item for item in timeline_entries if str(item.get("event_type") or "") == "orchestration.multi_agent.recovery.coordinated"
            ],
            "authority_sessions": [
                item
                for item in timeline_entries
                if str(item.get("event_type") or "")
                in {
                    "orchestration.authority.session.issued",
                    "orchestration.authority.session.validated",
                    "orchestration.authority.session.revoked",
                }
            ],
            "execution_audit_lineage": [
                item
                for item in timeline_entries
                if str(item.get("event_type") or "")
                in {
                    "orchestration.authority.execution.requested",
                    "orchestration.authority.execution.approved",
                    "orchestration.authority.execution.denied",
                }
            ],
            "rollback_linkage": [
                item
                for item in timeline_entries
                if str(item.get("event_type") or "") == "orchestration.authority.execution.rollback_linked"
            ],
            "recovery_execution_lineage": [
                item
                for item in timeline_entries
                if str(item.get("event_type") or "") == "orchestration.authority.recovery.executed"
            ],
            "authority_tracking": [
                item
                for item in timeline_entries
                if str(item.get("timeline_category") or "") == "authenticated_authority"
            ],
            "replayable": True,
            "sequence_ordered": True,
            "timestamp_normalized": True,
            "audit_reconstructable": True,
        }

    @staticmethod
    def replayable_autonomous_decision_rebuild(
        db: Session,
        *,
        organization_id: str,
        limit: int = 500,
    ) -> dict[str, Any]:
        rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type.in_(list(OperationalOrchestrationResilienceService.AUTONOMOUS_AUDIT_TYPES)),
            )
            .order_by(HealthISFWorkflowAuditLog.created_at.asc(), HealthISFWorkflowAuditLog.id.asc())
            .limit(max(1, int(limit)))
            .all()
        )

        events: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            payload = _safe_json_load(row.payload, {})
            events.append(
                {
                    "replay_sequence": index,
                    "audit_id": str(row.id),
                    "event_type": str(row.event_type),
                    "payload": payload if isinstance(payload, dict) else {},
                    "created_at": _as_utc(row.created_at).isoformat() if row.created_at else _as_utc(now()).isoformat(),
                }
            )

        digest_source = {
            "organization_id": organization_id,
            "count": len(events),
            "first_event": events[0].get("audit_id") if events else None,
            "last_event": events[-1].get("audit_id") if events else None,
        }
        replay_digest = hashlib.sha256(
            json.dumps(digest_source, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()[:24]

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "event_count": len(events),
            "replay_digest": replay_digest,
            "events": events,
            "replay_safe": True,
            "reconstructable": True,
            "sequence_ordered": True,
            "timestamp_normalized": True,
            "audit_traceable": True,
        }

    @staticmethod
    def replayable_prediction_rebuild(
        db: Session,
        *,
        organization_id: str,
        limit: int = 500,
    ) -> dict[str, Any]:
        rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type.in_(
                    [
                        "orchestration.prediction.generated",
                        "orchestration.reliability.driver",
                        "orchestration.rider_risk.detected",
                        "orchestration.regional.forecast",
                        "orchestration.recovery.proactive",
                    ]
                ),
            )
            .order_by(HealthISFWorkflowAuditLog.created_at.asc(), HealthISFWorkflowAuditLog.id.asc())
            .limit(max(1, int(limit)))
            .all()
        )

        events: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            payload = _safe_json_load(row.payload, {})
            events.append(
                {
                    "replay_sequence": index,
                    "audit_id": str(row.id),
                    "event_type": str(row.event_type),
                    "payload": payload if isinstance(payload, dict) else {},
                    "created_at": _as_utc(row.created_at).isoformat() if row.created_at else _as_utc(now()).isoformat(),
                }
            )

        digest_source = {
            "organization_id": organization_id,
            "count": len(events),
            "first_event": events[0].get("audit_id") if events else None,
            "last_event": events[-1].get("audit_id") if events else None,
        }
        replay_digest = hashlib.sha256(
            json.dumps(digest_source, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()[:24]

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "event_count": len(events),
            "replay_digest": replay_digest,
            "events": events,
            "replay_safe": True,
            "reconstructable": True,
            "sequence_ordered": True,
            "timestamp_normalized": True,
            "audit_traceable": True,
        }

    @staticmethod
    def observe_resilience_state(
        db: Session,
        *,
        organization_id: str,
        incidents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        ws_stats = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
        queue_stats = RetryQueueService.get_queue_stats(db, organization_id=organization_id)
        replay = OperationalReplayService.replay_integrity(organization_id)

        state = "healthy"
        if not bool(replay.get("integrity_ok", True)):
            state = "replay_repair"
        elif int(queue_stats.get("dead_letter", 0) or 0) > 0 or int(queue_stats.get("failed", 0) or 0) > 0:
            state = "synchronization_risk"
        elif any(str(item.get("severity") or "").lower() == "critical" for item in incidents):
            state = "critical"
        elif int(ws_stats.get("disconnects_last_5m", 0) or 0) >= int(thresholds.get("reconnect_failure_disconnects_5m", 4) or 4):
            state = "degraded"

        previous_state = "healthy"
        latest_transition = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type == "orchestration.resilience.transition",
            )
            .order_by(desc(HealthISFWorkflowAuditLog.created_at))
            .first()
        )
        if latest_transition is not None:
            payload = _safe_json_load(latest_transition.payload, {})
            if isinstance(payload, dict):
                previous_state = str(payload.get("state") or previous_state)

        return {
            "state": state,
            "previous_state": previous_state,
            "changed": state != previous_state,
            "evaluated_at": now().isoformat(),
            "state_machine_states": [
                "healthy",
                "degraded",
                "recovering",
                "critical",
                "replay_repair",
                "synchronization_risk",
            ],
            "indicators": {
                "disconnects_last_5m": int(ws_stats.get("disconnects_last_5m", 0) or 0),
                "queue_failed": int(queue_stats.get("failed", 0) or 0),
                "queue_dead_letter": int(queue_stats.get("dead_letter", 0) or 0),
                "replay_integrity_ok": bool(replay.get("integrity_ok", True)),
            },
        }

    @staticmethod
    def latest_automation_projection(
        db: Session,
        *,
        organization_id: str,
        incidents: list[dict[str, Any]],
        limit: int = 300,
    ) -> dict[str, Any]:
        rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type.like("orchestration.%"),
            )
            .order_by(desc(HealthISFWorkflowAuditLog.created_at))
            .limit(max(1, int(limit)))
            .all()
        )
        escalations: list[dict[str, Any]] = []
        recommendations: list[dict[str, Any]] = []
        recovery: list[dict[str, Any]] = []
        forecasts: list[dict[str, Any]] = []
        driver_reliability: list[dict[str, Any]] = []
        rider_risk: list[dict[str, Any]] = []
        regional_forecasts: list[dict[str, Any]] = []
        proactive_recovery: list[dict[str, Any]] = []
        autonomous_executed: list[dict[str, Any]] = []
        autonomous_denied: list[dict[str, Any]] = []
        autonomous_approval: list[dict[str, Any]] = []
        autonomous_conflicts: list[dict[str, Any]] = []
        autonomous_recovery_chain: list[dict[str, Any]] = []
        multi_agent_coordination: list[dict[str, Any]] = []
        multi_agent_consensus: list[dict[str, Any]] = []
        multi_agent_negotiation: list[dict[str, Any]] = []
        multi_agent_simulation: list[dict[str, Any]] = []
        multi_agent_recovery: list[dict[str, Any]] = []
        multi_agent_memory: list[dict[str, Any]] = []
        authority_sessions: list[dict[str, Any]] = []
        authority_execution: list[dict[str, Any]] = []
        authority_rollbacks: list[dict[str, Any]] = []
        authority_recovery: list[dict[str, Any]] = []
        authority_hydration: list[dict[str, Any]] = []
        authority_integrity: list[dict[str, Any]] = []
        for row in rows:
            payload = _safe_json_load(row.payload, {})
            if not isinstance(payload, dict):
                continue
            if row.event_type == "orchestration.escalation.generated":
                escalations.append(payload)
            elif row.event_type == "orchestration.recommendation.generated":
                recommendations.append(payload)
            elif row.event_type == "orchestration.recovery.performed":
                recovery.append(payload)
            elif row.event_type == "orchestration.prediction.generated":
                forecasts.append(payload)
            elif row.event_type == "orchestration.reliability.driver":
                driver_reliability.append(payload)
            elif row.event_type == "orchestration.rider_risk.detected":
                rider_risk.append(payload)
            elif row.event_type == "orchestration.regional.forecast":
                regional_forecasts.append(payload)
            elif row.event_type == "orchestration.recovery.proactive":
                proactive_recovery.append(payload)
            elif row.event_type == "orchestration.autonomous.decision.executed":
                autonomous_executed.append(payload)
            elif row.event_type == "orchestration.autonomous.decision.denied":
                autonomous_denied.append(payload)
            elif row.event_type == "orchestration.autonomous.approval.required":
                autonomous_approval.append(payload)
            elif row.event_type == "orchestration.autonomous.decision.conflict":
                autonomous_conflicts.append(payload)
            elif row.event_type == "orchestration.autonomous.recovery.executed":
                autonomous_recovery_chain.append(payload)
            elif row.event_type == "orchestration.multi_agent.coordination.generated":
                multi_agent_coordination.append(payload)
            elif row.event_type in {
                "orchestration.multi_agent.consensus.computed",
                "orchestration.multi_agent.consensus.executed",
                "orchestration.multi_agent.consensus.denied",
                "orchestration.multi_agent.consensus.conflict",
            }:
                multi_agent_consensus.append(payload)
            elif row.event_type in {
                "orchestration.multi_agent.negotiation.round",
                "orchestration.multi_agent.negotiation.resolved",
            }:
                multi_agent_negotiation.append(payload)
            elif row.event_type == "orchestration.multi_agent.simulation.generated":
                multi_agent_simulation.append(payload)
            elif row.event_type == "orchestration.multi_agent.recovery.coordinated":
                multi_agent_recovery.append(payload)
            elif row.event_type == "orchestration.multi_agent.memory.snapshot":
                multi_agent_memory.append(payload)
            elif row.event_type in {
                "orchestration.authority.session.issued",
                "orchestration.authority.session.validated",
                "orchestration.authority.session.revoked",
            }:
                authority_sessions.append(payload)
            elif row.event_type in {
                "orchestration.authority.execution.requested",
                "orchestration.authority.execution.approved",
                "orchestration.authority.execution.denied",
            }:
                authority_execution.append(payload)
            elif row.event_type == "orchestration.authority.execution.rollback_linked":
                authority_rollbacks.append(payload)
            elif row.event_type == "orchestration.authority.recovery.executed":
                authority_recovery.append(payload)
            elif row.event_type == "orchestration.authority.hydration.restored":
                authority_hydration.append(payload)
            elif row.event_type == "orchestration.authority.runtime.integrity":
                authority_integrity.append(payload)

        resilience = OperationalOrchestrationResilienceService.observe_resilience_state(
            db,
            organization_id=organization_id,
            incidents=incidents,
        )
        replayable = OperationalOrchestrationResilienceService.replayable_automation_rebuild(
            db,
            organization_id=organization_id,
            limit=500,
        )
        prediction_rebuild = OperationalOrchestrationResilienceService.replayable_prediction_rebuild(
            db,
            organization_id=organization_id,
            limit=500,
        )
        autonomous_rebuild = OperationalOrchestrationResilienceService.replayable_autonomous_decision_rebuild(
            db,
            organization_id=organization_id,
            limit=500,
        )
        distributed_rebuild = OperationalOrchestrationResilienceService.replayable_distributed_coordination_rebuild(
            db,
            organization_id=organization_id,
            limit=500,
        )
        authority_rebuild = OperationalOrchestrationResilienceService.replayable_authority_rebuild(
            db,
            organization_id=organization_id,
            limit=500,
        )
        intelligence_timeline = OperationalOrchestrationResilienceService.build_operational_intelligence_timeline(
            db,
            organization_id=organization_id,
            limit=500,
        )

        shared_memory = dict(multi_agent_memory[0]) if multi_agent_memory else {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "active_incident_memory": list(incidents[:100]),
            "regional_degradation_memory": list(reversed(regional_forecasts[:120])),
            "historical_recovery_outcomes": list(reversed(proactive_recovery[:120])),
            "sla_risk_persistence": [
                item
                for item in reversed(forecasts[:120])
                if str(item.get("prediction_type") or "") in {"projected_sla_breach", "projected_arrival_delay"}
            ],
            "driver_reliability_history": list(reversed(driver_reliability[:120])),
            "overload_trend_persistence": [
                item
                for item in reversed(forecasts[:120])
                if str(item.get("prediction_type") or "") == "projected_dispatcher_overload"
            ],
            "deterministic": True,
            "reconstructable": True,
            "sequence_ordered": True,
            "backend_authoritative": True,
        }

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "automated_incident_escalations": list(reversed(escalations[:100])),
            "dispatch_recommendations": list(reversed(recommendations[:100])),
            "automated_recovery_operations": list(reversed(recovery[:100])),
            "predictive_sla_risk_engine": list(reversed(forecasts[:150])),
            "driver_reliability_intelligence": list(reversed(driver_reliability[:150])),
            "rider_operational_risk_detection": list(reversed(rider_risk[:150])),
            "regional_mobility_intelligence": list(reversed(regional_forecasts[:150])),
            "predictive_recovery_coordination": list(reversed(proactive_recovery[:150])),
            "autonomous_operational_decisions": {
                "executed": list(reversed(autonomous_executed[:150])),
                "denied": list(reversed(autonomous_denied[:150])),
                "approval_required": list(reversed(autonomous_approval[:150])),
                "conflicts": list(reversed(autonomous_conflicts[:150])),
                "autonomous_recovery_chain": list(reversed(autonomous_recovery_chain[:150])),
            },
            "multi_agent_operational_coordination": {
                "coordination_layer": list(reversed(multi_agent_coordination[:200])),
                "consensus_events": list(reversed(multi_agent_consensus[:300])),
                "negotiation_chains": list(reversed(multi_agent_negotiation[:300])),
                "simulation_projections": list(reversed(multi_agent_simulation[:120])),
                "recovery_coordination_chains": list(reversed(multi_agent_recovery[:200])),
                "shared_operational_memory": shared_memory,
            },
            "controlled_authenticated_operational_authority": {
                "authenticated_sessions": list(reversed(authority_sessions[:200])),
                "execution_audit": list(reversed(authority_execution[:300])),
                "rollback_links": list(reversed(authority_rollbacks[:200])),
                "recovery_lineage": list(reversed(authority_recovery[:200])),
                "hydration_recovery": list(reversed(authority_hydration[:120])),
                "runtime_integrity": list(reversed(authority_integrity[:120])),
            },
            "operational_intelligence_timeline": intelligence_timeline,
            "resilience_state_machine": resilience,
            "replayable_automation_rebuild": replayable,
            "replayable_prediction_rebuild": prediction_rebuild,
            "replayable_autonomous_decision_rebuild": autonomous_rebuild,
            "replayable_distributed_coordination_rebuild": distributed_rebuild,
            "replayable_authority_rebuild": authority_rebuild,
            "backend_authoritative": True,
            "replay_safe": True,
            "cross_role_synchronized": True,
            "read_only_projection": True,
        }

    @staticmethod
    def run_automated_recovery(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
    ) -> list[dict[str, Any]]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        if not bool(thresholds.get("automation_enabled", True)):
            return []

        operations: list[dict[str, Any]] = []
        dedup_minutes = int(thresholds.get("recovery_dedup_minutes", 8) or 8)

        rides = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.organization_id == organization_id)
            .all()
        )
        assignments = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.organization_id == organization_id)
            .all()
        )
        ws_stats = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
        queue_stats = RetryQueueService.get_queue_stats(db, organization_id=organization_id)
        replay = OperationalReplayService.replay_integrity(organization_id)

        orphaned = [
            row
            for row in rides
            if _status_text(row.status) in {RideStatus.ASSIGNED.value, RideStatus.DRIVER_EN_ROUTE.value, RideStatus.ACCEPTED.value}
            and not row.driver_id
        ]
        for ride in orphaned[:20]:
            dedup_key = f"orphaned_ride_recovery:{organization_id}:{ride.id}"
            if OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.recovery.performed",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                continue
            payload = {
                "operation_type": "orphaned_ride_recovery",
                "ride_id": str(ride.id),
                "action": "requeue_for_assignment",
                "dedup_key": dedup_key,
                "generated_at": now().isoformat(),
            }
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.recovery.performed",
                payload=payload,
                actor_user_id=actor_user_id,
            )
            OperationalSynchronizationEngine.publish_event(
                organization_id=organization_id,
                event_type=OperationalEventType.WORKFLOW_TRANSITION,
                payload={**payload, "automated": True},
                role_scope=list(OperationalOrchestrationResilienceService.CROSS_ROLE_SCOPE),
                source_nonce=f"automation_recovery:{dedup_key}",
                metadata={"actor_user_id": actor_user_id or "", "source": "operational_orchestration_engine"},
            )
            operations.append(payload)

        failed_assignment_states = {
            DispatchAssignmentState.EXPIRED.value,
            DispatchAssignmentState.REJECTED.value,
            DispatchAssignmentState.REASSIGNMENT_PENDING.value,
        }
        stale_assignments = [
            row
            for row in assignments
            if _status_text(row.assignment_state) in failed_assignment_states and _minutes_since(row.updated_at) >= 5
        ]
        for row in stale_assignments[:20]:
            dedup_key = f"failed_assignment_rollback:{organization_id}:{row.id}"
            if OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.recovery.performed",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                continue
            payload = {
                "operation_type": "failed_assignment_rollback",
                "assignment_id": str(row.id),
                "ride_id": str(row.ride_id),
                "action": "rollback_to_queue",
                "dedup_key": dedup_key,
                "generated_at": now().isoformat(),
            }
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.recovery.performed",
                payload=payload,
                actor_user_id=actor_user_id,
            )
            operations.append(payload)

        open_alert_reconnect = (
            db.query(OperationalAlertLog)
            .filter(
                OperationalAlertLog.organization_id == organization_id,
                OperationalAlertLog.alert_type == "websocket_disconnect_degradation_alert",
                OperationalAlertLog.alert_state.in_(["open", "acknowledged", "escalated"]),
            )
            .count()
        )
        reconnect_threshold = int(thresholds.get("reconnect_failure_disconnects_5m", 4) or 4)
        if int(ws_stats.get("disconnects_last_5m", 0) or 0) >= reconnect_threshold or open_alert_reconnect > 0:
            dedup_key = (
                f"degraded_websocket_recovery_mode:{organization_id}:"
                f"{int(ws_stats.get('disconnects_last_5m', 0) or 0)}:{int(open_alert_reconnect)}"
            )
            if not OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.recovery.performed",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                payload = {
                    "operation_type": "degraded_websocket_recovery_mode",
                    "action": "automatic_reconnect_resynchronization",
                    "disconnects_last_5m": int(ws_stats.get("disconnects_last_5m", 0) or 0),
                    "open_reconnect_alerts": int(open_alert_reconnect),
                    "dedup_key": dedup_key,
                    "generated_at": now().isoformat(),
                }
                OperationalOrchestrationResilienceService._audit(
                    db,
                    organization_id=organization_id,
                    event_type="orchestration.recovery.performed",
                    payload=payload,
                    actor_user_id=actor_user_id,
                )
                operations.append(payload)

        if not bool(replay.get("integrity_ok", True)):
            dedup_key = f"replay_mismatch_detection:{organization_id}:{int(replay.get('latest_sequence', 0) or 0)}"
            if not OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.recovery.performed",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                payload = {
                    "operation_type": "replay_mismatch_detection",
                    "action": "replay_repair_reconciliation",
                    "integrity": replay,
                    "dedup_key": dedup_key,
                    "generated_at": now().isoformat(),
                }
                OperationalOrchestrationResilienceService._audit(
                    db,
                    organization_id=organization_id,
                    event_type="orchestration.recovery.performed",
                    payload=payload,
                    actor_user_id=actor_user_id,
                )
                operations.append(payload)

        stale_cutoff = now() - timedelta(minutes=max(5, int(thresholds.get("stale_workflow_minutes", 25) or 25)))
        stale_incidents = (
            db.query(HealthISFWorkflowIncident)
            .filter(
                HealthISFWorkflowIncident.organization_id == organization_id,
                HealthISFWorkflowIncident.status.notin_(list(_STATUS_RESOLVED_STATES)),
                HealthISFWorkflowIncident.updated_at < stale_cutoff,
            )
            .count()
        )
        if stale_incidents > 0:
            dedup_key = f"stale_workflow_repair:{organization_id}:{stale_incidents}"
            if not OperationalOrchestrationResilienceService._has_recent_audit_key(
                db,
                organization_id=organization_id,
                event_type="orchestration.recovery.performed",
                dedup_key=dedup_key,
                minutes=dedup_minutes,
            ):
                payload = {
                    "operation_type": "stale_workflow_repair",
                    "action": "rebuild_open_workflow_context",
                    "stale_incident_count": int(stale_incidents),
                    "dedup_key": dedup_key,
                    "generated_at": now().isoformat(),
                }
                OperationalOrchestrationResilienceService._audit(
                    db,
                    organization_id=organization_id,
                    event_type="orchestration.recovery.performed",
                    payload=payload,
                    actor_user_id=actor_user_id,
                )
                operations.append(payload)

        consistency_source = {
            "queue_failed": int(queue_stats.get("failed", 0) or 0),
            "queue_dead_letter": int(queue_stats.get("dead_letter", 0) or 0),
            "replay_latest": int(replay.get("latest_sequence", 0) or 0),
            "replay_integrity": bool(replay.get("integrity_ok", True)),
            "operation_count": len(operations),
        }
        consistency_token = hashlib.sha256(
            json.dumps(consistency_source, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()[:24]
        dedup_key = f"operational_consistency_revalidation:{organization_id}:{consistency_token}"
        if not OperationalOrchestrationResilienceService._has_recent_audit_key(
            db,
            organization_id=organization_id,
            event_type="orchestration.recovery.performed",
            dedup_key=dedup_key,
            minutes=dedup_minutes,
        ):
            payload = {
                "operation_type": "operational_consistency_revalidation",
                "action": "cross_role_revalidation",
                "consistency_token": consistency_token,
                "dedup_key": dedup_key,
                "generated_at": now().isoformat(),
            }
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.recovery.performed",
                payload=payload,
                actor_user_id=actor_user_id,
            )
            operations.append(payload)

        for payload in operations:
            OperationalSynchronizationEngine.publish_event(
                organization_id=organization_id,
                event_type=OperationalEventType.WORKFLOW_TRANSITION,
                payload={**payload, "automated": True},
                role_scope=list(OperationalOrchestrationResilienceService.CROSS_ROLE_SCOPE),
                source_nonce=f"automation_recovery_broadcast:{payload.get('dedup_key')}",
                metadata={"actor_user_id": actor_user_id or "", "source": "operational_orchestration_engine"},
            )

        return operations

    @staticmethod
    def resolve_resilience_state(
        db: Session,
        *,
        organization_id: str,
        incidents: list[dict[str, Any]],
        recovery_operations: list[dict[str, Any]],
        actor_user_id: str | None,
    ) -> dict[str, Any]:
        thresholds = OperationalOrchestrationResilienceService._thresholds(db, organization_id)
        ws_stats = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
        queue_stats = RetryQueueService.get_queue_stats(db, organization_id=organization_id)
        replay = OperationalReplayService.replay_integrity(organization_id)

        state = "healthy"
        if not bool(replay.get("integrity_ok", True)):
            state = "replay_repair"
        elif int(queue_stats.get("dead_letter", 0) or 0) > 0 or int(queue_stats.get("failed", 0) or 0) > 0:
            state = "synchronization_risk"
        elif any(str(item.get("severity") or "").lower() == "critical" for item in incidents):
            state = "critical"
        elif int(ws_stats.get("disconnects_last_5m", 0) or 0) >= int(thresholds.get("reconnect_failure_disconnects_5m", 4) or 4):
            state = "degraded"
        elif len(recovery_operations) > 0:
            state = "recovering"

        previous_state = "healthy"
        latest_transition = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type == "orchestration.resilience.transition",
            )
            .order_by(desc(HealthISFWorkflowAuditLog.created_at))
            .first()
        )
        if latest_transition is not None:
            payload = _safe_json_load(latest_transition.payload, {})
            if isinstance(payload, dict):
                previous_state = str(payload.get("state") or previous_state)

        changed = state != previous_state
        if changed:
            payload = {
                "state": state,
                "previous_state": previous_state,
                "indicators": {
                    "disconnects_last_5m": int(ws_stats.get("disconnects_last_5m", 0) or 0),
                    "queue_failed": int(queue_stats.get("failed", 0) or 0),
                    "queue_dead_letter": int(queue_stats.get("dead_letter", 0) or 0),
                    "replay_integrity_ok": bool(replay.get("integrity_ok", True)),
                    "critical_incidents": sum(1 for item in incidents if str(item.get("severity") or "").lower() == "critical"),
                },
                "transitioned_at": now().isoformat(),
            }
            OperationalOrchestrationResilienceService._audit(
                db,
                organization_id=organization_id,
                event_type="orchestration.resilience.transition",
                payload=payload,
                actor_user_id=actor_user_id,
            )
            OperationalSynchronizationEngine.publish_event(
                organization_id=organization_id,
                event_type=OperationalEventType.SUPERVISION_ALERT,
                payload={
                    "resilience_state": state,
                    "previous_state": previous_state,
                    "indicators": payload.get("indicators", {}),
                    "automated": True,
                },
                role_scope=list(OperationalOrchestrationResilienceService.CROSS_ROLE_SCOPE),
                source_nonce=f"resilience_transition:{organization_id}:{state}:{int(_as_utc(now()).timestamp())}",
                metadata={"actor_user_id": actor_user_id or "", "source": "operational_orchestration_engine"},
            )

        return {
            "state": state,
            "previous_state": previous_state,
            "changed": changed,
            "evaluated_at": now().isoformat(),
            "state_machine_states": [
                "healthy",
                "degraded",
                "recovering",
                "critical",
                "replay_repair",
                "synchronization_risk",
            ],
            "indicators": {
                "disconnects_last_5m": int(ws_stats.get("disconnects_last_5m", 0) or 0),
                "queue_failed": int(queue_stats.get("failed", 0) or 0),
                "queue_dead_letter": int(queue_stats.get("dead_letter", 0) or 0),
                "replay_integrity_ok": bool(replay.get("integrity_ok", True)),
            },
        }

    @staticmethod
    def replayable_automation_rebuild(
        db: Session,
        *,
        organization_id: str,
        limit: int = 500,
    ) -> dict[str, Any]:
        rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type.like("orchestration.%"),
            )
            .order_by(HealthISFWorkflowAuditLog.created_at.asc(), HealthISFWorkflowAuditLog.id.asc())
            .limit(max(1, int(limit)))
            .all()
        )

        events: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            payload = _safe_json_load(row.payload, {})
            events.append(
                {
                    "replay_sequence": index,
                    "audit_id": str(row.id),
                    "event_type": str(row.event_type),
                    "payload": payload if isinstance(payload, dict) else {},
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )

        digest_source = {
            "organization_id": organization_id,
            "count": len(events),
            "first_event": events[0].get("audit_id") if events else None,
            "last_event": events[-1].get("audit_id") if events else None,
        }
        replay_digest = hashlib.sha256(
            json.dumps(digest_source, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()[:24]

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "event_count": len(events),
            "replay_digest": replay_digest,
            "events": events,
            "replay_safe": True,
            "reconstructable": True,
            "sequence_ordered": True,
            "timestamp_normalized": True,
            "audit_traceable": True,
        }

    @staticmethod
    def execute_automation_cycle(
        db: Session,
        *,
        organization_id: str,
        incidents: list[dict[str, Any]],
        actor_user_id: str | None,
    ) -> dict[str, Any]:
        escalations = OperationalOrchestrationResilienceService.generate_automated_escalations(
            db,
            organization_id=organization_id,
            incidents=incidents,
            actor_user_id=actor_user_id,
        )
        recommendations = OperationalOrchestrationResilienceService.generate_dispatch_recommendations(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            limit=50,
        )
        recovery = OperationalOrchestrationResilienceService.run_automated_recovery(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
        )
        resilience = OperationalOrchestrationResilienceService.resolve_resilience_state(
            db,
            organization_id=organization_id,
            incidents=incidents,
            recovery_operations=recovery,
            actor_user_id=actor_user_id,
        )
        forecasts = OperationalOrchestrationResilienceService.generate_predictive_sla_risk_engine(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            incidents=incidents,
        )
        driver_reliability = OperationalOrchestrationResilienceService.generate_driver_reliability_intelligence(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
        )
        rider_risk = OperationalOrchestrationResilienceService.generate_rider_operational_risk_detection(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
        )
        regional_forecasts = OperationalOrchestrationResilienceService.generate_regional_mobility_intelligence(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            incidents=incidents,
        )
        proactive_recovery = OperationalOrchestrationResilienceService.generate_predictive_recovery_coordination(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            forecasts=forecasts,
            driver_reliability=driver_reliability,
            regional_forecasts=regional_forecasts,
        )
        autonomous_decisions = OperationalOrchestrationResilienceService.execute_autonomous_decision_engine(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            escalations=escalations,
            recommendations=recommendations,
            recovery_operations=recovery,
            predictive_recovery=proactive_recovery,
            forecasts=forecasts,
            resilience_state=resilience,
        )
        coordination_layer = OperationalOrchestrationResilienceService.build_multi_agent_operational_coordination_layer(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            escalations=escalations,
            recommendations=recommendations,
            recovery_operations=recovery,
            proactive_recovery=proactive_recovery,
            forecasts=forecasts,
            driver_reliability=driver_reliability,
            regional_forecasts=regional_forecasts,
            resilience_state=resilience,
        )
        consensus = OperationalOrchestrationResilienceService.execute_agent_consensus_infrastructure(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            coordination_layer=coordination_layer,
            resilience_state=resilience,
        )
        negotiation = OperationalOrchestrationResilienceService.execute_autonomous_negotiation_framework(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            coordination_layer=coordination_layer,
            consensus=consensus,
        )
        simulations = OperationalOrchestrationResilienceService.run_operational_simulation_engine(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            incidents=incidents,
            forecasts=forecasts,
            resilience_state=resilience,
            recommendations=recommendations,
        )
        cross_agent_recovery = OperationalOrchestrationResilienceService.execute_cross_agent_recovery_coordination(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            resilience_state=resilience,
            autonomous_recovery_chain=list(autonomous_decisions.get("autonomous_recovery_chain") or []),
            consensus=consensus,
            negotiation=negotiation,
        )
        shared_memory = OperationalOrchestrationResilienceService.build_shared_operational_memory_layer(
            organization_id=organization_id,
            incidents=incidents,
            resilience_state=resilience,
            forecasts=forecasts,
            driver_reliability=driver_reliability,
            regional_forecasts=regional_forecasts,
            proactive_recovery=proactive_recovery,
            consensus=consensus,
            simulations=simulations,
            cross_agent_recovery=cross_agent_recovery,
        )
        shared_memory = OperationalOrchestrationResilienceService.persist_shared_operational_memory_snapshot(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            memory_snapshot=shared_memory,
        )
        authority_session: dict[str, Any]
        if actor_user_id:
            authority_session = OperationalOrchestrationResilienceService.issue_authenticated_operational_session(
                db,
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                role="recovery_coordinator",
                requested_capabilities=[
                    "recovery.execute",
                    "rollback.execute",
                    "snapshot.read",
                    "snapshot.hydrate",
                    "orchestration.activate",
                ],
            )
        else:
            authority_session = {
                "session_id": "",
                "organization_id": organization_id,
                "actor_user_id": "",
                "role": "dispatcher",
                "capabilities": [],
                "issued_at": now().isoformat(),
                "expires_at": now().isoformat(),
                "signature": "",
                "signature_material": {},
                "state": "unauthenticated",
            }
        authority_validation = OperationalOrchestrationResilienceService.validate_authenticated_operational_session(
            db,
            organization_id=organization_id,
            session_payload=authority_session,
            required_capability="orchestration.activate",
        )
        controlled_recovery = OperationalOrchestrationResilienceService.execute_controlled_recovery_execution(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            authority_session=authority_session,
            recovery_actions=[
                item
                for item in list(consensus.get("executed") or [])
                if "recovery" in str(item.get("decision_type") or "") or "stabilization" in str(item.get("decision_type") or "")
            ],
        )
        hydration_recovery = OperationalOrchestrationResilienceService.run_authenticated_hydration_recovery(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            authority_session=authority_session,
        )
        replayable = OperationalOrchestrationResilienceService.replayable_automation_rebuild(
            db,
            organization_id=organization_id,
            limit=500,
        )
        prediction_rebuild = OperationalOrchestrationResilienceService.replayable_prediction_rebuild(
            db,
            organization_id=organization_id,
            limit=500,
        )
        autonomous_rebuild = OperationalOrchestrationResilienceService.replayable_autonomous_decision_rebuild(
            db,
            organization_id=organization_id,
            limit=500,
        )
        distributed_rebuild = OperationalOrchestrationResilienceService.replayable_distributed_coordination_rebuild(
            db,
            organization_id=organization_id,
            limit=500,
        )
        runtime_integrity = OperationalOrchestrationResilienceService.validate_runtime_integrity_protection(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            authority_session=authority_session,
            distributed_rebuild=distributed_rebuild,
        )
        authority_rebuild = OperationalOrchestrationResilienceService.replayable_authority_rebuild(
            db,
            organization_id=organization_id,
            limit=500,
        )
        intelligence_timeline = OperationalOrchestrationResilienceService.build_operational_intelligence_timeline(
            db,
            organization_id=organization_id,
            limit=500,
        )

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "automated_incident_escalations": escalations,
            "dispatch_recommendations": recommendations,
            "automated_recovery_operations": recovery,
            "predictive_sla_risk_engine": forecasts,
            "driver_reliability_intelligence": driver_reliability,
            "rider_operational_risk_detection": rider_risk,
            "regional_mobility_intelligence": regional_forecasts,
            "predictive_recovery_coordination": proactive_recovery,
            "autonomous_operational_decisions": autonomous_decisions,
            "multi_agent_operational_coordination": {
                "coordination_layer": coordination_layer,
                "agent_consensus": consensus,
                "autonomous_negotiation_framework": negotiation,
                "operational_simulation_engine": simulations,
                "cross_agent_recovery_coordination": cross_agent_recovery,
                "shared_operational_memory_layer": shared_memory,
            },
            "controlled_authenticated_operational_authority": {
                "authenticated_orchestration_session": authority_session,
                "authority_validation": authority_validation,
                "supervised_execution_activation": controlled_recovery,
                "authenticated_hydration_recovery": hydration_recovery,
                "runtime_integrity_protection": runtime_integrity,
            },
            "operational_intelligence_timeline": intelligence_timeline,
            "resilience_state_machine": resilience,
            "replayable_automation_rebuild": replayable,
            "replayable_prediction_rebuild": prediction_rebuild,
            "replayable_autonomous_decision_rebuild": autonomous_rebuild,
            "replayable_distributed_coordination_rebuild": distributed_rebuild,
            "replayable_authority_rebuild": authority_rebuild,
            "backend_authoritative": True,
            "replay_safe": True,
            "cross_role_synchronized": True,
        }
