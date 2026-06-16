"""
PHASE 7A: Nova Operational Timeline
Extended timeline system capturing all operational events with replay-safe deduplication.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class TimelineEventType(str, Enum):
    """All event types in operational timeline."""
    AI_RECOMMENDATION_CREATED = "ai_recommendation_created"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    ROLLBACK_TRIGGERED = "rollback_triggered"
    ROLLBACK_COMPLETED = "rollback_completed"
    RECOVERY_COMPLETED = "recovery_completed"
    WEBSOCKET_RECONNECT = "websocket_reconnect"
    DEPLOYMENT_EVENT = "deployment_event"
    STAFFING_ESCALATION = "staffing_escalation"
    PROVIDER_OUTAGE = "provider_outage"
    DISPATCH_ANOMALY = "dispatch_anomaly"
    MEMORY_CHECKPOINT = "memory_checkpoint"
    OPERATOR_COMMAND = "operator_command"


@dataclass
class TimelineEvent:
    """Single event in operational timeline."""
    event_id: str
    event_type: TimelineEventType
    timestamp: datetime
    organization_id: str
    correlation_id: Optional[str] = None  # Links related events
    action_id: Optional[str] = None  # Action being tracked
    operator_identity: Optional[str] = None  # Who triggered
    source_reference_id: Optional[str] = None  # Source system ID
    title: str = ""
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    sequence_number: int = 0  # Immutable ordering

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict with datetime serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "organization_id": self.organization_id,
            "correlation_id": self.correlation_id,
            "action_id": self.action_id,
            "operator_identity": self.operator_identity,
            "source_reference_id": self.source_reference_id,
            "title": self.title,
            "description": self.description,
            "metadata": self.metadata,
            "sequence_number": self.sequence_number,
        }


class OperationalTimeline:
    """Append-only operational timeline with replay safety."""

    def __init__(self):
        """Initialize timeline."""
        self._events: List[TimelineEvent] = []
        self._event_index: Dict[str, int] = {}  # event_id → index
        self._correlation_index: Dict[str, List[int]] = {}  # correlation_id → [indices]
        self._action_index: Dict[str, List[int]] = {}  # action_id → [indices]
        self._org_index: Dict[str, List[int]] = {}  # org_id → [indices]
        self._replay_seen: Dict[str, set] = {}  # org_id → {event_ids}
        self._sequence_counter = 0
        self._max_events_per_org = 5000  # Prevent unbounded growth

    def append_event(self, event: TimelineEvent) -> Optional[TimelineEvent]:
        """Append event to timeline. Detects and prevents replay."""
        # Replay detection: same event_id from same org
        org_seen = self._replay_seen.setdefault(event.organization_id, set())
        if event.event_id in org_seen:
            return None  # Duplicate, skip

        org_seen.add(event.event_id)

        # Assign sequence number (immutable ordering)
        self._sequence_counter += 1
        event.sequence_number = self._sequence_counter

        # Add to timeline
        index = len(self._events)
        self._events.append(event)
        self._event_index[event.event_id] = index

        # Index by correlation_id
        if event.correlation_id:
            if event.correlation_id not in self._correlation_index:
                self._correlation_index[event.correlation_id] = []
            self._correlation_index[event.correlation_id].append(index)

        # Index by action_id
        if event.action_id:
            if event.action_id not in self._action_index:
                self._action_index[event.action_id] = []
            self._action_index[event.action_id].append(index)

        # Index by organization_id
        if event.organization_id not in self._org_index:
            self._org_index[event.organization_id] = []
        self._org_index[event.organization_id].append(index)

        # Prune if too many events
        org_event_count = len(self._org_index.get(event.organization_id, []))
        if org_event_count > self._max_events_per_org:
            self._prune_oldest_org_events(event.organization_id, 500)

        return event

    def get_event_by_id(self, event_id: str) -> Optional[TimelineEvent]:
        """Get event by ID."""
        if event_id not in self._event_index:
            return None
        return self._events[self._event_index[event_id]]

    def get_events_by_correlation(self, correlation_id: str) -> List[TimelineEvent]:
        """Get all events linked by correlation_id."""
        indices = self._correlation_index.get(correlation_id, [])
        return [self._events[idx] for idx in indices if idx < len(self._events)]

    def get_events_by_action(self, action_id: str) -> List[TimelineEvent]:
        """Get all events for an action."""
        indices = self._action_index.get(action_id, [])
        return [self._events[idx] for idx in indices if idx < len(self._events)]

    def get_events_by_organization(
        self,
        organization_id: str,
        limit: int = 1000,
        event_type: Optional[TimelineEventType] = None,
    ) -> List[TimelineEvent]:
        """Get events for organization (newest first)."""
        indices = self._org_index.get(organization_id, [])
        events = [self._events[idx] for idx in indices if idx < len(self._events)]

        # Filter by type if specified
        if event_type:
            events = [e for e in events if e.event_type == event_type]

        # Sort by sequence descending (newest first)
        events.sort(key=lambda e: e.sequence_number, reverse=True)
        return events[:limit]

    def get_events_by_organization_and_type(
        self,
        organization_id: str,
        event_type: TimelineEventType,
        limit: int = 100,
    ) -> List[TimelineEvent]:
        """Get events of specific type for organization."""
        indices = self._org_index.get(organization_id, [])
        events = [
            self._events[idx]
            for idx in indices
            if idx < len(self._events) and self._events[idx].event_type == event_type
        ]
        events.sort(key=lambda e: e.sequence_number, reverse=True)
        return events[:limit]

    def get_timeline_snapshot(
        self, organization_id: str, limit: int = 500
    ) -> Dict[str, Any]:
        """Get timeline snapshot for organization."""
        events = self.get_events_by_organization(organization_id, limit=limit)
        return {
            "organization_id": organization_id,
            "total_events": len(self._org_index.get(organization_id, [])),
            "events": [e.to_dict() for e in events],
            "sequence_counter": self._sequence_counter,
        }

    def _prune_oldest_org_events(self, organization_id: str, count: int) -> int:
        """Remove oldest events for organization. Returns count removed."""
        indices = self._org_index.get(organization_id, [])
        if not indices:
            return 0

        # Sort indices and remove oldest
        sorted_indices = sorted(indices)[:count]
        removed = 0

        for idx in sorted_indices:
            if idx < len(self._events):
                event = self._events[idx]
                if event.event_id in self._event_index:
                    del self._event_index[event.event_id]

                # Remove from correlation index
                if event.correlation_id and event.correlation_id in self._correlation_index:
                    try:
                        self._correlation_index[event.correlation_id].remove(idx)
                    except ValueError:
                        pass

                # Remove from action index
                if event.action_id and event.action_id in self._action_index:
                    try:
                        self._action_index[event.action_id].remove(idx)
                    except ValueError:
                        pass

                removed += 1

        # Update org index
        self._org_index[organization_id] = [
            idx for idx in indices if idx not in sorted_indices
        ]
        return removed

    def count_events_by_type(
        self, organization_id: str
    ) -> Dict[str, int]:
        """Count events by type for organization."""
        indices = self._org_index.get(organization_id, [])
        events = [self._events[idx] for idx in indices if idx < len(self._events)]

        counts = {}
        for event in events:
            event_type_str = event.event_type.value
            counts[event_type_str] = counts.get(event_type_str, 0) + 1

        return counts


# Singleton instance
operational_timeline = OperationalTimeline()
