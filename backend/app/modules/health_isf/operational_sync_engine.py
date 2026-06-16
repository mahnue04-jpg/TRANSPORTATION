"""Distributed operational sync engine for cross-surface event propagation."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from app.helpers import uuid4
from app.modules.health_isf.operational_event_bus import get_operational_event_bus
from app.modules.health_isf.operational_event_models import OperationalEvent, OperationalEventType
from app.modules.health_isf.realtime import SubscriptionType, get_broadcaster


_ROLE_TO_SUBSCRIPTIONS: dict[str, list[str]] = {
    "dispatcher": [SubscriptionType.DISPATCHER_BOARD.value, SubscriptionType.WORKFLOW_EVENTS.value],
    "driver": [SubscriptionType.DRIVER_DASHBOARD.value, SubscriptionType.RIDE_UPDATES.value],
    "provider": [SubscriptionType.RIDE_UPDATES.value, SubscriptionType.INCIDENT_UPDATES.value],
    "staff": [SubscriptionType.WORKFLOW_EVENTS.value, SubscriptionType.ESCALATION_QUEUE.value],
    "admin": [SubscriptionType.WORKFLOW_EVENTS.value, SubscriptionType.ESCALATION_QUEUE.value, SubscriptionType.INCIDENT_UPDATES.value],
    "customer": [SubscriptionType.RIDE_UPDATES.value],
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OperationalSynchronizationEngine:
    @staticmethod
    def publish_event(
        *,
        organization_id: str,
        event_type: OperationalEventType,
        payload: dict[str, Any],
        role_scope: list[str],
        source_nonce: str | None = None,
        stale_after_seconds: int = 180,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = OperationalEvent(
            organization_id=organization_id,
            event_id=str(uuid4()),
            event_type=event_type,
            role_scope=role_scope,
            payload=payload,
            emitted_at=_utc_now(),
            source_nonce=source_nonce,
            metadata=metadata or {},
            approval_governed=True,
            replayable=True,
        )

        bus = get_operational_event_bus()
        accepted, status, persisted = bus.publish(event, stale_after_seconds=stale_after_seconds)
        if not accepted or persisted is None:
            return {
                "organization_id": organization_id,
                "accepted": False,
                "status": status,
                "tenant_scoped": True,
                "approval_governed": True,
            }

        subscriptions: set[str] = set()
        for role in role_scope:
            subscriptions.update(_ROLE_TO_SUBSCRIPTIONS.get(role, []))

        try:
            loop = asyncio.get_running_loop()
            broadcaster = get_broadcaster()
            loop.create_task(
                broadcaster.broadcast_event(
                    event_type=str(event_type.value),
                    payload={
                        "event_id": persisted.event_id,
                        "sequence": persisted.sequence,
                        "payload": persisted.payload,
                        "role_scope": persisted.role_scope,
                    },
                    organization_id=organization_id,
                    subscription_types=sorted(subscriptions) if subscriptions else None,
                )
            )
        except RuntimeError:
            # Event loop may not be available in some sync contexts; this does not affect ordering/replay.
            pass

        return {
            "organization_id": organization_id,
            "accepted": True,
            "status": status,
            "event_id": persisted.event_id,
            "sequence": persisted.sequence,
            "event_type": str(persisted.event_type.value),
            "role_scope": list(persisted.role_scope),
            "tenant_scoped": True,
            "approval_governed": True,
            "backend_authoritative": True,
        }

    @staticmethod
    def synchronization_snapshot(organization_id: str) -> dict[str, Any]:
        bus = get_operational_event_bus()
        stats = bus.stats(organization_id)
        recent = bus.replay(organization_id, after_sequence=max(0, stats["latest_sequence"] - 20), limit=20)
        return {
            "organization_id": organization_id,
            "cross_client_operational_synchronization": True,
            "dashboard_driver_provider_event_propagation": True,
            "future_customer_synchronization_hooks": True,
            "tenant_scoped_event_streaming": True,
            "operational_state_reconciliation": True,
            "reconnect_safe_replay_handling": True,
            "stale_event_rejection": True,
            "ordered_operational_event_sequencing": True,
            "event_bus": stats,
            "recent_events": [asdict(item) for item in recent],
        }
