"""Dispatch intelligence models with explainable and confidence-scored outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DispatchRecommendation:
    recommendation_id: str
    organization_id: str
    ride_id: str
    recommendation_type: str
    target_id: str
    confidence: float
    explainability: list[str]
    evidence: dict[str, Any] = field(default_factory=dict)
    approval_required: bool = True
    execution_mode: str = "recommendation_only"


@dataclass(slots=True)
class DispatchRecommendationBundle:
    organization_id: str
    recommendations: list[DispatchRecommendation]
    assignment_recommendations: int
    emergency_recommendations: int
    generated_at: str
