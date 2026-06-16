"""Controlled dispatch intelligence orchestrator (recommendations only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.health_isf.dispatch_models import DispatchRecommendationBundle
from app.modules.health_isf.routing_recommendation_engine import RoutingRecommendationEngine


class DispatchIntelligenceEngine:
    @staticmethod
    def build_bundle(db: Session, organization_id: str) -> dict[str, Any]:
        recommendations = RoutingRecommendationEngine.build_recommendations(db, organization_id)
        bundle = DispatchRecommendationBundle(
            organization_id=organization_id,
            recommendations=recommendations,
            assignment_recommendations=sum(1 for item in recommendations if item.recommendation_type == "assignment_recommendation"),
            emergency_recommendations=sum(1 for item in recommendations if item.recommendation_type == "emergency_priority_assignment"),
            generated_at=datetime.utcnow().isoformat(),
        )

        return {
            "organization_id": bundle.organization_id,
            "generated_at": bundle.generated_at,
            "recommendation_only": True,
            "approval_required": True,
            "unrestricted_execution": False,
            "recommendations": [
                {
                    "recommendation_id": item.recommendation_id,
                    "ride_id": item.ride_id,
                    "recommendation_type": item.recommendation_type,
                    "target_id": item.target_id,
                    "confidence": item.confidence,
                    "explainability": item.explainability,
                    "evidence": item.evidence,
                    "approval_required": item.approval_required,
                    "execution_mode": item.execution_mode,
                }
                for item in bundle.recommendations
            ],
            "summary": {
                "total": len(bundle.recommendations),
                "assignment_recommendations": bundle.assignment_recommendations,
                "emergency_recommendations": bundle.emergency_recommendations,
                "confidence_scored": True,
                "explainable": True,
            },
        }
