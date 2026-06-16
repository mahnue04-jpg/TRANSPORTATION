"""Reasoning inspection helpers for supervisory explainability review."""

from __future__ import annotations

from typing import Any


class ReasoningInspectionService:
    @staticmethod
    def build(*, decision: dict[str, Any], coordination: dict[str, Any], adaptive_forecast: dict[str, Any]) -> dict[str, Any]:
        return {
            "decision_reasoning_chains": [item.get("reasoning_chain") for item in (decision.get("recommendations") or [])[:10]],
            "coordination_reasoning_chains": [item.get("reasoning_chain") for item in (coordination.get("recommendations") or [])[:10]],
            "forecast_reasoning": {
                "continuity": (adaptive_forecast.get("continuity_degradation_forecast") or {}).get("reasoning_chain") or [],
                "resilience": (adaptive_forecast.get("operational_resilience_scoring") or {}).get("reasoning_chain") or [],
            },
            "explainable": True,
            "auditable": True,
        }
