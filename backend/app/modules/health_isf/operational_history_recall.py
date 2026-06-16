"""Replay-safe operational history recall helpers."""

from __future__ import annotations

from typing import Any


class OperationalHistoryRecall:
    @staticmethod
    def build(*, incidents: list[dict[str, Any]], operations: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
        def _refs(items: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
            refs: list[dict[str, Any]] = []
            for item in items[:limit]:
                refs.append(
                    {
                        "event_id": item.get("event_id"),
                        "event_type": item.get("event_type"),
                        "recorded_at": item.get("recorded_at"),
                        "tenant_scope": item.get("tenant_scope"),
                        "replay_key": item.get("replay_key"),
                        "explainable_reference": True,
                    }
                )
            return refs

        return {
            "recent_incident_references": _refs(incidents),
            "recent_operation_references": _refs(operations),
            "recent_prediction_references": _refs(predictions),
            "replay_safe_operational_recall": True,
            "auditable_memory_usage": True,
        }
