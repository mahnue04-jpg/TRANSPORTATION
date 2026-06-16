"""In-memory operational identity registry with tenant isolation and append-only events."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict
from datetime import datetime
from threading import RLock
from typing import Any

from app.modules.health_isf.identity_models import OperationalIdentity, OperationalSession, PresenceSnapshot


def _record_runtime_websocket_reconnect() -> None:
    try:
        from app.modules.health_isf.runtime_governor import get_runtime_governor

        governor = get_runtime_governor()
        governor.record_websocket_reconnect()
    except Exception:
        return None


class OperationalIdentityRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._identities: dict[str, dict[str, OperationalIdentity]] = defaultdict(dict)
        self._sessions: dict[str, dict[str, OperationalSession]] = defaultdict(dict)
        self._events: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=5000))

    def register_identity(self, identity: OperationalIdentity) -> OperationalIdentity:
        with self._lock:
            self._identities[identity.organization_id][identity.identity_id] = identity
            self._append_event(
                identity.organization_id,
                "identity_registered",
                {
                    "identity_id": identity.identity_id,
                    "identity_type": identity.identity_type,
                    "role": identity.role,
                },
            )
            return identity

    def open_session(self, session: OperationalSession) -> OperationalSession:
        with self._lock:
            self._sessions[session.organization_id][session.session_id] = session
            self._append_event(
                session.organization_id,
                "session_opened",
                {
                    "session_id": session.session_id,
                    "identity_id": session.identity_id,
                    "websocket_connection_id": session.websocket_connection_id,
                },
            )
            return session

    def bind_websocket(self, organization_id: str, session_id: str, connection_id: str) -> OperationalSession | None:
        with self._lock:
            session = self._sessions.get(organization_id, {}).get(session_id)
            if session is None:
                return None
            session.websocket_connection_id = connection_id
            session.last_seen_at = datetime.utcnow()
            self._append_event(
                organization_id,
                "session_websocket_bound",
                {
                    "session_id": session_id,
                    "connection_id": connection_id,
                },
            )
            return session

    def reconnect_session(self, organization_id: str, session_id: str, connection_id: str) -> OperationalSession | None:
        with self._lock:
            session = self._sessions.get(organization_id, {}).get(session_id)
            if session is None:
                return None
            session.reconnect_count += 1
            session.websocket_connection_id = connection_id
            session.last_seen_at = datetime.utcnow()
            session.active = True
            _record_runtime_websocket_reconnect()
            self._append_event(
                organization_id,
                "session_reconnected",
                {
                    "session_id": session_id,
                    "connection_id": connection_id,
                    "reconnect_count": session.reconnect_count,
                },
            )
            return session

    def heartbeat(self, organization_id: str, session_id: str) -> OperationalSession | None:
        with self._lock:
            session = self._sessions.get(organization_id, {}).get(session_id)
            if session is None:
                return None
            session.last_seen_at = datetime.utcnow()
            return session

    def close_session(self, organization_id: str, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(organization_id, {}).get(session_id)
            if session is None:
                return False
            session.active = False
            session.last_seen_at = datetime.utcnow()
            self._append_event(
                organization_id,
                "session_closed",
                {
                    "session_id": session_id,
                    "identity_id": session.identity_id,
                },
            )
            return True

    def presence(self, organization_id: str) -> PresenceSnapshot:
        with self._lock:
            sessions = [s for s in self._sessions.get(organization_id, {}).values() if s.active]
            unique_identities = {s.identity_id for s in sessions}
            websocket_bound = sum(1 for s in sessions if bool(s.websocket_connection_id))
            return PresenceSnapshot(
                organization_id=organization_id,
                active_sessions=len(sessions),
                active_identities=len(unique_identities),
                websocket_bound_sessions=websocket_bound,
                generated_at=datetime.utcnow(),
            )

    def list_events(self, organization_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events.get(organization_id, []))
            return events[-max(1, limit):]

    def export_sessions(self, organization_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(item) for item in self._sessions.get(organization_id, {}).values()]

    def _append_event(self, organization_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self._events[organization_id].append(
            {
                "event_type": event_type,
                "payload": payload,
                "append_only": True,
                "created_at": datetime.utcnow().isoformat(),
            }
        )


_registry = OperationalIdentityRegistry()


def get_operational_identity_registry() -> OperationalIdentityRegistry:
    return _registry
