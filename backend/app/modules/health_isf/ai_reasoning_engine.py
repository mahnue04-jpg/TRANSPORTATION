"""Controlled read-only AI reasoning over enterprise operational state."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.modules.health_isf.ai_governance_engine import AIGovernanceEngine
from app.modules.health_isf.ai_audit_engine import AIAuditEngine
from app.modules.health_isf.anomaly_detection import detect_anomalies
from app.modules.health_isf.enterprise_feature_flags import is_feature_enabled
from app.modules.health_isf.explainability_contract import build_explainability
from app.modules.health_isf.incident_analysis import analyze_incident_state
from app.modules.health_isf.incident_detection_engine import IncidentDetectionEngine
from app.modules.health_isf.memory_service import OperationalMemoryService
from app.modules.health_isf.operations import build_operational_metrics
from app.modules.health_isf.realtime import get_broadcaster
from app.modules.health_isf.realtime_service import RetryQueueService


class AIReasoningEngine:
    @classmethod
    def reason_incidents(
        cls,
        db: Session,
        *,
        organization_id: str,
        user: UserContext,
    ) -> dict[str, Any]:
        if not is_feature_enabled("ENABLE_AI_REASONING", role=user.role):
            return {
                "organization_id": organization_id,
                "enabled": False,
                "reasoning": [],
                "read_only": True,
            }

        metrics = build_operational_metrics(db, organization_id=organization_id)
        websocket_health = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
        queue_stats = RetryQueueService.get_queue_stats(db, organization_id=organization_id)
        live_incidents = IncidentDetectionEngine.detect(db, organization_id=organization_id)

        findings = analyze_incident_state(
            organization_id=organization_id,
            metrics=metrics,
            websocket_health=websocket_health,
            queue_stats=queue_stats,
            live_incidents=live_incidents,
        )

        recommendations = [
            build_explainability(
                reason=finding.get("type", "incident_reasoning"),
                evidence=finding.get("evidence", []),
                confidence=finding.get("confidence", 0.5),
                affected_systems=finding.get("affected_systems", []),
                operational_impact=finding.get("operational_impact", "Operational impact under review."),
                recommended_action=finding.get("recommended_action", "Review incident and apply controlled workflow."),
                rollback_impact=finding.get("rollback_impact", "No direct runtime changes applied."),
                tenant_scope=organization_id,
                reasoning_trace=finding.get("reasoning_trace", []),
            )
            for finding in findings
        ]

        for incident in live_incidents:
            OperationalMemoryService.record_incident(
                db,
                organization_id=organization_id,
                actor_user_id=user.user_id,
                incident=incident,
                replay_hint=str(incident.get("incident_id") or ""),
            )

        if recommendations:
            AIAuditEngine.record_decision(
                db,
                organization_id=organization_id,
                actor_user_id=user.user_id,
                decision={
                    "decision_id": f"reasoning:{organization_id}",
                    "risk_level": "informational",
                    "reasoning_summary": f"Generated {len(recommendations)} read-only incident recommendations",
                    "requires_human_approval": True,
                    "execution_mode": "read_only",
                },
                supporting_signals=[
                    {"metrics": metrics},
                    {"websocket_health": websocket_health},
                    {"queue_stats": queue_stats},
                ],
            )
            for recommendation in recommendations:
                AIGovernanceEngine.register_reasoning_event(
                    db,
                    organization_id=organization_id,
                    actor_user_id=user.user_id,
                    reasoning=recommendation,
                )

        return {
            "organization_id": organization_id,
            "enabled": True,
            "read_only": True,
            "incident_count": len(live_incidents),
            "reasoning": recommendations,
        }

    @classmethod
    def reason_anomalies(
        cls,
        db: Session,
        *,
        organization_id: str,
        user: UserContext,
    ) -> dict[str, Any]:
        if not is_feature_enabled("ENABLE_AI_REASONING", role=user.role):
            return {
                "organization_id": organization_id,
                "enabled": False,
                "anomalies": [],
                "read_only": True,
            }

        metrics = build_operational_metrics(db, organization_id=organization_id)
        websocket_health = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
        features = OperationalMemoryService.history_features(
            db,
            organization_id=organization_id,
            role=user.role,
        )

        anomalies = detect_anomalies(
            organization_id=organization_id,
            metrics=metrics,
            websocket_health=websocket_health,
            memory_features=features,
        )

        contracts = [
            build_explainability(
                reason=item.get("anomaly_type", "anomaly_detected"),
                evidence=item.get("evidence", []),
                confidence=item.get("confidence", 0.5),
                affected_systems=["operations", "dispatch"],
                operational_impact="Observed anomaly pattern in operational telemetry.",
                recommended_action="Investigate anomaly and run controlled operator playbook.",
                rollback_impact="Recommendation-only output; no auto execution.",
                tenant_scope=organization_id,
                reasoning_trace=item.get("reasoning_trace", []),
            )
            for item in anomalies
        ]

        return {
            "organization_id": organization_id,
            "enabled": True,
            "read_only": True,
            "features": features,
            "anomalies": contracts,
        }

    @classmethod
    def risk_score(
        cls,
        db: Session,
        *,
        organization_id: str,
        user: UserContext,
    ) -> dict[str, Any]:
        if not is_feature_enabled("ENABLE_AI_REASONING", role=user.role):
            return {
                "organization_id": organization_id,
                "enabled": False,
                "risk_score": 0.0,
                "read_only": True,
            }

        metrics = build_operational_metrics(db, organization_id=organization_id)
        websocket_health = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
        queue_stats = RetryQueueService.get_queue_stats(db, organization_id=organization_id)
        features = OperationalMemoryService.history_features(db, organization_id=organization_id, role=user.role)

        pending = float(metrics.get("unassigned_rides") or metrics.get("pending_rides") or 0)
        utilization = float(metrics.get("driver_utilization_percent") or 0)
        disconnects = float(websocket_health.get("disconnects_last_5m") or 0)
        queued = float(queue_stats.get("queued") or 0)
        growth = float(features.get("incident_growth_ratio") or 0)

        risk = (
            min(0.35, pending / 40.0)
            + min(0.2, utilization / 500.0)
            + min(0.15, disconnects / 50.0)
            + min(0.15, queued / 120.0)
            + min(0.15, growth / 10.0)
        )

        return {
            "organization_id": organization_id,
            "enabled": True,
            "read_only": True,
            "risk_score": round(max(0.0, min(1.0, risk)), 4),
            "confidence": round(min(0.98, 0.55 + risk * 0.4), 4),
            "reasoning_trace": [
                "Aggregated queue pressure, utilization, websocket disconnect trends, and incident growth",
                "Applied bounded weighted risk model for controlled operational scoring",
            ],
        }
