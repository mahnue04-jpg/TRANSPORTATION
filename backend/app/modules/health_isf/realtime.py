"""
Real-time infrastructure for Health ISF dispatch operations.
Manages WebSocket connections, event broadcasting, and synchronization.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, List, Set, Optional, Callable, Any
from enum import Enum

from app.modules.health_isf.operations import (
    get_operational_metrics_registry,
    log_operational_event,
)

logger = logging.getLogger("amicor.health_isf.realtime")


def _record_runtime_websocket(counter_name: str) -> None:
    try:
        from app.modules.health_isf.runtime_governor import get_runtime_governor

        governor = get_runtime_governor()
        getattr(governor, counter_name)()
    except Exception:
        return None


class SubscriptionType(str, Enum):
    """Types of real-time subscriptions."""
    DISPATCHER_BOARD = "dispatcher_board"
    DRIVER_DASHBOARD = "driver_dashboard"
    RIDE_UPDATES = "ride_updates"
    DRIVER_AVAILABILITY = "driver_availability"
    WORKFLOW_EVENTS = "workflow_events"
    ESCALATION_QUEUE = "escalation_queue"
    INCIDENT_UPDATES = "incident_updates"


class WebSocketConnection:
    """Represents a single WebSocket connection."""
    
    def __init__(self, connection_id: str, user_id: str, role: str):
        self.connection_id = connection_id
        self.user_id = user_id
        self.role = role  # 'dispatcher', 'driver', 'admin'
        self.subscriptions: Set[str] = set()
        self.ride_subscriptions: Set[str] = set()
        self.connected_at = datetime.utcnow()
        self.last_heartbeat = datetime.utcnow()
        self.send_queue: asyncio.Queue = asyncio.Queue()
        self.message_timestamps: deque[datetime] = deque(maxlen=500)
    
    def subscribe(self, subscription_type: str):
        """Add subscription."""
        self.subscriptions.add(subscription_type)
    
    def unsubscribe(self, subscription_type: str):
        """Remove subscription."""
        self.subscriptions.discard(subscription_type)

    def subscribe_ride(self, ride_id: str):
        """Add ride-specific subscription."""
        ride = str(ride_id or "").strip()
        if ride:
            self.ride_subscriptions.add(ride)

    def unsubscribe_ride(self, ride_id: str):
        """Remove ride-specific subscription."""
        ride = str(ride_id or "").strip()
        if ride:
            self.ride_subscriptions.discard(ride)
    
    def is_stale(self, timeout_seconds: int = 300) -> bool:
        """Check if connection hasn't received heartbeat for timeout period."""
        return (datetime.utcnow() - self.last_heartbeat).total_seconds() > timeout_seconds
    
    def update_heartbeat(self):
        """Update last heartbeat timestamp."""
        self.last_heartbeat = datetime.utcnow()

    def register_message(self, max_messages_per_minute: int) -> bool:
        """Track incoming messages and report if connection exceeded rate limit."""
        now_dt = datetime.utcnow()
        self.message_timestamps.append(now_dt)
        one_minute_ago = now_dt - timedelta(minutes=1)
        recent = sum(1 for ts in self.message_timestamps if ts >= one_minute_ago)
        return recent <= max_messages_per_minute


