"""Operational identity continuity engine for sessions, roles, and websocket reconnects."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.helpers import uuid4
from app.modules.health_isf.identity_models import OperationalIdentity, OperationalSession
from app.modules.health_isf.identity_registry import get_operational_identity_registry


class OperationalIdentityEngine:
    @staticmethod
    def register_identity(
        *,
        organization_id: str,
        identity_id: str,
        identity_type: str,
        role: str,
        display_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> OperationalIdentity:
        registry = get_operational_identity_registry()
        identity = OperationalIdentity(
            organization_id=organization_id,
            identity_id=identity_id,
            identity_type=identity_type,
            role=role,
            display_name=display_name,
            metadata=metadata or {},
        )
        return registry.register_identity(identity)

    @staticmethod
    def open_session(
        *,
        organization_id: str,
        identity_id: str,
        websocket_connection_id: str | None,
        session_id: str | None = None,
    ) -> OperationalSession:
        registry = get_operational_identity_registry()
        current_time = datetime.utcnow()
        session = OperationalSession(
            organization_id=organization_id,
            session_id=session_id or str(uuid4()),
            identity_id=identity_id,
            websocket_connection_id=websocket_connection_id,
            started_at=current_time,
            last_seen_at=current_time,
        )
        return registry.open_session(session)

    @staticmethod
    def heartbeat(*, organization_id: str, session_id: str) -> OperationalSession | None:
        return get_operational_identity_registry().heartbeat(organization_id, session_id)

    @staticmethod
    def bind_websocket(*, organization_id: str, session_id: str, connection_id: str) -> OperationalSession | None:
        return get_operational_identity_registry().bind_websocket(organization_id, session_id, connection_id)

    @staticmethod
    def reconnect(*, organization_id: str, session_id: str, connection_id: str) -> OperationalSession | None:
        return get_operational_identity_registry().reconnect_session(organization_id, session_id, connection_id)

    @staticmethod
    def close_session(*, organization_id: str, session_id: str) -> bool:
        return get_operational_identity_registry().close_session(organization_id, session_id)

    @staticmethod
    def continuity_snapshot(organization_id: str) -> dict[str, Any]:
        registry = get_operational_identity_registry()
        presence = registry.presence(organization_id)
        return {
            "organization_id": organization_id,
            "operational_session_continuity": {
                "active_sessions": presence.active_sessions,
                "active_identities": presence.active_identities,
                "websocket_bound_sessions": presence.websocket_bound_sessions,
            },
            "role_continuity": {
                "enforced": True,
                "identity_scoped": True,
            },
            "tenant_continuity": {
                "enforced": True,
                "organization_id": organization_id,
            },
            "reconnect_continuity": {
                "supported": True,
                "append_only_events": True,
            },
            "events": registry.list_events(organization_id, limit=100),
            "sessions": registry.export_sessions(organization_id),
            "generated_at": datetime.utcnow().isoformat(),
        }
