"""Operational timeline reconstruction using append-only memory and audit history."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.modules.health_isf.models import HealthISFWorkflowAuditLog
from app.modules.health_isf.memory_service import OperationalMemoryService
from app.modules.health_isf.security import enforce_tenant_scope
from app.modules.health_isf.realtime import get_broadcaster
from app.modules.health_isf.operations import build_operational_metrics


class OperationalTimelineEngine:
    @staticmethod
    def _parse_payload(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            import json
            value = json.loads(raw)
            return value if isinstance(value, dict) else {"value": value}
        except Exception:
            return {"raw": raw}

    @staticmethod
    def _parse_recorded_at(value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            # Keep continuity by assigning a deterministic fallback timestamp for malformed records.
            return datetime.min.replace(tzinfo=timezone.utc)

    @classmethod
    def reconstruct_incident_timeline(
        cls,
        db: Session,
        *,
        organization_id: str,
        role: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        incidents = OperationalMemoryService.list_stream(db, organization_id=organization_id, stream="incidents", role=role, limit=limit)
        timeline: list[dict[str, Any]] = []
        for event in incidents:
            timeline.append(
                {
                    "event_id": event.get("event_id"),
                    "event_type": event.get("event_type"),
                    "organization_id": organization_id,
                    "tenant_scope": event.get("tenant_scope") or organization_id,
                    "timestamp": cls._parse_recorded_at(event.get("recorded_at")),
                    "confidence": float((event.get("payload") or {}).get("confidence", 0.0)) if isinstance(event.get("payload"), dict) else None,
                    "related_incidents": [event],
                    "related_predictions": [],
                    "related_executions": [],
                    "rollback_references": [],
                    "evidence": [event.get("payload") or {}],
                }
            )
        return timeline

    @classmethod
    def reconstruct_prediction_chain(
        cls,
        db: Session,
        *,
        organization_id: str,
        role: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        predictions = OperationalMemoryService.list_stream(db, organization_id=organization_id, stream="predictions", role=role, limit=limit)
        timeline: list[dict[str, Any]] = []
        for event in predictions:
            timeline.append(
                {
                    "event_id": event.get("event_id"),
                    "event_type": event.get("event_type"),
                    "organization_id": organization_id,
                    "tenant_scope": event.get("tenant_scope") or organization_id,
                    "timestamp": cls._parse_recorded_at(event.get("recorded_at")),
                    "confidence": float((event.get("payload") or {}).get("confidence", 0.0)) if isinstance(event.get("payload"), dict) else None,
                    "related_incidents": [],
                    "related_predictions": [event],
                    "related_executions": [],
                    "rollback_references": [],
                    "evidence": [event.get("payload") or {}],
                }
            )
        return timeline

    @classmethod
    def reconstruct_execution_history(
        cls,
        db: Session,
        *,
        organization_id: str,
        role: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        executions = OperationalMemoryService.list_stream(db, organization_id=organization_id, stream="executions", role=role, limit=limit)
        approvals = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(HealthISFWorkflowAuditLog.organization_id == organization_id)
            .filter(HealthISFWorkflowAuditLog.event_type.like("ai.governance.%"))
            .order_by(HealthISFWorkflowAuditLog.created_at.desc())
            .limit(limit)
            .all()
        )
        approval_events = [cls._parse_payload(row.payload) for row in approvals]
        timeline: list[dict[str, Any]] = []
        for event in executions:
            timeline.append(
                {
                    "event_id": event.get("event_id"),
                    "event_type": event.get("event_type"),
                    "organization_id": organization_id,
                    "tenant_scope": event.get("tenant_scope") or organization_id,
                    "timestamp": cls._parse_recorded_at(event.get("recorded_at")),
                    "confidence": float((event.get("payload") or {}).get("confidence", 0.0)) if isinstance(event.get("payload"), dict) else None,
                    "related_incidents": [],
                    "related_predictions": [],
                    "related_executions": [event],
                    "rollback_references": [str((event.get("payload") or {}).get("rollback_reference") or "")],
                    "evidence": [event.get("payload") or {}],
                    "approvals": approval_events,
                }
            )
        return timeline

    @classmethod
    def reconstruct_operational_timeline(
        cls,
        db: Session,
        *,
        organization_id: str,
        role: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        incidents = cls.reconstruct_incident_timeline(db, organization_id=organization_id, role=role, limit=limit)
        predictions = cls.reconstruct_prediction_chain(db, organization_id=organization_id, role=role, limit=limit)
        executions = cls.reconstruct_execution_history(db, organization_id=organization_id, role=role, limit=limit)
        combined = incidents + predictions + executions
        combined.sort(key=lambda item: item.get("timestamp") or datetime.min, reverse=True)
        return combined[:limit]

    @classmethod
    def capture_realtime_context(cls, db: Session, *, organization_id: str) -> dict[str, Any]:
        return {
            "metrics": build_operational_metrics(db, organization_id=organization_id),
            "websocket": get_broadcaster().get_websocket_health_stats(organization_id=organization_id),
        }
