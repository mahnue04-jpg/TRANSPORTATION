"""Explainable recommendation contracts for operational decision intelligence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class RecommendationExplanation:
    recommendation_id: str
    summary: str
    evidence_chain: list[dict[str, Any]] = field(default_factory=list)
    reasoning_chain: list[str] = field(default_factory=list)
    confidence: float = 0.0
    operational_impact: str = ""
    sla_impact_estimation: str = "low"
    auditable: bool = True
    no_hidden_inference_paths: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = round(float(self.confidence), 4)
        return payload


@dataclass(slots=True)
class ExplainableRecommendation:
    recommendation_id: str
    recommendation_type: str
    confidence: float
    evidence_chain: list[dict[str, Any]]
    reasoning_chain: list[str]
    operational_impact_reasoning: str
    sla_impact_estimation: str
    recommendation_only: bool = True
    approval_governed: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = round(float(self.confidence), 4)
        return payload
