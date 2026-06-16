"""Recommendation explanation service for audit-safe operational decisioning."""

from __future__ import annotations

from typing import Any

from app.modules.health_isf.explainable_recommendation_models import RecommendationExplanation


class RecommendationExplanationService:
    @staticmethod
    def build(
        *,
        recommendation_id: str,
        recommendation_type: str,
        confidence: float,
        evidence_chain: list[dict[str, Any]],
        reasoning_chain: list[str],
        operational_impact_reasoning: str,
        sla_impact_estimation: str,
    ) -> dict[str, Any]:
        explanation = RecommendationExplanation(
            recommendation_id=recommendation_id,
            summary=(
                f"{recommendation_type} generated with confidence {confidence:.2f}. "
                "Output is explainable, auditable, and recommendation-only."
            ),
            evidence_chain=evidence_chain,
            reasoning_chain=reasoning_chain,
            confidence=confidence,
            operational_impact=operational_impact_reasoning,
            sla_impact_estimation=sla_impact_estimation,
            auditable=True,
            no_hidden_inference_paths=True,
        )
        return explanation.to_dict()
