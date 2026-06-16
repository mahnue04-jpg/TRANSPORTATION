"""Operational memory service for incidents, predictions, executions, and workflow outcomes."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.health_isf.operational_memory_store import OperationalMemoryStore


class OperationalMemoryService:
    @classmethod
    def record_incident(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        incident: dict[str, Any],
        replay_hint: str | None = None,
    ) -> dict[str, Any]:
        return OperationalMemoryStore.append_event(
            db,
            organization_id=organization_id,
            stream="incidents",
            event_type=str(incident.get("incident_type") or "incident_detected"),
            payload=incident,
            actor_user_id=actor_user_id,
            replay_hint=replay_hint,
        )

    @classmethod
    def record_operation(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        operation: dict[str, Any],
        replay_hint: str | None = None,
    ) -> dict[str, Any]:
        return OperationalMemoryStore.append_event(
            db,
            organization_id=organization_id,
            stream="operations",
            event_type=str(operation.get("operation_type") or "operation_recorded"),
            payload=operation,
            actor_user_id=actor_user_id,
            replay_hint=replay_hint,
        )

    @classmethod
    def record_prediction(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        prediction: dict[str, Any],
        replay_hint: str | None = None,
    ) -> dict[str, Any]:
        return OperationalMemoryStore.append_event(
            db,
            organization_id=organization_id,
            stream="predictions",
            event_type=str(prediction.get("prediction_type") or "prediction_generated"),
            payload=prediction,
            actor_user_id=actor_user_id,
            replay_hint=replay_hint,
        )

    @classmethod
    def record_execution(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        execution: dict[str, Any],
        replay_hint: str | None = None,
    ) -> dict[str, Any]:
        return OperationalMemoryStore.append_event(
            db,
            organization_id=organization_id,
            stream="executions",
            event_type=str(execution.get("action_type") or "execution_recorded"),
            payload=execution,
            actor_user_id=actor_user_id,
            replay_hint=replay_hint,
        )

    @classmethod
    def list_stream(
        cls,
        db: Session,
        *,
        organization_id: str,
        stream: str,
        role: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return OperationalMemoryStore.list_events(
            db,
            organization_id=organization_id,
            stream=stream,
            role=role,
            limit=limit,
        )

    @classmethod
    def history_features(
        cls,
        db: Session,
        *,
        organization_id: str,
        role: str,
    ) -> dict[str, float]:
        """Return real trend features extracted from append-only memory streams."""
        incidents = cls.list_stream(db, organization_id=organization_id, stream="incidents", role=role, limit=400)
        predictions = cls.list_stream(db, organization_id=organization_id, stream="predictions", role=role, limit=400)
        executions = cls.list_stream(db, organization_id=organization_id, stream="executions", role=role, limit=400)

        now_dt = now()

        def _count_window(events: list[dict[str, Any]], minutes: int) -> int:
            cutoff = now_dt - timedelta(minutes=minutes)
            count = 0
            for event in events:
                recorded_at = str(event.get("recorded_at") or "")
                try:
                    # ISO-8601 lexical ordering does not handle timezone offsets safely, so parse with fromisoformat fallback.
                    stamp = recorded_at.replace("Z", "+00:00")
                    import datetime as _dt

                    dt = _dt.datetime.fromisoformat(stamp)
                except Exception:
                    continue
                if dt >= cutoff:
                    count += 1
            return count

        incidents_60m = _count_window(incidents, 60)
        incidents_360m = _count_window(incidents, 360)
        executions_60m = _count_window(executions, 60)
        predictions_60m = _count_window(predictions, 60)

        baseline_incidents_per_hour = (incidents_360m / 6.0) if incidents_360m > 0 else 0.0
        incident_growth_ratio = (incidents_60m / baseline_incidents_per_hour) if baseline_incidents_per_hour > 0 else 0.0

        return {
            "incidents_60m": float(incidents_60m),
            "incidents_360m": float(incidents_360m),
            "executions_60m": float(executions_60m),
            "predictions_60m": float(predictions_60m),
            "baseline_incidents_per_hour": float(baseline_incidents_per_hour),
            "incident_growth_ratio": float(incident_growth_ratio),
        }
