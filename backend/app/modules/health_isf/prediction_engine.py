"""Controlled AI prediction engine using real operational metrics and memory history."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.modules.health_isf.ai_governance_engine import AIGovernanceEngine
from app.modules.health_isf.enterprise_feature_flags import is_feature_enabled
from app.modules.health_isf.memory_service import OperationalMemoryService
from app.modules.health_isf.operations import build_operational_metrics
from app.modules.health_isf.prediction_models import AIPrediction
from app.modules.health_isf.realtime_service import RetryQueueService
from app.modules.health_isf.trend_analysis import TrendAnalysis


class AIPredictionEngine:
    @classmethod
    def _prediction_confidence(cls, base: float, evidence_points: int) -> float:
        return round(max(0.0, min(0.99, base + min(0.25, evidence_points * 0.03))), 4)

    @classmethod
    def _as_prediction(
        cls,
        *,
        organization_id: str,
        prediction_type: str,
        horizon: str,
        value: float,
        confidence: float,
        evidence: list[dict],
    ) -> dict[str, Any]:
        model = AIPrediction(
            prediction_type=prediction_type,
            horizon=horizon,
            value=round(max(0.0, min(1.0, float(value))), 4),
            confidence=round(max(0.0, min(1.0, float(confidence))), 4),
            evidence=evidence,
            tenant_scope=organization_id,
        )
        return model.model_dump()

    @classmethod
    def predict_sla(
        cls,
        db: Session,
        *,
        organization_id: str,
        user: UserContext,
    ) -> dict[str, Any]:
        if not is_feature_enabled("ENABLE_AI_PREDICTIONS", role=user.role):
            return {"organization_id": organization_id, "enabled": False, "predictions": []}

        metrics = build_operational_metrics(db, organization_id=organization_id)
        trends = TrendAnalysis.compute_trends(db, organization_id=organization_id)
        memory_features = OperationalMemoryService.history_features(db, organization_id=organization_id, role=user.role)

        queue_pressure = float(metrics.get("unassigned_rides") or metrics.get("pending_rides") or 0)
        utilization = float(metrics.get("driver_utilization_percent") or 0)
        retry_pressure = float(trends.get("retry_last_1h") or 0)
        growth = float(memory_features.get("incident_growth_ratio") or 0)

        breach_probability = min(1.0, queue_pressure / 35.0 + utilization / 220.0 + retry_pressure / 80.0 + growth / 8.0)
        evidence = [
            {"queue_pressure": queue_pressure},
            {"driver_utilization_percent": utilization},
            {"retry_last_1h": retry_pressure},
            {"incident_growth_ratio": growth},
        ]
        prediction = cls._as_prediction(
            organization_id=organization_id,
            prediction_type="sla_breach_probability",
            horizon="next_60m",
            value=breach_probability,
            confidence=cls._prediction_confidence(0.55, len(evidence)),
            evidence=evidence,
        )
        OperationalMemoryService.record_prediction(
            db,
            organization_id=organization_id,
            actor_user_id=user.user_id,
            prediction=prediction,
            replay_hint=f"sla:{organization_id}:{prediction['value']}",
        )
        AIGovernanceEngine.register_prediction_event(
            db,
            organization_id=organization_id,
            actor_user_id=user.user_id,
            prediction=prediction,
        )
        return {"organization_id": organization_id, "enabled": True, "predictions": [prediction]}

    @classmethod
    def predict_load(
        cls,
        db: Session,
        *,
        organization_id: str,
        user: UserContext,
    ) -> dict[str, Any]:
        if not is_feature_enabled("ENABLE_AI_PREDICTIONS", role=user.role):
            return {"organization_id": organization_id, "enabled": False, "predictions": []}

        metrics = build_operational_metrics(db, organization_id=organization_id)
        trends = TrendAnalysis.compute_trends(db, organization_id=organization_id)
        memory_features = OperationalMemoryService.history_features(db, organization_id=organization_id, role=user.role)
        queue = RetryQueueService.get_queue_stats(db, organization_id=organization_id)

        rides_last_1h = float(trends.get("rides_last_1h") or 0)
        rides_avg = float(trends.get("rides_avg_hour_6h") or 0)
        demand_ratio = (rides_last_1h / rides_avg) if rides_avg > 0 else 0.0
        retry_queue = float(queue.get("queued") or 0)
        incident_growth = float(memory_features.get("incident_growth_ratio") or 0)
        active_rides = float(metrics.get("active_rides") or 0)

        overload_risk = min(1.0, max(0.0, demand_ratio - 1.0) * 0.45 + retry_queue / 75.0 + incident_growth / 10.0 + active_rides / 90.0)
        evidence = [
            {"demand_ratio": demand_ratio},
            {"retry_queue": retry_queue},
            {"incident_growth_ratio": incident_growth},
            {"active_rides": active_rides},
        ]
        prediction = cls._as_prediction(
            organization_id=organization_id,
            prediction_type="dispatch_overload_risk",
            horizon="next_45m",
            value=overload_risk,
            confidence=cls._prediction_confidence(0.58, len(evidence)),
            evidence=evidence,
        )
        OperationalMemoryService.record_prediction(
            db,
            organization_id=organization_id,
            actor_user_id=user.user_id,
            prediction=prediction,
            replay_hint=f"load:{organization_id}:{prediction['value']}",
        )
        AIGovernanceEngine.register_prediction_event(
            db,
            organization_id=organization_id,
            actor_user_id=user.user_id,
            prediction=prediction,
        )
        return {"organization_id": organization_id, "enabled": True, "predictions": [prediction]}

    @classmethod
    def predict_emergency(
        cls,
        db: Session,
        *,
        organization_id: str,
        user: UserContext,
    ) -> dict[str, Any]:
        if not is_feature_enabled("ENABLE_AI_PREDICTIONS", role=user.role):
            return {"organization_id": organization_id, "enabled": False, "predictions": []}

        trends = TrendAnalysis.compute_trends(db, organization_id=organization_id)
        memory_features = OperationalMemoryService.history_features(db, organization_id=organization_id, role=user.role)

        rides_last_1h = float(trends.get("rides_last_1h") or 0)
        emergency_last_1h = float(trends.get("emergency_last_1h") or 0)
        emergency_ratio = emergency_last_1h / max(1.0, rides_last_1h)
        retry_failed = float(trends.get("retry_failed_last_1h") or 0)
        incident_growth = float(memory_features.get("incident_growth_ratio") or 0)

        surge_risk = min(1.0, emergency_ratio + retry_failed / 40.0 + incident_growth / 12.0)
        evidence = [
            {"emergency_ratio": emergency_ratio},
            {"retry_failed_last_1h": retry_failed},
            {"incident_growth_ratio": incident_growth},
        ]
        prediction = cls._as_prediction(
            organization_id=organization_id,
            prediction_type="emergency_surge_probability",
            horizon="next_30m",
            value=surge_risk,
            confidence=cls._prediction_confidence(0.56, len(evidence)),
            evidence=evidence,
        )
        OperationalMemoryService.record_prediction(
            db,
            organization_id=organization_id,
            actor_user_id=user.user_id,
            prediction=prediction,
            replay_hint=f"emergency:{organization_id}:{prediction['value']}",
        )
        AIGovernanceEngine.register_prediction_event(
            db,
            organization_id=organization_id,
            actor_user_id=user.user_id,
            prediction=prediction,
        )
        return {"organization_id": organization_id, "enabled": True, "predictions": [prediction]}
