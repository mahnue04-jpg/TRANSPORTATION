"""
PHASE 7A: Live Operational Dashboard State
Centralized operational state aggregation for real-time command center visibility.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class OperationalCategory(str, Enum):
    """Event categories for operational dashboard."""
    ACTIVE_INCIDENT = "active_incident"
    EXECUTION_QUEUE = "execution_queue"
    PENDING_APPROVAL = "pending_approval"
    FAILED_ACTION = "failed_action"
    ROLLBACK_EVENT = "rollback_event"
    STAFFING_ALERT = "staffing_alert"
    DEPLOYMENT_WARNING = "deployment_warning"
    WEBSOCKET_HEALTH = "websocket_health"
    PROVIDER_DISRUPTION = "provider_disruption"
    DISPATCH_ESCALATION = "dispatch_escalation"


class OperationalSeverity(str, Enum):
    """Event severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class DashboardEvent:
    """Single operational event on dashboard."""
    event_id: str
    category: OperationalCategory
    severity: OperationalSeverity
    title: str
    description: str
    timestamp: datetime
    organization_id: str
    source_reference_id: Optional[str] = None  # action_id, incident_id, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)
    requires_attention: bool = False
    operator_acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict with datetime serialization."""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat() if self.timestamp else None
        d["acknowledged_at"] = (
            self.acknowledged_at.isoformat() if self.acknowledged_at else None
        )
        d["category"] = self.category.value
        d["severity"] = self.severity.value
        return d


@dataclass
class OperationalDashboardSnapshot:
    """Complete operational dashboard state snapshot."""
    organization_id: str
    timestamp: datetime
    active_incidents: List[DashboardEvent] = field(default_factory=list)
    execution_queue: List[DashboardEvent] = field(default_factory=list)
    pending_approvals: List[DashboardEvent] = field(default_factory=list)
    failed_actions: List[DashboardEvent] = field(default_factory=list)
    rollback_events: List[DashboardEvent] = field(default_factory=list)
    staffing_alerts: List[DashboardEvent] = field(default_factory=list)
    deployment_warnings: List[DashboardEvent] = field(default_factory=list)
    provider_disruptions: List[DashboardEvent] = field(default_factory=list)
    dispatch_escalations: List[DashboardEvent] = field(default_factory=list)

    # Aggregates
    total_active_incidents: int = 0
    total_pending_approvals: int = 0
    total_failed_actions: int = 0
    total_rollback_events: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0

    # Runtime health summary
    websocket_health: Optional[Dict[str, Any]] = None
    runtime_health: Optional[Dict[str, Any]] = None
    memory_health: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict with datetime serialization."""
        return {
            "organization_id": self.organization_id,
            "timestamp": self.timestamp.isoformat(),
            "active_incidents": [e.to_dict() for e in self.active_incidents],
            "execution_queue": [e.to_dict() for e in self.execution_queue],
            "pending_approvals": [e.to_dict() for e in self.pending_approvals],
            "failed_actions": [e.to_dict() for e in self.failed_actions],
            "rollback_events": [e.to_dict() for e in self.rollback_events],
            "staffing_alerts": [e.to_dict() for e in self.staffing_alerts],
            "deployment_warnings": [e.to_dict() for e in self.deployment_warnings],
            "provider_disruptions": [e.to_dict() for e in self.provider_disruptions],
            "dispatch_escalations": [e.to_dict() for e in self.dispatch_escalations],
            "summary": {
                "total_active_incidents": self.total_active_incidents,
                "total_pending_approvals": self.total_pending_approvals,
                "total_failed_actions": self.total_failed_actions,
                "total_rollback_events": self.total_rollback_events,
                "severity_breakdown": {
                    "critical": self.critical_count,
                    "high": self.high_count,
                    "medium": self.medium_count,
                    "low": self.low_count,
                },
            },
            "health": {
                "websocket": self.websocket_health or {},
                "runtime": self.runtime_health or {},
                "memory": self.memory_health or {},
            },
        }


