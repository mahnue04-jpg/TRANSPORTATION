from __future__ import annotations

from typing import Any

from app.core.nova.event_models import NovaOperationalEvent
from app.core.nova.memory import memory_store


class NovaOperationalEventBus:
    """Deduplicated, replay-safe event pipeline persisted in Nova memory fabric."""

    def publish_events(self, organization_id: str, events: list[NovaOperationalEvent]) -> dict[str, Any]:
        normalized = [event.model_dump() for event in events]
        persisted = memory_store.append_operational_events(organization_id, normalized)
        return {
            "organization_id": organization_id,
            "published_count": len(persisted),
            "events": persisted,
        }

    def replay_events(self, organization_id: str, *, limit: int = 60) -> list[dict[str, Any]]:
        return memory_store.read_operational_events(organization_id, limit=limit)


nova_event_bus = NovaOperationalEventBus()
