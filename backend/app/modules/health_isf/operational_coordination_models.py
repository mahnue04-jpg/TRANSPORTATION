"""Data contracts for supervised multi-agent operational coordination."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CoordinationRecommendation:
    recommendation_id: str
    coordination_type: str
    confidence: float
    workload_score: float
    continuity_score: float
    regional_score: float
    evidence_chain: list[dict[str, Any]] = field(default_factory=list)
    reasoning_chain: list[str] = field(default_factory=list)
    recommendation_only: bool = True
    approval_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = round(float(self.confidence), 4)
        payload["workload_score"] = round(float(self.workload_score), 4)
        payload["continuity_score"] = round(float(self.continuity_score), 4)
        payload["regional_score"] = round(float(self.regional_score), 4)
        return payload


@dataclass(slots=True)
class OperationalCoordinationSnapshot:
    organization_id: str
    generated_at: str
    backend_authoritative: bool
    tenant_scoped: bool
    replay_safe: bool
    websocket_synchronized: bool
    explainable: bool
    auditable: bool
    recommendation_only: bool
    coordination_summary: dict[str, Any]
    recommendations: list[CoordinationRecommendation]

    def to_dict(self) -> dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "generated_at": self.generated_at,
            "backend_authoritative": bool(self.backend_authoritative),
            "tenant_scoped": bool(self.tenant_scoped),
            "replay_safe": bool(self.replay_safe),
            "websocket_synchronized": bool(self.websocket_synchronized),
            "explainable": bool(self.explainable),
            "auditable": bool(self.auditable),
            "recommendation_only": bool(self.recommendation_only),
            "coordination_summary": self.coordination_summary,
            "recommendations": [item.to_dict() for item in self.recommendations],
        }
