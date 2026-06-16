"""
PHASE 7A: Event Priority Engine
Maps events to severity levels and prioritizes recommendations.
"""

from typing import Any, Dict, List, Tuple
from enum import Enum


class EventPriority(str, Enum):
    """Event priority/severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EventPriorityEngine:
    """Determines event severity based on type and context."""

    def __init__(self):
        """Initialize priority engine with default rules."""
        self._priority_map: Dict[str, EventPriority] = {
            # CRITICAL severity
            "deployment_outage": EventPriority.CRITICAL,
            "dispatch_failure": EventPriority.CRITICAL,
            "websocket_collapse": EventPriority.CRITICAL,
            "execution_corruption": EventPriority.CRITICAL,
            "memory_persistence_failure": EventPriority.CRITICAL,
            "approval_system_failure": EventPriority.CRITICAL,

            # HIGH severity
            "staffing_shortage": EventPriority.HIGH,
            "provider_instability": EventPriority.HIGH,
            "repeated_rollback": EventPriority.HIGH,
            "queue_congestion": EventPriority.HIGH,
            "execution_timeout": EventPriority.HIGH,
            "operator_escalation": EventPriority.HIGH,

            # MEDIUM severity
            "latency_increase": EventPriority.MEDIUM,
            "reconnect_spikes": EventPriority.MEDIUM,
            "approval_backlog": EventPriority.MEDIUM,
            "execution_delay": EventPriority.MEDIUM,
            "deployment_warning": EventPriority.MEDIUM,

            # LOW severity
            "informational_runtime": EventPriority.LOW,
            "metrics_update": EventPriority.LOW,
            "checkpoint_created": EventPriority.LOW,
            "routine_maintenance": EventPriority.LOW,
        }

        # Severity boost rules (context-based)
        self._severity_boosts: Dict[str, Tuple[str, EventPriority]] = {
            # If event repeats frequently, boost severity
            "repeated_failures": (
                "execution_failed",
                EventPriority.HIGH,
            ),
            "repeated_rollbacks": ("rollback_triggered", EventPriority.HIGH),
            "repeated_timeouts": ("execution_timeout", EventPriority.HIGH),
        }

        # Severity reduction rules
        self._severity_reductions: Dict[str, Tuple[str, EventPriority]] = {
            # If event is expected/scheduled, reduce severity
            "scheduled_maintenance": ("deployment_event", EventPriority.LOW),
            "expected_downtime": ("websocket_reconnect", EventPriority.LOW),
        }

    def get_event_priority(
        self,
        event_type: str,
        context: Dict[str, Any] | None = None,
    ) -> EventPriority:
        """Determine event priority based on type and context.
        
        Args:
            event_type: Type of event (e.g., "deployment_outage")
            context: Additional context (e.g., {"repeat_count": 5})
        
        Returns:
            EventPriority level
        """
        context = context or {}

        # Base priority from map
        priority = self._priority_map.get(event_type, EventPriority.LOW)

        # Check for boost rules
        repeat_count = context.get("repeat_count", 0)
        if repeat_count > 3 and priority == EventPriority.MEDIUM:
            # Boost repeated events from MEDIUM to HIGH
            priority = EventPriority.HIGH
        elif repeat_count > 5 and priority != EventPriority.CRITICAL:
            # Boost repeated events to HIGH
            priority = EventPriority.HIGH

        # Check for reduction rules
        is_scheduled = context.get("is_scheduled", False)
        if is_scheduled and priority == EventPriority.LOW:
            # Already low, keep it low
            pass
        elif is_scheduled and priority == EventPriority.MEDIUM:
            # Reduce scheduled events
            priority = EventPriority.LOW

        return priority

    def register_event_type(
        self, event_type: str, priority: EventPriority
    ) -> None:
        """Register custom event type with priority."""
        self._priority_map[event_type] = priority

    def get_priority_breakdown(self) -> Dict[EventPriority, List[str]]:
        """Get breakdown of all registered events by priority."""
        breakdown: Dict[EventPriority, List[str]] = {
            EventPriority.CRITICAL: [],
            EventPriority.HIGH: [],
            EventPriority.MEDIUM: [],
            EventPriority.LOW: [],
        }

        for event_type, priority in self._priority_map.items():
            breakdown[priority].append(event_type)

        return breakdown

    def should_trigger_recommendation(
        self, event_type: str, context: Dict[str, Any] | None = None
    ) -> bool:
        """Determine if event should trigger Nova recommendation."""
        priority = self.get_event_priority(event_type, context)
        # Only CRITICAL and HIGH trigger recommendations
        return priority in {EventPriority.CRITICAL, EventPriority.HIGH}

    def should_surface_in_dashboard(
        self, event_type: str, context: Dict[str, Any] | None = None
    ) -> bool:
        """Determine if event should appear in operational dashboard."""
        priority = self.get_event_priority(event_type, context)
        # All but LOW severity appear in dashboard
        return priority != EventPriority.LOW

    def should_require_operator_action(
        self, event_type: str, context: Dict[str, Any] | None = None
    ) -> bool:
        """Determine if event requires immediate operator action."""
        priority = self.get_event_priority(event_type, context)
        # CRITICAL and HIGH require action
        return priority in {EventPriority.CRITICAL, EventPriority.HIGH}

    def sort_events_by_priority(
        self,
        events: List[Tuple[str, Dict[str, Any]]],
    ) -> List[Tuple[str, Dict[str, Any], EventPriority]]:
        """Sort events by priority (highest first).
        
        Args:
            events: List of (event_type, context) tuples
        
        Returns:
            Sorted list of (event_type, context, priority) tuples
        """
        events_with_priority = [
            (event_type, context, self.get_event_priority(event_type, context))
            for event_type, context in events
        ]

        # Custom sort: CRITICAL > HIGH > MEDIUM > LOW
        priority_order = {
            EventPriority.CRITICAL: 0,
            EventPriority.HIGH: 1,
            EventPriority.MEDIUM: 2,
            EventPriority.LOW: 3,
        }

        events_with_priority.sort(
            key=lambda x: priority_order[x[2]]
        )

        return events_with_priority


# Singleton instance
event_priority_engine = EventPriorityEngine()

# Pre-register common event types based on specification
event_priority_engine.register_event_type("deployment_outage", EventPriority.CRITICAL)
event_priority_engine.register_event_type("dispatch_failure", EventPriority.CRITICAL)
event_priority_engine.register_event_type("websocket_collapse", EventPriority.CRITICAL)
event_priority_engine.register_event_type("execution_corruption", EventPriority.CRITICAL)

event_priority_engine.register_event_type("staffing_shortage", EventPriority.HIGH)
event_priority_engine.register_event_type("provider_instability", EventPriority.HIGH)
event_priority_engine.register_event_type("repeated_rollback", EventPriority.HIGH)
event_priority_engine.register_event_type("queue_congestion", EventPriority.HIGH)

event_priority_engine.register_event_type("latency_increase", EventPriority.MEDIUM)
event_priority_engine.register_event_type("reconnect_spikes", EventPriority.MEDIUM)
event_priority_engine.register_event_type("approval_backlog", EventPriority.MEDIUM)

event_priority_engine.register_event_type("informational_runtime", EventPriority.LOW)
event_priority_engine.register_event_type("metrics_update", EventPriority.LOW)
