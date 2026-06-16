"""Safe read-only correlation across incidents, predictions, memory, realtime, and executions."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.modules.health_isf.operational_timeline import OperationalTimelineEngine
from app.modules.health_isf.memory_service import OperationalMemoryService


class CorrelationEngine:
    @staticmethod
    def _correlation_id(organization_id: str, material: dict[str, Any]) -> str:
        payload = json.dumps({"organization_id": organization_id, **material}, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:18]
        return f"corr_{digest}"

    @classmethod
    def build_correlations(
        cls,
        db: Session,
        *,
        organization_id: str,
        role: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        incidents = OperationalMemoryService.list_stream(db, organization_id=organization_id, stream="incidents", role=role, limit=limit)
        predictions = OperationalMemoryService.list_stream(db, organization_id=organization_id, stream="predictions", role=role, limit=limit)
        executions = OperationalMemoryService.list_stream(db, organization_id=organization_id, stream="executions", role=role, limit=limit)
        timeline = OperationalTimelineEngine.reconstruct_operational_timeline(db, organization_id=organization_id, role=role, limit=limit)
        realtime = OperationalTimelineEngine.capture_realtime_context(db, organization_id=organization_id)

        buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "incidents": [],
            "predictions": [],
            "memory": [],
            "executions": [],
            "rollback_references": [],
        })

        for event in incidents:
            key = str((event.get("payload") or {}).get("tenant_scope") or organization_id)
            buckets[key]["incidents"].append(event)
            buckets[key]["memory"].append(event)
        for event in predictions:
            key = str((event.get("payload") or {}).get("tenant_scope") or organization_id)
            buckets[key]["predictions"].append(event)
            buckets[key]["memory"].append(event)
        for event in executions:
            key = str((event.get("payload") or {}).get("tenant_scope") or organization_id)
            buckets[key]["executions"].append(event)
            rollback = str((event.get("payload") or {}).get("rollback_reference") or "")
            if rollback:
                buckets[key]["rollback_references"].append(rollback)

        correlations: list[dict[str, Any]] = []
        for tenant_scope, bucket in buckets.items():
            confidence = 0.5
            confidence += min(0.25, len(bucket["incidents"]) * 0.03)
            confidence += min(0.15, len(bucket["predictions"]) * 0.02)
            confidence += min(0.1, len(bucket["executions"]) * 0.02)
            summary = (
                f"Correlated {len(bucket['incidents'])} incident(s), {len(bucket['predictions'])} prediction(s), "
                f"and {len(bucket['executions'])} execution event(s) under tenant scope {tenant_scope}."
            )
            correlations.append(
                {
                    "correlation_id": cls._correlation_id(organization_id, {"tenant_scope": tenant_scope, "summary": summary}),
                    "organization_id": organization_id,
                    "tenant_scope": tenant_scope,
                    "confidence": round(min(0.99, confidence), 4),
                    "summary": summary,
                    "incidents": bucket["incidents"],
                    "predictions": bucket["predictions"],
                    "memory": bucket["memory"],
                    "realtime": realtime,
                    "executions": bucket["executions"],
                    "rollback_references": bucket["rollback_references"],
                }
            )

        if not correlations:
            correlations.append(
                {
                    "correlation_id": cls._correlation_id(organization_id, {"tenant_scope": organization_id, "empty": True}),
                    "organization_id": organization_id,
                    "tenant_scope": organization_id,
                    "confidence": 0.0,
                    "summary": "No correlated operational intelligence events were found.",
                    "incidents": [],
                    "predictions": [],
                    "memory": [],
                    "realtime": realtime,
                    "executions": [],
                    "rollback_references": [],
                }
            )
        return correlations[:limit]