class EventBroadcaster:
    """Broadcasts real-time events to subscribed WebSocket connections."""
    
    def __init__(self):
        self.connections: Dict[str, WebSocketConnection] = {}
        self.organization_connections: Dict[str, Set[str]] = {}  # org_id -> set of connection_ids
        self.subscription_listeners: Dict[str, List[Callable]] = {}
        self.disconnect_events: deque[datetime] = deque(maxlen=2000)
        self.event_replay_buffers: Dict[str, deque[dict]] = {}
        self.sequence_by_org: Dict[str, int] = {}
        self.recovery_attempts_by_org: Dict[str, int] = {}
        self.recovery_failures_by_org: Dict[str, int] = {}
        self.last_recovery_status_by_org: Dict[str, str] = {}
        self.degraded_reasons_by_org: Dict[str, List[str]] = {}
        self.max_connections_per_org = int(os.environ.get("HEALTH_ISF_WS_MAX_ORG_CONNECTIONS", "500"))
        self.max_connections_per_user = int(os.environ.get("HEALTH_ISF_WS_MAX_USER_CONNECTIONS", "5"))
        self._lock = asyncio.Lock()
    
    async def register_connection(self, connection: WebSocketConnection, organization_id: str):
        """Register a new WebSocket connection."""
        async with self._lock:
            org_connections = self.organization_connections.get(organization_id, set())
            if len(org_connections) >= self.max_connections_per_org:
                raise ValueError("organization connection limit exceeded")

            user_connections = sum(
                1 for conn_id in org_connections
                if conn_id in self.connections and self.connections[conn_id].user_id == connection.user_id
            )
            if user_connections >= self.max_connections_per_user:
                raise ValueError("user connection limit exceeded")

            self.connections[connection.connection_id] = connection
            if organization_id not in self.organization_connections:
                self.organization_connections[organization_id] = set()
            self.organization_connections[organization_id].add(connection.connection_id)
            try:
                metrics = get_operational_metrics_registry()
                metrics.increment("websocket.connections.active", 1)
                metrics.record_event_ts("websocket.connects")
                _record_runtime_websocket("record_websocket_connect")
                log_operational_event(
                    "websocket.connection.registered",
                    connection_id=connection.connection_id,
                    organization_id=organization_id,
                    user_id=connection.user_id,
                    role=connection.role,
                )
            except Exception as exc:
                logger.warning({"event": "websocket_register_metrics_failed", "error": str(exc)})
            logger.info(f"Connection registered: {connection.connection_id} for org {organization_id}")
    
    async def unregister_connection(self, connection_id: str):
        """Remove a WebSocket connection."""
        async with self._lock:
            if connection_id in self.connections:
                del self.connections[connection_id]
                # Remove from organization tracking
                for org_connections in self.organization_connections.values():
                    org_connections.discard(connection_id)
                self.disconnect_events.append(datetime.utcnow())
                try:
                    metrics = get_operational_metrics_registry()
                    metrics.increment("websocket.connections.active", -1)
                    metrics.record_event_ts("websocket.disconnects")
                    _record_runtime_websocket("record_websocket_disconnect")
                except Exception as exc:
                    logger.warning({"event": "websocket_unregister_metrics_failed", "error": str(exc)})
                logger.info(f"Connection unregistered: {connection_id}")
    
    async def broadcast_event(
        self,
        event_type: str,
        payload: dict,
        organization_id: str,
        subscription_types: Optional[List[str]] = None,
        exclude_user_id: Optional[str] = None,
    ) -> int:
        """Broadcast an event to relevant subscribers."""
        if organization_id not in self.organization_connections:
            return 0
        
        message = {
            "type": "event",
            "event_type": event_type,
            "payload": payload,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        message_json = json.dumps(message)
        connection_ids = self.organization_connections.get(organization_id, set()).copy()
        delivered_count = 0

        sequence = self.sequence_by_org.get(organization_id, 0) + 1
        self.sequence_by_org[organization_id] = sequence
        replay_entry = {
            "sequence": sequence,
            "event_type": event_type,
            "payload": payload,
            "timestamp": message["timestamp"],
        }
        if organization_id not in self.event_replay_buffers:
            self.event_replay_buffers[organization_id] = deque(maxlen=500)
        self.event_replay_buffers[organization_id].append(replay_entry)
        
        for conn_id in connection_ids:
            connection = self.connections.get(conn_id)
            if not connection:
                continue
            
            # Skip if excluded user
            if exclude_user_id and connection.user_id == exclude_user_id:
                continue
            
            # Check subscription match
            if subscription_types:
                if not any(sub in connection.subscriptions for sub in subscription_types):
                    continue

            try:
                await connection.send_queue.put(message_json)
                delivered_count += 1
            except Exception as e:
                logger.error(f"Error queueing message for {conn_id}: {e}")

        metrics = get_operational_metrics_registry()
        metrics.increment("dispatch.events.broadcast.total")
        metrics.record_event_ts("dispatch_events")
        if delivered_count == 0:
            metrics.increment("dispatch.events.broadcast.zero_delivery")

        log_operational_event(
            "websocket.event.broadcast",
            event_type=event_type,
            organization_id=organization_id,
            delivered=delivered_count,
            subscribers=len(connection_ids),
            sequence=sequence,
        )
        return delivered_count

    def get_latest_sequence(self, organization_id: str) -> int:
        return int(self.sequence_by_org.get(organization_id, 0))

    def record_recovery_attempt(self, organization_id: str, *, success: bool) -> None:
        org_id = str(organization_id or "")
        if not org_id:
            return
        self.recovery_attempts_by_org[org_id] = int(self.recovery_attempts_by_org.get(org_id, 0)) + 1
        if success:
            self.last_recovery_status_by_org[org_id] = "succeeded"
            return
        self.recovery_failures_by_org[org_id] = int(self.recovery_failures_by_org.get(org_id, 0)) + 1
        self.last_recovery_status_by_org[org_id] = "failed"

    def get_workflow_coordination_contract(self, organization_id: str) -> dict[str, Any]:
        org_id = str(organization_id or "")
        attempts = int(self.recovery_attempts_by_org.get(org_id, 0))
        failures = int(self.recovery_failures_by_org.get(org_id, 0))
        success_rate = 1.0
        if attempts > 0:
            success_rate = max(0.0, float(attempts - failures) / float(attempts))
        return {
            "organization_id": org_id,
            "latest_sequence": self.get_latest_sequence(org_id),
            "recovery_attempts": attempts,
            "recovery_failures": failures,
            "recovery_success_rate": round(success_rate, 4),
            "last_recovery_status": self.last_recovery_status_by_org.get(org_id, "unknown"),
        }

    def get_replay_events(self, organization_id: str, since_sequence: int, limit: int = 200) -> list[dict]:
        buffer = self.event_replay_buffers.get(organization_id) or deque()
        events = [item for item in buffer if int(item.get("sequence", 0)) > int(since_sequence)]
        if limit > 0:
            events = events[:limit]
        return events

    def clear_degraded_state(self, organization_id: str) -> None:
        org_id = str(organization_id or "")
        if not org_id:
            return
        self.degraded_reasons_by_org.pop(org_id, None)

    def get_runtime_reliability_diagnostics(self, organization_id: str) -> dict[str, Any]:
        org_id = str(organization_id or "")
        websocket = self.get_websocket_health_stats(organization_id=org_id)
        recovery_attempts = int(self.recovery_attempts_by_org.get(org_id, 0) or 0)
        recovery_failures = int(self.recovery_failures_by_org.get(org_id, 0) or 0)
        reasons = list(self.degraded_reasons_by_org.get(org_id, []))

        if recovery_failures > 0 and "recovery_failures_present" not in reasons:
            reasons.append("recovery_failures_present")
        if int(websocket.get("disconnects_last_5m", 0) or 0) >= 10 and "websocket_disconnect_spike" not in reasons:
            reasons.append("websocket_disconnect_spike")

        degraded_enabled = len(reasons) > 0
        latest_sequence = self.get_latest_sequence(org_id)

        return {
            "organization_id": org_id,
            "websocket": websocket,
            "replay": {
                "latest_sequence": latest_sequence,
                "buffered_events": len(self.event_replay_buffers.get(org_id) or []),
                "recovery_attempts": recovery_attempts,
                "recovery_failures": recovery_failures,
                "last_recovery_status": self.last_recovery_status_by_org.get(org_id, "unknown"),
            },
            "degraded_mode": {
                "enabled": degraded_enabled,
                "reasons": reasons,
            },
            "distributed_governance": {
                "runtime_coordination_safe": not degraded_enabled,
                "degraded_reasons": reasons,
                "latest_sequence": latest_sequence,
            },
        }

    async def broadcast_event_batch(
        self,
        events: List[dict],
        organization_id: str,
        subscription_types: Optional[List[str]] = None,
    ) -> int:
        """Batch multiple events into a single websocket payload for efficiency."""
        if not events:
            return 0

        batch_payload = {
            "type": "event_batch",
            "count": len(events),
            "events": events,
            "timestamp": datetime.utcnow().isoformat(),
        }

        delivered_count = 0
        message_json = json.dumps(batch_payload)
        connection_ids = self.organization_connections.get(organization_id, set()).copy()
        for conn_id in connection_ids:
            connection = self.connections.get(conn_id)
            if not connection:
                continue
            if subscription_types and not any(sub in connection.subscriptions for sub in subscription_types):
                continue
            try:
                await connection.send_queue.put(message_json)
                delivered_count += 1
            except Exception:
                continue

        metrics = get_operational_metrics_registry()
        metrics.increment("dispatch.events.batch.total")
        metrics.record_sample("dispatch.events.batch.size", float(len(events)))
        return delivered_count
    
    async def broadcast_to_user(
        self,
        user_id: str,
        event_type: str,
        payload: dict,
    ):
        """Broadcast event to all connections of a specific user."""
        message = {
            "type": "event",
            "event_type": event_type,
            "payload": payload,
            "timestamp": datetime.utcnow().isoformat(),
        }
        message_json = json.dumps(message)
        
        for connection in self.connections.values():
            if connection.user_id == user_id:
                try:
                    await connection.send_queue.put(message_json)
                except Exception as e:
                    logger.error(f"Error queueing message for user {user_id}: {e}")
    
    async def cleanup_stale_connections(self, timeout_seconds: int = 300):
        """Remove stale connections (no heartbeat)."""
        async with self._lock:
            stale_ids = [
                conn_id for conn_id, conn in self.connections.items()
                if conn.is_stale(timeout_seconds)
            ]
            for conn_id in stale_ids:
                del self.connections[conn_id]
                for org_connections in self.organization_connections.values():
                    org_connections.discard(conn_id)
                logger.warning(f"Cleaned up stale connection: {conn_id}")
    
    def get_connection_stats(self, organization_id: str) -> dict:
        """Get connection statistics for an organization."""
        conn_ids = self.organization_connections.get(organization_id, set())
        connections = [self.connections.get(cid) for cid in conn_ids if cid in self.connections]
        
        dispatcher_count = sum(1 for c in connections if c.role == "dispatcher")
        driver_count = sum(1 for c in connections if c.role == "driver")
        
        return {
            "total_connections": len(connections),
            "dispatcher_connections": dispatcher_count,
            "driver_connections": driver_count,
            "organization_id": organization_id,
        }

    def get_websocket_health_stats(self, organization_id: Optional[str] = None) -> dict:
        """Return websocket health and disconnect trend statistics."""
        now_dt = datetime.utcnow()
        disconnects_last_5m = sum(
            1 for ts in self.disconnect_events
            if (now_dt - ts).total_seconds() <= 300
        )

        if organization_id:
            scoped = self.get_connection_stats(organization_id)
            active_connections = scoped["total_connections"]
            dispatcher_connections = scoped["dispatcher_connections"]
            driver_connections = scoped["driver_connections"]
        else:
            active_connections = len(self.connections)
            dispatcher_connections = sum(1 for c in self.connections.values() if c.role == "dispatcher")
            driver_connections = sum(1 for c in self.connections.values() if c.role == "driver")

        return {
            "active_connections": active_connections,
            "dispatcher_connections": dispatcher_connections,
            "driver_connections": driver_connections,
            "disconnects_last_5m": disconnects_last_5m,
            "max_connections_per_org": self.max_connections_per_org,
            "max_connections_per_user": self.max_connections_per_user,
            "organization_id": organization_id,
        }


class EventEmitter:
    """Emits real-time events for dispatch operations."""
    
    def __init__(self, broadcaster: EventBroadcaster):
        self.broadcaster = broadcaster

    async def emit_ride_created(
        self,
        organization_id: str,
        ride_id: str,
        passenger_name: str,
        priority_score: float | None = None,
        priority_tag: str | None = None,
        actor_user_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Emit ride created event for dispatcher dashboards."""
        payload = {
            "event_type": "ride_created",
            "ride_id": ride_id,
            "passenger_name": passenger_name,
            "priority_score": priority_score,
            "priority_tag": priority_tag,
            "actor_user_id": actor_user_id,
            "details": details or {},
        }

        await self.broadcaster.broadcast_event(
            event_type="ride_created",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.RIDE_UPDATES,
            ],
        )

        logger.info(f"Emitted ride_created: {ride_id}")
    
    async def emit_ride_status_changed(
        self,
        organization_id: str,
        ride_id: str,
        from_status: Optional[str],
        to_status: str,
        actor_user_id: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Emit ride status changed event."""
        payload = {
            "event_type": "ride_status_changed",
            "ride_id": ride_id,
            "from_status": from_status,
            "to_status": to_status,
            "actor_user_id": actor_user_id,
            "reason": reason,
            "details": details or {},
        }
        
        await self.broadcaster.broadcast_event(
            event_type="ride_status_changed",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.RIDE_UPDATES,
            ],
        )
        
        logger.info(f"Emitted ride_status_changed: {ride_id} ({from_status} -> {to_status})")
    
    async def emit_driver_status_changed(
        self,
        organization_id: str,
        driver_id: str,
        from_status: Optional[str],
        to_status: str,
        actor_user_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Emit driver status changed event."""
        payload = {
            "event_type": "driver_status_changed",
            "driver_id": driver_id,
            "from_status": from_status,
            "to_status": to_status,
            "actor_user_id": actor_user_id,
            "details": details or {},
        }
        
        await self.broadcaster.broadcast_event(
            event_type="driver_status_changed",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.DRIVER_DASHBOARD,
                SubscriptionType.DRIVER_AVAILABILITY,
            ],
        )
        
        logger.info(f"Emitted driver_status_changed: {driver_id} ({from_status} -> {to_status})")
    
    async def emit_ride_assigned(
        self,
        organization_id: str,
        ride_id: str,
        driver_id: str,
        driver_name: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Emit ride assigned event."""
        payload = {
            "event_type": "ride_assigned",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "driver_name": driver_name,
            "actor_user_id": actor_user_id,
            "details": details or {},
        }
        
        await self.broadcaster.broadcast_event(
            event_type="ride_assigned",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.RIDE_UPDATES,
                SubscriptionType.DRIVER_DASHBOARD,
            ],
        )
        
        logger.info(f"Emitted ride_assigned: {ride_id} -> {driver_id}")
    
    async def emit_assignment_rejected(
        self,
        organization_id: str,
        ride_id: str,
        driver_id: str,
        reason: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Emit assignment rejected event."""
        payload = {
            "event_type": "assignment_rejected",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "reason": reason,
            "actor_user_id": actor_user_id,
            "details": details or {},
        }
        
        await self.broadcaster.broadcast_event(
            event_type="assignment_rejected",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[SubscriptionType.DISPATCHER_BOARD],
        )
        
        logger.info(f"Emitted assignment_rejected: {ride_id} by {driver_id}")
    
    async def emit_ride_completed(
        self,
        organization_id: str,
        ride_id: str,
        driver_id: str,
        distance_miles: Optional[float] = None,
        duration_minutes: Optional[int] = None,
        actor_user_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Emit ride completed event."""
        payload = {
            "event_type": "ride_completed",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "distance_miles": distance_miles,
            "duration_minutes": duration_minutes,
            "actor_user_id": actor_user_id,
            "details": details or {},
        }
        
        await self.broadcaster.broadcast_event(
            event_type="ride_completed",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.RIDE_UPDATES,
                SubscriptionType.DRIVER_DASHBOARD,
            ],
        )
        
        logger.info(f"Emitted ride_completed: {ride_id}")

    async def emit_ride_reassigned(
        self,
        organization_id: str,
        ride_id: str,
        from_driver_id: Optional[str],
        to_driver_id: str,
        driver_name: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Emit ride reassigned event for dispatcher operations."""
        payload = {
            "event_type": "ride_reassigned",
            "ride_id": ride_id,
            "from_driver_id": from_driver_id,
            "to_driver_id": to_driver_id,
            "driver_name": driver_name,
            "actor_user_id": actor_user_id,
            "details": details or {},
        }
        
        await self.broadcaster.broadcast_event(
            event_type="ride_reassigned",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.RIDE_UPDATES,
                SubscriptionType.DRIVER_DASHBOARD,
            ],
        )
        
        logger.info(f"Emitted ride_reassigned: {ride_id} from {from_driver_id} to {to_driver_id}")

    async def emit_pickup_completed(
        self,
        organization_id: str,
        ride_id: str,
        driver_id: str,
        actor_user_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Emit pickup completed event."""
        payload = {
            "event_type": "pickup_completed",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "actor_user_id": actor_user_id,
            "details": details or {},
        }
        
        await self.broadcaster.broadcast_event(
            event_type="pickup_completed",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.RIDE_UPDATES,
                SubscriptionType.DRIVER_DASHBOARD,
            ],
        )
        
        logger.info(f"Emitted pickup_completed: {ride_id}")

    async def emit_ride_escalated(
        self,
        organization_id: str,
        ride_id: str,
        issue_type: str,
        description: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Emit ride escalation event for operational issues."""
        payload = {
            "event_type": "ride_escalated",
            "ride_id": ride_id,
            "issue_type": issue_type,
            "description": description,
            "actor_user_id": actor_user_id,
            "details": details or {},
        }
        
        await self.broadcaster.broadcast_event(
            event_type="ride_escalated",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.ESCALATION_QUEUE,
            ],
        )
        
        logger.info(f"Emitted ride_escalated: {ride_id} ({issue_type})")

    async def emit_ride_retry(
        self,
        organization_id: str,
        ride_id: str,
        actor_user_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Emit ride workflow retry event."""
        payload = {
            "event_type": "ride_retry",
            "ride_id": ride_id,
            "actor_user_id": actor_user_id,
            "details": details or {},
        }
        
        await self.broadcaster.broadcast_event(
            event_type="ride_retry",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.RIDE_UPDATES,
            ],
        )
        
        logger.info(f"Emitted ride_retry: {ride_id}")

    async def emit_dispatch_changed(
        self,
        organization_id: str,
        event_name: str,
        details: Optional[dict] = None,
        actor_user_id: Optional[str] = None,
    ):
        payload = {
            "event_type": "dispatch_changed",
            "event_name": event_name,
            "actor_user_id": actor_user_id,
            "details": details or {},
        }
        await self.broadcaster.broadcast_event(
            event_type="dispatch_changed",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.WORKFLOW_EVENTS,
            ],
        )

    async def emit_provider_updated(
        self,
        organization_id: str,
        provider_id: str,
        details: Optional[dict] = None,
        actor_user_id: Optional[str] = None,
    ):
        payload = {
            "event_type": "provider_updated",
            "provider_id": provider_id,
            "actor_user_id": actor_user_id,
            "details": details or {},
        }
        await self.broadcaster.broadcast_event(
            event_type="provider_updated",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.RIDE_UPDATES,
            ],
        )

    async def emit_driver_active_ride_state(
        self,
        organization_id: str,
        driver_id: str,
        active_ride_id: str | None,
        state: str,
        details: Optional[dict] = None,
        actor_user_id: Optional[str] = None,
    ):
        """Emit driver's active ride execution state for mobile-sync readiness."""
        payload = {
            "event_type": "driver_active_ride_state",
            "driver_id": driver_id,
            "active_ride_id": active_ride_id,
            "state": state,
            "actor_user_id": actor_user_id,
            "details": details or {},
        }
        await self.broadcaster.broadcast_event(
            event_type="driver_active_ride_state",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.DRIVER_DASHBOARD,
                SubscriptionType.DRIVER_AVAILABILITY,
            ],
        )

    async def emit_ride_lifecycle_sync(
        self,
        organization_id: str,
        ride_id: str,
        lifecycle_state: str,
        legacy_status: str,
        sequence: int,
    ):
        payload = {
            "event_type": "ride_lifecycle_sync",
            "ride_id": ride_id,
            "lifecycle_state": lifecycle_state,
            "legacy_status": legacy_status,
            "sequence": sequence,
        }
        await self.broadcaster.broadcast_event(
            event_type="ride_lifecycle_sync",
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD,
                SubscriptionType.RIDE_UPDATES,
            ],
        )


# Global broadcaster and emitter instances
_broadcaster: Optional[EventBroadcaster] = None
_emitter: Optional[EventEmitter] = None


def get_broadcaster() -> EventBroadcaster:
    """Get the global event broadcaster instance."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = EventBroadcaster()
    return _broadcaster


def get_emitter() -> EventEmitter:
    """Get the global event emitter instance."""
    global _emitter
    if _emitter is None:
        _emitter = EventEmitter(get_broadcaster())
    return _emitter


def initialize_realtime():
    """Initialize real-time infrastructure."""
    get_broadcaster()
    get_emitter()
    logger.info("Real-time infrastructure initialized")
