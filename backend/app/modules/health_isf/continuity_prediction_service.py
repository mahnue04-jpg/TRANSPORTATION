"""Continuity and recovery prediction helpers for adaptive operational forecasting."""

from __future__ import annotations

from typing import Any


class ContinuityPredictionService:
    @staticmethod
    def build(*, decision: dict[str, Any], memory: dict[str, Any], sync: dict[str, Any]) -> dict[str, Any]:
        pressure = decision.get("pressure_analysis") or {}
        pattern_summary = memory.get("pattern_summary") or {}
        event_bus = sync.get("event_bus") or {}

        continuity_risk = min(
            1.0,
            float(pressure.get("continuity_degradation_risk") or 0.0) * 0.55
            + float(pattern_summary.get("incident_growth_ratio") or 0.0) * 0.2
            + min(1.0, float(event_bus.get("total_events") or 0.0) / 400.0) * 0.25,
        )
        recovery_minutes = int(15 + continuity_risk * 90)
        confidence = max(0.05, min(0.99, 1.0 - continuity_risk * 0.45))
        return {
            "continuity_risk": round(continuity_risk, 4),
            "recovery_timeline_minutes": recovery_minutes,
            "confidence": round(confidence, 4),
            "reasoning_chain": [
                "Continuity forecast derived from current pressure, historical growth, and ordered event volume.",
                "Prediction remains recommendation-only and requires human-approved follow-through.",
            ],
        }
