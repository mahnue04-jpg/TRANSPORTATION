"""Pipeline for supervised multi-agent operational coordination."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.modules.health_isf.multi_agent_coordination_engine import MultiAgentCoordinationEngine
from app.modules.health_isf.operational_coordination_models import OperationalCoordinationSnapshot
from app.modules.health_isf.workload_distribution_engine import WorkloadDistributionEngine


class CoordinationRecommendationPipeline:
    @staticmethod
    def build_snapshot(
        *,
        organization_id: str,
        metrics: dict[str, Any],
        decision: dict[str, Any],
        memory: dict[str, Any],
        adaptive_forecast: dict[str, Any],
        sync_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        workload_summary = WorkloadDistributionEngine.summarize(
            metrics=metrics,
            forecast=decision.get("forecast") or {},
            decision=decision,
        )
        recommendations = MultiAgentCoordinationEngine.build_recommendations(
            organization_id=organization_id,
            decision=decision,
            memory=memory,
            adaptive_forecast=adaptive_forecast,
            workload_summary=workload_summary,
            sync_snapshot=sync_snapshot,
        )
        snapshot = OperationalCoordinationSnapshot(
            organization_id=organization_id,
            generated_at=datetime.utcnow().isoformat(),
            backend_authoritative=True,
            tenant_scoped=True,
            replay_safe=True,
            websocket_synchronized=True,
            explainable=True,
            auditable=True,
            recommendation_only=True,
            coordination_summary={
                "cross_surface_operational_coordination": True,
                "synchronized_escalation_awareness": True,
                "incident_collaboration_recommendations": True,
                "provider_driver_balancing_recommendations": True,
                "operational_workload_distribution": True,
                "continuity_aware_coordination": True,
                "regional_coordination_intelligence": True,
                "replay_safe_coordination_synchronization": True,
                "workload_summary": workload_summary,
            },
            recommendations=recommendations,
        )
        return snapshot.to_dict()
