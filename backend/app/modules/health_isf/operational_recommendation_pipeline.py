"""Operational recommendation pipeline orchestrating pressure, forecast, and explainable ranking."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.modules.health_isf.operational_decision_engine import OperationalDecisionEngine
from app.modules.health_isf.operational_decision_models import OperationalDecisionSnapshot
from app.modules.health_isf.operational_forecast_service import OperationalForecastService
from app.modules.health_isf.operational_priority_service import OperationalPriorityService


class OperationalRecommendationPipeline:
    @staticmethod
    def build_snapshot(
        *,
        organization_id: str,
        telemetry_metrics: dict[str, Any],
        geospatial_snapshot: dict[str, Any],
        dispatch_snapshot: dict[str, Any],
        sync_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        pressure = OperationalPriorityService.build_pressure_snapshot(
            metrics=telemetry_metrics,
            geospatial_snapshot=geospatial_snapshot,
            sync_snapshot=sync_snapshot,
        )
        forecast = OperationalForecastService.build_forecast(
            pressure=pressure,
            sync_snapshot=sync_snapshot,
        )
        recommendations = OperationalDecisionEngine.build_recommendations(
            organization_id=organization_id,
            pressure=pressure,
            forecast=forecast,
            dispatch_snapshot=dispatch_snapshot,
        )

        snapshot = OperationalDecisionSnapshot(
            organization_id=organization_id,
            generated_at=datetime.utcnow().isoformat(),
            recommendation_only=True,
            approval_governed=True,
            backend_authoritative=True,
            tenant_scoped=True,
            replay_safe=True,
            websocket_synchronized=True,
            pressure_analysis=pressure,
            forecast=forecast,
            recommendations=recommendations,
        )
        payload = snapshot.to_dict()
        payload["summary"] = {
            "total_recommendations": len(recommendations),
            "operational_prioritization": True,
            "escalation_scoring": True,
            "dispatch_recommendation_ranking": True,
            "incident_severity_weighting": True,
            "workload_balancing_recommendations": True,
            "resource_pressure_forecasting": True,
            "explainable": True,
            "confidence_scored": True,
            "recommendation_only": True,
            "approval_governed": True,
            "no_hidden_inference_paths": True,
        }
        return payload
