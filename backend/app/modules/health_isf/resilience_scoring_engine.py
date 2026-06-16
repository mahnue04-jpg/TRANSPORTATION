"""Operational resilience scoring for supervised forecasting."""

from __future__ import annotations

from typing import Any


class ResilienceScoringEngine:
    @staticmethod
    def build(*, decision: dict[str, Any], memory: dict[str, Any], continuity: dict[str, Any]) -> dict[str, Any]:
        pressure = decision.get("pressure_analysis") or {}
        memory_summary = memory.get("pattern_summary") or {}
        resilience = 1.0 - min(
            1.0,
            float(pressure.get("regional_congestion") or 0.0) * 0.2
            + float(pressure.get("provider_queue_pressure") or 0.0) * 0.2
            + float(pressure.get("driver_load_pressure") or 0.0) * 0.2
            + float(memory_summary.get("incident_growth_ratio") or 0.0) * 0.15
            + float(continuity.get("continuity_risk") or 0.0) * 0.25,
        )
        return {
            "resilience_score": round(max(0.01, resilience), 4),
            "confidence": round(max(0.05, min(0.99, 0.6 + resilience * 0.3)), 4),
            "reasoning_chain": [
                "Resilience score synthesized from current workload pressure, historical trend growth, and continuity risk.",
                "Score is backend-authoritative and recommendation-only.",
            ],
        }
