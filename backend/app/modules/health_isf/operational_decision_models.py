"""Operational decision intelligence data contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class OperationalPressureSnapshot:
    regional_congestion: float
    driver_load_pressure: float
    provider_queue_pressure: float
    escalation_surge: float
    incident_clustering: float
    continuity_degradation_risk: float

    def to_dict(self) -> dict[str, float]:
        return {
            "regional_congestion": round(float(self.regional_congestion), 4),
            "driver_load_pressure": round(float(self.driver_load_pressure), 4),
            "provider_queue_pressure": round(float(self.provider_queue_pressure), 4),
            "escalation_surge": round(float(self.escalation_surge), 4),
            "incident_clustering": round(float(self.incident_clustering), 4),
            "continuity_degradation_risk": round(float(self.continuity_degradation_risk), 4),
        }


@dataclass(slots=True)
class OperationalDecisionCandidate:
    recommendation_id: str
    recommendation_type: str
    priority_score: float
    escalation_score: float
    severity_weight: float
    confidence: float
    sla_impact: str
    operational_impact: str
    evidence_chain: list[dict[str, Any]] = field(default_factory=list)
    reasoning_chain: list[str] = field(default_factory=list)
    recommendation_only: bool = True
    approval_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["priority_score"] = round(float(self.priority_score), 4)
        payload["escalation_score"] = round(float(self.escalation_score), 4)
        payload["severity_weight"] = round(float(self.severity_weight), 4)
        payload["confidence"] = round(float(self.confidence), 4)
        return payload


@dataclass(slots=True)
class OperationalDecisionSnapshot:
    organization_id: str
    generated_at: str
    recommendation_only: bool
    approval_governed: bool
    backend_authoritative: bool
    tenant_scoped: bool
    replay_safe: bool
    websocket_synchronized: bool
    pressure_analysis: OperationalPressureSnapshot
    forecast: dict[str, Any]
    recommendations: list[OperationalDecisionCandidate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "generated_at": self.generated_at,
            "recommendation_only": bool(self.recommendation_only),
            "approval_governed": bool(self.approval_governed),
            "backend_authoritative": bool(self.backend_authoritative),
            "tenant_scoped": bool(self.tenant_scoped),
            "replay_safe": bool(self.replay_safe),
            "websocket_synchronized": bool(self.websocket_synchronized),
            "pressure_analysis": self.pressure_analysis.to_dict(),
            "forecast": self.forecast,
            "recommendations": [item.to_dict() for item in self.recommendations],
        }
