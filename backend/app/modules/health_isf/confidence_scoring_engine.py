"""Confidence scoring for operational decision recommendations."""

from __future__ import annotations

from typing import Any


class ConfidenceScoringEngine:
    @staticmethod
    def score(*, pressure: dict[str, Any], forecast: dict[str, Any], severity_weight: float) -> float:
        p_regional = float(pressure.get("regional_congestion", 0.0))
        p_driver = float(pressure.get("driver_load_pressure", 0.0))
        p_provider = float(pressure.get("provider_queue_pressure", 0.0))
        f_pressure = float(forecast.get("resource_pressure_forecast", 0.0))
        f_continuity = float(forecast.get("continuity_risk_forecast", 0.0))

        uncertainty = (
            p_regional * 0.22
            + p_driver * 0.2
            + p_provider * 0.2
            + f_pressure * 0.2
            + f_continuity * 0.18
        )
        confidence = 1.0 - min(1.0, uncertainty * 0.7 + max(0.0, 1.0 - float(severity_weight)) * 0.15)
        return round(max(0.05, min(0.99, confidence)), 4)
