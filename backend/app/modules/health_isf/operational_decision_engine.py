"""Explainable operational decision engine for recommendation-only outputs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.health_isf.confidence_scoring_engine import ConfidenceScoringEngine
from app.modules.health_isf.explainable_recommendation_models import ExplainableRecommendation
from app.modules.health_isf.operational_decision_models import OperationalDecisionCandidate, OperationalPressureSnapshot
from app.modules.health_isf.operational_priority_service import OperationalPriorityService
from app.modules.health_isf.operational_reasoning_chain import OperationalReasoningChain
from app.modules.health_isf.recommendation_explanation_service import RecommendationExplanationService


class OperationalDecisionEngine:
    @staticmethod
    def _stable_id(organization_id: str, recommendation_type: str, material: dict[str, Any]) -> str:
        payload = {
            "organization_id": organization_id,
            "recommendation_type": recommendation_type,
            "material": material,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
        return f"oprec_{digest}"

    @classmethod
    def build_recommendations(
        cls,
        *,
        organization_id: str,
        pressure: OperationalPressureSnapshot,
        forecast: dict[str, Any],
        dispatch_snapshot: dict[str, Any],
    ) -> list[OperationalDecisionCandidate]:
        recommendation_types = [
            "escalation_prioritization",
            "dispatch_rebalance",
            "congestion_reroute",
            "workload_balance",
            "continuity_risk_warning",
            "resource_pressure_watch",
        ]

        dispatch_total = int((dispatch_snapshot.get("summary") or {}).get("total") or 0)
        dispatch_emergency = int((dispatch_snapshot.get("summary") or {}).get("emergency_recommendations") or 0)

        candidates: list[OperationalDecisionCandidate] = []
        for recommendation_type in recommendation_types:
            severity_weight = OperationalPriorityService.severity_weight(
                recommendation_type=recommendation_type,
                pressure=pressure,
            )
            confidence = ConfidenceScoringEngine.score(
                pressure=pressure.to_dict(),
                forecast=forecast,
                severity_weight=severity_weight,
            )
            escalation_score = OperationalPriorityService.escalation_score(
                severity_weight=severity_weight,
                pressure=pressure,
            )
            priority = OperationalPriorityService.priority_score(
                severity_weight=severity_weight,
                escalation_score=escalation_score,
                confidence=confidence,
            )

            context = {
                "pressure": pressure.to_dict(),
                "forecast": forecast,
                "dispatch_total": dispatch_total,
                "dispatch_emergency": dispatch_emergency,
            }
            reasoning_chain = OperationalReasoningChain.build(
                context=context,
                recommendation_type=recommendation_type,
            )
            evidence_chain = [
                {"key": "dispatch_total", "value": dispatch_total, "source": "dispatch_intelligence.summary.total"},
                {
                    "key": "dispatch_emergency",
                    "value": dispatch_emergency,
                    "source": "dispatch_intelligence.summary.emergency_recommendations",
                },
                {"key": "pressure", "value": pressure.to_dict(), "source": "operational_priority_service"},
                {"key": "forecast", "value": forecast, "source": "operational_forecast_service"},
            ]

            recommendation_id = cls._stable_id(
                organization_id,
                recommendation_type,
                {
                    "priority": priority,
                    "confidence": confidence,
                    "dispatch_total": dispatch_total,
                },
            )

            sla_impact = "high" if priority >= 0.82 else "medium" if priority >= 0.62 else "low"
            operational_impact = (
                f"{recommendation_type} may reduce SLA risk by prioritizing governed operator action. "
                f"Current pressure index {pressure.driver_load_pressure:.2f}/{pressure.provider_queue_pressure:.2f}."
            )

            explanation = RecommendationExplanationService.build(
                recommendation_id=recommendation_id,
                recommendation_type=recommendation_type,
                confidence=confidence,
                evidence_chain=evidence_chain,
                reasoning_chain=reasoning_chain,
                operational_impact_reasoning=operational_impact,
                sla_impact_estimation=sla_impact,
            )

            explainable = ExplainableRecommendation(
                recommendation_id=recommendation_id,
                recommendation_type=recommendation_type,
                confidence=confidence,
                evidence_chain=evidence_chain,
                reasoning_chain=reasoning_chain,
                operational_impact_reasoning=operational_impact,
                sla_impact_estimation=sla_impact,
                recommendation_only=True,
                approval_governed=True,
            )

            candidate = OperationalDecisionCandidate(
                recommendation_id=recommendation_id,
                recommendation_type=recommendation_type,
                priority_score=priority,
                escalation_score=escalation_score,
                severity_weight=severity_weight,
                confidence=confidence,
                sla_impact=sla_impact,
                operational_impact=operational_impact,
                evidence_chain=[
                    *evidence_chain,
                    {"key": "explanation", "value": explanation, "source": "recommendation_explanation_service"},
                    {"key": "explainable_contract", "value": explainable.to_dict(), "source": "explainable_recommendation_models"},
                ],
                reasoning_chain=reasoning_chain,
                recommendation_only=True,
                approval_required=True,
            )
            candidates.append(candidate)

        return sorted(candidates, key=lambda item: item.priority_score, reverse=True)
