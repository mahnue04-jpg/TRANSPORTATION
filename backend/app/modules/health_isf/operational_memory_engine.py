"""Tenant-scoped operational memory fabric built from append-only memory streams."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.health_isf.memory_service import OperationalMemoryService
from app.modules.health_isf.operational_history_recall import OperationalHistoryRecall
from app.modules.health_isf.operational_memory_models import OperationalMemorySnapshot
from app.modules.health_isf.operational_pattern_service import OperationalPatternService


class OperationalMemoryEngine:
    @staticmethod
    def build_snapshot(db: Session, *, organization_id: str, role: str = "dispatcher") -> dict[str, Any]:
        incidents = OperationalMemoryService.list_stream(
            db,
            organization_id=organization_id,
            stream="incidents",
            role=role,
            limit=25,
        )
        operations = OperationalMemoryService.list_stream(
            db,
            organization_id=organization_id,
            stream="operations",
            role=role,
            limit=25,
        )
        predictions = OperationalMemoryService.list_stream(
            db,
            organization_id=organization_id,
            stream="predictions",
            role=role,
            limit=25,
        )
        history = OperationalMemoryService.history_features(
            db,
            organization_id=organization_id,
            role=role,
        )
        pattern_summary = OperationalPatternService.build_summary(
            history_features=history,
            incidents=incidents,
            operations=operations,
        )
        recall_summary = OperationalHistoryRecall.build(
            incidents=incidents,
            operations=operations,
            predictions=predictions,
        )

        provider_history = [item for item in operations if "provider" in str(item.get("event_type") or "").lower()][:10]
        driver_history = [item for item in operations if "driver" in str(item.get("event_type") or "").lower()][:10]
        congestion_history = [item for item in operations if "congestion" in str(item.get("event_type") or "").lower()][:10]

        snapshot = OperationalMemorySnapshot(
            organization_id=organization_id,
            generated_at=datetime.utcnow().isoformat(),
            backend_authoritative=True,
            tenant_scoped=True,
            replay_safe=True,
            auditable=True,
            explainable_memory_references=True,
            incident_history_memory=incidents,
            escalation_pattern_memory=[item for item in operations if "escalat" in str(item.get("event_type") or "").lower()][:10],
            provider_continuity_history=provider_history,
            driver_operational_trend_memory=driver_history,
            operational_congestion_history=congestion_history,
            regional_operational_learning=predictions[:10],
            pattern_summary=pattern_summary,
            recall_summary=recall_summary,
        )
        return snapshot.to_dict()
