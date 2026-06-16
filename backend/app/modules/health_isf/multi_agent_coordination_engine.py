"""Supervised multi-agent coordination recommendations over existing operational intelligence."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.health_isf.operational_collaboration_service import OperationalCollaborationService
from app.modules.health_isf.operational_coordination_models import CoordinationRecommendation


class MultiAgentCoordinationEngine:
    @staticmethod
    def _stable_id(organization_id: str, coordination_type: str, material: dict[str, Any]) -> str:
        digest = hashlib.sha256(
            json.dumps({"organization_id": organization_id, "coordination_type": coordination_type, **material}, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]
        return f"coord_{digest}"

    @classmethod
    def build_recommendations(
        cls,
        *,
        organization_id: str,
        decision: dict[str, Any],
        memory: dict[str, Any],
        adaptive_forecast: dict[str, Any],
        workload_summary: dict[str, Any],
        sync_snapshot: dict[str, Any],
    ) -> list[CoordinationRecommendation]:
        recommendation_types = [
            "cross_surface_operational_coordination",
            "synchronized_escalation_awareness",
            "incident_collaboration_recommendation",
            "provider_driver_balance_recommendation",
            "continuity_aware_coordination",
            "regional_coordination_intelligence",
        ]
        pattern_summary = memory.get("pattern_summary") or {}
        recommendations: list[CoordinationRecommendation] = []
        for coordination_type in recommendation_types:
            continuity_score = min(
                1.0,
                float((adaptive_forecast.get("continuity_degradation_forecast") or {}).get("continuity_risk") or 0.0) * 0.6
                + float((adaptive_forecast.get("operational_resilience_scoring") or {}).get("resilience_score") or 0.0) * 0.1
                + float((decision.get("pressure_analysis") or {}).get("continuity_degradation_risk") or 0.0) * 0.3,
            )
            workload_score = min(
                1.0,
                float(workload_summary.get("provider_driver_balance") or 0.0) * 0.55
                + float(workload_summary.get("operational_distribution") or 0.0) * 0.45,
            )
            regional_score = min(
                1.0,
                float((decision.get("pressure_analysis") or {}).get("regional_congestion") or 0.0) * 0.55
                + float(pattern_summary.get("incident_growth_ratio") or 0.0) * 0.2
                + float((adaptive_forecast.get("congestion_chain_prediction") or {}).get("value") or 0.0) * 0.25,
            )
            confidence = max(0.05, min(0.99, 1.0 - (continuity_score * 0.35 + workload_score * 0.35 + regional_score * 0.2)))
            evidence_chain = OperationalCollaborationService.build_evidence_chain(
                coordination_type=coordination_type,
                workload_summary=workload_summary,
                memory_summary=pattern_summary,
                adaptive_forecast=adaptive_forecast,
            )
            reasoning_chain = OperationalCollaborationService.build_reasoning_chain(
                coordination_type=coordination_type,
                memory_summary=pattern_summary,
                sync_snapshot=sync_snapshot,
            )
            recommendations.append(
                CoordinationRecommendation(
                    recommendation_id=cls._stable_id(organization_id, coordination_type, {"workload": workload_score, "regional": regional_score}),
                    coordination_type=coordination_type,
                    confidence=confidence,
                    workload_score=workload_score,
                    continuity_score=continuity_score,
                    regional_score=regional_score,
                    evidence_chain=evidence_chain,
                    reasoning_chain=reasoning_chain,
                    recommendation_only=True,
                    approval_required=True,
                )
            )
        return sorted(recommendations, key=lambda item: (item.continuity_score + item.workload_score + item.regional_score), reverse=True)
