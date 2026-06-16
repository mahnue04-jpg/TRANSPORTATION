"""Adaptive operational forecasting on top of decision intelligence and memory fabric."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.modules.health_isf.adaptive_forecast_models import AdaptiveForecastSnapshot
from app.modules.health_isf.continuity_prediction_service import ContinuityPredictionService
from app.modules.health_isf.resilience_scoring_engine import ResilienceScoringEngine


class OperationalForecastEngine:
    @staticmethod
    def build_snapshot(*, organization_id: str, decision: dict[str, Any], memory: dict[str, Any], sync: dict[str, Any]) -> dict[str, Any]:
        pressure = decision.get("pressure_analysis") or {}
        continuity = ContinuityPredictionService.build(decision=decision, memory=memory, sync=sync)
        resilience = ResilienceScoringEngine.build(decision=decision, memory=memory, continuity=continuity)

        congestion = min(1.0, float(pressure.get("regional_congestion") or 0.0) * 0.6 + float(pressure.get("incident_clustering") or 0.0) * 0.4)
        cascade = min(1.0, float(pressure.get("escalation_surge") or 0.0) * 0.6 + float(memory.get("pattern_summary", {}).get("incident_growth_ratio") or 0.0) * 0.4)
        provider_overload = min(1.0, float(pressure.get("provider_queue_pressure") or 0.0) * 0.7 + float(congestion) * 0.3)
        dispatch_bottleneck = min(1.0, float(pressure.get("driver_load_pressure") or 0.0) * 0.65 + float(provider_overload) * 0.35)

        snapshot = AdaptiveForecastSnapshot(
            organization_id=organization_id,
            generated_at=datetime.utcnow().isoformat(),
            recommendation_only=True,
            explainable=True,
            confidence_scored=True,
            auditable_reasoning_chains=True,
            tenant_scoped=True,
            replay_safe=True,
            escalation_cascade_forecast={"value": round(cascade, 4), "confidence": continuity["confidence"], "reasoning_chain": continuity["reasoning_chain"]},
            congestion_chain_prediction={"value": round(congestion, 4), "confidence": resilience["confidence"], "reasoning_chain": resilience["reasoning_chain"]},
            continuity_degradation_forecast=continuity,
            provider_overload_prediction={"value": round(provider_overload, 4), "confidence": continuity["confidence"], "reasoning_chain": continuity["reasoning_chain"]},
            dispatch_bottleneck_forecast={"value": round(dispatch_bottleneck, 4), "confidence": resilience["confidence"], "reasoning_chain": resilience["reasoning_chain"]},
            recovery_timeline_estimation={"minutes": continuity["recovery_timeline_minutes"], "confidence": continuity["confidence"], "reasoning_chain": continuity["reasoning_chain"]},
            operational_resilience_scoring=resilience,
        )
        return snapshot.to_dict()
