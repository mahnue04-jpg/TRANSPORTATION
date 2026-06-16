"""Reasoning chain builder for explainable operational recommendations."""

from __future__ import annotations

from typing import Any


class OperationalReasoningChain:
    @staticmethod
    def build(*, context: dict[str, Any], recommendation_type: str) -> list[str]:
        pressure = context.get("pressure") or {}
        forecast = context.get("forecast") or {}

        chain: list[str] = []
        chain.append(f"Detected recommendation category {recommendation_type} from tenant-scoped operational inputs.")
        chain.append(
            "Pressure inputs considered: "
            f"regional={float(pressure.get('regional_congestion', 0.0)):.2f}, "
            f"driver={float(pressure.get('driver_load_pressure', 0.0)):.2f}, "
            f"provider={float(pressure.get('provider_queue_pressure', 0.0)):.2f}."
        )
        chain.append(
            "Forecast context considered: "
            f"resource_pressure={float(forecast.get('resource_pressure_forecast', 0.0)):.2f}, "
            f"congestion={float(forecast.get('operational_congestion_prediction', 0.0)):.2f}."
        )
        chain.append("Execution mode remains recommendation-only and approval-governed.")
        return chain
