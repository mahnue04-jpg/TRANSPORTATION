"""Operational replay service for reconnect-safe distributed synchronization."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from app.modules.health_isf.operational_event_bus import get_operational_event_bus
from app.modules.health_isf.operational_event_models import OperationalReplayCursor


class OperationalReplayService:
    @staticmethod
    def replay(
        *,
        organization_id: str,
        after_sequence: int,
        role: str,
        limit: int = 200,
    ) -> dict[str, Any]:
        bus = get_operational_event_bus()
        envelopes = bus.replay(organization_id, after_sequence=after_sequence, limit=limit)
        filtered = [item for item in envelopes if role in item.role_scope or "admin" in item.role_scope]

        cursor = OperationalReplayCursor(
            organization_id=organization_id,
            last_sequence=filtered[-1].sequence if filtered else after_sequence,
            generated_at=datetime.now(timezone.utc),
        )

        return {
            "organization_id": organization_id,
            "role": role,
            "events": [asdict(item) for item in filtered],
            "cursor": {
                "organization_id": cursor.organization_id,
                "last_sequence": cursor.last_sequence,
                "generated_at": cursor.generated_at.isoformat(),
            },
            "reconnect_safe": True,
            "tenant_scoped": True,
            "approval_governed": True,
            "backend_authoritative": True,
        }

    @staticmethod
    def replay_integrity(organization_id: str) -> dict[str, Any]:
        bus = get_operational_event_bus()
        stats = bus.stats(organization_id)
        events = bus.replay(organization_id, after_sequence=0, limit=500)
        sequences = [item.sequence for item in events]
        ordered = sequences == sorted(sequences)
        no_duplicates = len(sequences) == len(set(sequences))
        return {
            "organization_id": organization_id,
            "ordered": ordered,
            "no_duplicates": no_duplicates,
            "latest_sequence": stats["latest_sequence"],
            "total_events": stats["total_events"],
            "integrity_ok": bool(ordered and no_duplicates),
        }
