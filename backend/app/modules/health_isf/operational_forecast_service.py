"""Operational pressure forecasting and continuity risk estimation."""

from __future__ import annotations

from typing import Any

from app.modules.health_isf.operational_decision_models import OperationalPressureSnapshot


class OperationalForecastService:
    @staticmethod
    def build_forecast(*, pressure: OperationalPressureSnapshot, sync_snapshot: dict[str, Any]) -> dict[str, Any]:
        event_bus = sync_snapshot.get("event_bus") or {}
        latest_sequence = float(event_bus.get("latest_sequence") or 0.0)

        congestion_prediction = min(1.0, pressure.regional_congestion * 0.6 + pressure.incident_clustering * 0.4)
        continuity_risk = min(
            1.0,
            pressure.continuity_degradation_risk * 0.55 + pressure.escalation_surge * 0.3 + (latest_sequence / 1000.0) * 0.15,
        )
        workload_imbalance = min(1.0, pressure.driver_load_pressure * 0.55 + pressure.provider_queue_pressure * 0.45)
        resource_pressure = min(1.0, pressure.provider_queue_pressure * 0.5 + pressure.driver_load_pressure * 0.5)

        return {
            "operational_congestion_prediction": round(congestion_prediction, 4),
            "continuity_risk_forecast": round(continuity_risk, 4),
            "workload_balance_forecast": round(workload_imbalance, 4),
            "resource_pressure_forecast": round(resource_pressure, 4),
            "recommendation_only": True,
            "tenant_scoped": True,
            "replay_safe": True,
            "websocket_synchronized": True,
        }
