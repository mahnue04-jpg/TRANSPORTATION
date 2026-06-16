"""Adaptive forecasting contracts for supervised operational coordination."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AdaptiveForecastSnapshot:
    organization_id: str
    generated_at: str
    recommendation_only: bool
    explainable: bool
    confidence_scored: bool
    auditable_reasoning_chains: bool
    tenant_scoped: bool
    replay_safe: bool
    escalation_cascade_forecast: dict[str, Any]
    congestion_chain_prediction: dict[str, Any]
    continuity_degradation_forecast: dict[str, Any]
    provider_overload_prediction: dict[str, Any]
    dispatch_bottleneck_forecast: dict[str, Any]
    recovery_timeline_estimation: dict[str, Any]
    operational_resilience_scoring: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "generated_at": self.generated_at,
            "recommendation_only": bool(self.recommendation_only),
            "explainable": bool(self.explainable),
            "confidence_scored": bool(self.confidence_scored),
            "auditable_reasoning_chains": bool(self.auditable_reasoning_chains),
            "tenant_scoped": bool(self.tenant_scoped),
            "replay_safe": bool(self.replay_safe),
            "escalation_cascade_forecast": self.escalation_cascade_forecast,
            "congestion_chain_prediction": self.congestion_chain_prediction,
            "continuity_degradation_forecast": self.continuity_degradation_forecast,
            "provider_overload_prediction": self.provider_overload_prediction,
            "dispatch_bottleneck_forecast": self.dispatch_bottleneck_forecast,
            "recovery_timeline_estimation": self.recovery_timeline_estimation,
            "operational_resilience_scoring": self.operational_resilience_scoring,
        }
