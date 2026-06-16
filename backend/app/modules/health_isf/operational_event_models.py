"""Operational event models for distributed synchronization fabric."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class OperationalEventType(str, Enum):
    RIDE_REQUESTED = "ride_requested"
    RIDE_ASSIGNED = "ride_assigned"
    RIDE_UPDATED = "ride_updated"
    RIDE_COMPLETED = "ride_completed"
    DRIVER_STATE_CHANGED = "driver_state_changed"
    PROVIDER_STATE_CHANGED = "provider_state_changed"
    WORKFLOW_TRANSITION = "workflow_transition"
    SUPERVISION_ALERT = "supervision_alert"
    INCIDENT = "incident_event"
    DISPATCH_RECOMMENDATION = "dispatch_recommendation_event"
    COORDINATION_RECOMMENDATION = "coordination_recommendation_event"
    GEOSPATIAL_UPDATE = "geospatial_update_event"
    ESCALATION = "escalation_event"
    PROVIDER_STATUS = "provider_status_event"
    DRIVER_STATE = "driver_state_event"
    WEBSOCKET_RECONNECT = "websocket_reconnect_event"
    OPERATIONAL_ALERT = "operational_alert_broadcast_event"


@dataclass(slots=True)
class OperationalEvent:
    organization_id: str
    event_id: str
    event_type: OperationalEventType
    role_scope: list[str]
    payload: dict[str, Any]
    emitted_at: datetime
    sequence: int = 0
    source_nonce: str | None = None
    replayable: bool = True
    approval_governed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OperationalReplayCursor:
    organization_id: str
    last_sequence: int
    generated_at: datetime


@dataclass(slots=True)
class OperationalEventEnvelope:
    organization_id: str
    sequence: int
    event_type: str
    role_scope: list[str]
    payload: dict[str, Any]
    emitted_at: str
    approval_governed: bool
    replayable: bool
