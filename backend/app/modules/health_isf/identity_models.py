"""Models for operational identity continuity in Health ISF."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class OperationalIdentity:
    organization_id: str
    identity_id: str
    identity_type: str
    role: str
    display_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OperationalSession:
    organization_id: str
    session_id: str
    identity_id: str
    websocket_connection_id: str | None
    started_at: datetime
    last_seen_at: datetime
    reconnect_count: int = 0
    active: bool = True


@dataclass(slots=True)
class PresenceSnapshot:
    organization_id: str
    active_sessions: int
    active_identities: int
    websocket_bound_sessions: int
    generated_at: datetime
