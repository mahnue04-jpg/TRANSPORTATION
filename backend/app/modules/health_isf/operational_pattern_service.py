"""Operational memory pattern extraction over append-only history."""

from __future__ import annotations

from typing import Any


class OperationalPatternService:
    @staticmethod
    def build_summary(*, history_features: dict[str, float], incidents: list[dict[str, Any]], operations: list[dict[str, Any]]) -> dict[str, Any]:
        escalation_patterns = sum(1 for item in operations if "escalat" in str(item.get("event_type") or "").lower())
        congestion_patterns = sum(1 for item in operations if "congestion" in str(item.get("event_type") or "").lower())
        continuity_patterns = sum(1 for item in operations if "continu" in str(item.get("event_type") or "").lower())
        return {
            "incident_growth_ratio": round(float(history_features.get("incident_growth_ratio") or 0.0), 4),
            "incident_history_count": len(incidents),
            "escalation_pattern_count": escalation_patterns,
            "congestion_pattern_count": congestion_patterns,
            "continuity_pattern_count": continuity_patterns,
            "total_memory_references": len(incidents) + len(operations),
        }