class OperationalDashboardState:
    """Manages operational dashboard state and event aggregation."""

    def __init__(self):
        """Initialize dashboard state manager."""
        self._events: Dict[str, DashboardEvent] = {}  # event_id → event
        self._org_events: Dict[str, List[str]] = {}  # org_id → [event_ids]
        self._category_index: Dict[str, List[str]] = {}  # category → [event_ids]

    def add_event(self, event: DashboardEvent) -> None:
        """Add operational event to dashboard."""
        self._events[event.event_id] = event

        # Index by organization
        if event.organization_id not in self._org_events:
            self._org_events[event.organization_id] = []
        self._org_events[event.organization_id].append(event.event_id)

        # Index by category
        category_key = event.category.value
        if category_key not in self._category_index:
            self._category_index[category_key] = []
        self._category_index[category_key].append(event.event_id)

    def acknowledge_event(
        self, event_id: str, operator_identity: str
    ) -> Optional[DashboardEvent]:
        """Mark event as acknowledged by operator."""
        if event_id not in self._events:
            return None

        event = self._events[event_id]
        event.operator_acknowledged = True
        event.acknowledged_by = operator_identity
        event.acknowledged_at = datetime.utcnow()
        return event

    def get_events_by_category(
        self, organization_id: str, category: OperationalCategory
    ) -> List[DashboardEvent]:
        """Get all events for category."""
        category_key = category.value
        event_ids = self._category_index.get(category_key, [])
        org_event_ids = set(self._org_events.get(organization_id, []))
        return [
            self._events[eid]
            for eid in event_ids
            if eid in org_event_ids and eid in self._events
        ]

    def get_events_by_severity(
        self, organization_id: str, severity: OperationalSeverity
    ) -> List[DashboardEvent]:
        """Get all events for severity level."""
        org_event_ids = self._org_events.get(organization_id, [])
        return [
            self._events[eid]
            for eid in org_event_ids
            if eid in self._events and self._events[eid].severity == severity
        ]

    def get_unacknowledged_events(self, organization_id: str) -> List[DashboardEvent]:
        """Get unacknowledged events requiring attention."""
        org_event_ids = self._org_events.get(organization_id, [])
        return [
            self._events[eid]
            for eid in org_event_ids
            if eid in self._events
            and not self._events[eid].operator_acknowledged
            and self._events[eid].requires_attention
        ]

    def build_snapshot(
        self, organization_id: str, include_health: Optional[Dict[str, Any]] = None
    ) -> OperationalDashboardSnapshot:
        """Build dashboard snapshot for organization."""
        snapshot = OperationalDashboardSnapshot(
            organization_id=organization_id,
            timestamp=datetime.utcnow(),
        )

        org_event_ids = self._org_events.get(organization_id, [])

        # Categorize events
        for event_id in org_event_ids:
            if event_id not in self._events:
                continue
            event = self._events[event_id]

            if event.category == OperationalCategory.ACTIVE_INCIDENT:
                snapshot.active_incidents.append(event)
                snapshot.total_active_incidents += 1
            elif event.category == OperationalCategory.EXECUTION_QUEUE:
                snapshot.execution_queue.append(event)
            elif event.category == OperationalCategory.PENDING_APPROVAL:
                snapshot.pending_approvals.append(event)
                snapshot.total_pending_approvals += 1
            elif event.category == OperationalCategory.FAILED_ACTION:
                snapshot.failed_actions.append(event)
                snapshot.total_failed_actions += 1
            elif event.category == OperationalCategory.ROLLBACK_EVENT:
                snapshot.rollback_events.append(event)
                snapshot.total_rollback_events += 1
            elif event.category == OperationalCategory.STAFFING_ALERT:
                snapshot.staffing_alerts.append(event)
            elif event.category == OperationalCategory.DEPLOYMENT_WARNING:
                snapshot.deployment_warnings.append(event)
            elif event.category == OperationalCategory.PROVIDER_DISRUPTION:
                snapshot.provider_disruptions.append(event)
            elif event.category == OperationalCategory.DISPATCH_ESCALATION:
                snapshot.dispatch_escalations.append(event)

            # Count severity
            if event.severity == OperationalSeverity.CRITICAL:
                snapshot.critical_count += 1
            elif event.severity == OperationalSeverity.HIGH:
                snapshot.high_count += 1
            elif event.severity == OperationalSeverity.MEDIUM:
                snapshot.medium_count += 1
            elif event.severity == OperationalSeverity.LOW:
                snapshot.low_count += 1

        # Add health information
        if include_health:
            snapshot.websocket_health = include_health.get("websocket")
            snapshot.runtime_health = include_health.get("runtime")
            snapshot.memory_health = include_health.get("memory")

        # Sort by timestamp (newest first)
        for event_list in [
            snapshot.active_incidents,
            snapshot.execution_queue,
            snapshot.pending_approvals,
            snapshot.failed_actions,
            snapshot.rollback_events,
            snapshot.staffing_alerts,
            snapshot.deployment_warnings,
            snapshot.provider_disruptions,
            snapshot.dispatch_escalations,
        ]:
            event_list.sort(key=lambda e: e.timestamp, reverse=True)

        return snapshot

    def prune_old_events(
        self, organization_id: str, max_age_seconds: int = 86400
    ) -> int:
        """Remove events older than max_age_seconds. Returns count removed."""
        now = datetime.utcnow()
        org_event_ids = self._org_events.get(organization_id, [])
        removed = 0

        to_remove = []
        for event_id in org_event_ids:
            if event_id in self._events:
                event = self._events[event_id]
                age = (now - event.timestamp).total_seconds()
                if age > max_age_seconds:
                    to_remove.append(event_id)
                    removed += 1

        for event_id in to_remove:
            if event_id in self._events:
                del self._events[event_id]
            org_event_ids.remove(event_id)

        return removed


# Singleton instance
operational_dashboard = OperationalDashboardState()
