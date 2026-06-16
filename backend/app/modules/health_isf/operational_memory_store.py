"""Append-only tenant-isolated memory store backed by workflow audit logs."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.auth import normalize_role
from app.helpers import now, uuid4
from app.modules.health_isf.models import HealthISFWorkflowAuditLog

logger = logging.getLogger("amicor.health_isf.memory_store")


STREAM_EVENT_TYPE = {
    "incidents": "ai.memory.incidents",
    "operations": "ai.memory.operations",
    "predictions": "ai.memory.predictions",
    "executions": "ai.memory.executions",
}

DEFAULT_ROLE_SCOPE = {
    "incidents": ["admin", "super_admin_support", "dispatcher", "analytics_readonly"],
    "operations": ["admin", "super_admin_support", "dispatcher", "staff", "analytics_readonly"],
    "predictions": ["admin", "super_admin_support", "dispatcher", "analytics_readonly"],
    "executions": ["admin", "super_admin_support", "dispatcher"],
}


class OperationalMemoryStore:
    @staticmethod
    def _dumps(payload: dict[str, Any]) -> str:
        return json.dumps(payload, separators=(",", ":"), default=str)

    @staticmethod
    def _loads(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except Exception:
            return {"raw": raw}
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    @staticmethod
    def _make_replay_key(
        organization_id: str,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        replay_hint: str | None,
    ) -> str:
        seed = replay_hint or json.dumps(
            {
                "organization_id": organization_id,
                "stream": stream,
                "event_type": event_type,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    @classmethod
    def append_event(
        cls,
        db: Session,
        *,
        organization_id: str,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        actor_user_id: str | None,
        replay_hint: str | None = None,
        role_scope: list[str] | None = None,
    ) -> dict[str, Any]:
        stream_key = str(stream or "").strip().lower()
        if stream_key not in STREAM_EVENT_TYPE:
            raise ValueError(f"Unsupported memory stream: {stream}")

        replay_key = cls._make_replay_key(organization_id, stream_key, event_type, payload, replay_hint)

        existing_rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(HealthISFWorkflowAuditLog.organization_id == organization_id)
            .filter(HealthISFWorkflowAuditLog.event_type == STREAM_EVENT_TYPE[stream_key])
            .order_by(HealthISFWorkflowAuditLog.created_at.desc())
            .limit(300)
            .all()
        )
        for row in existing_rows:
            row_payload = cls._loads(row.payload)
            if row_payload.get("replay_key") == replay_key:
                return {
                    "event_id": row_payload.get("event_id") or row.id,
                    "replay_key": replay_key,
                    "deduplicated": True,
                    "recorded_at": row_payload.get("recorded_at") or row.created_at.isoformat(),
                }

        memory_event_id = str(uuid4())
        body = {
            "schema_version": "phase3.v1",
            "event_id": memory_event_id,
            "organization_id": organization_id,
            "stream": stream_key,
            "event_type": event_type,
            "payload": payload,
            "replay_key": replay_key,
            "immutable": True,
            "tenant_scope": organization_id,
            "role_scope": role_scope or DEFAULT_ROLE_SCOPE[stream_key],
            "actor_user_id": actor_user_id,
            "recorded_at": now().isoformat(),
        }
        row = HealthISFWorkflowAuditLog(
            id=str(uuid4()),
            organization_id=organization_id,
            workflow_execution_id=None,
            incident_id=None,
            escalation_id=None,
            event_type=STREAM_EVENT_TYPE[stream_key],
            actor_user_id=actor_user_id,
            payload=cls._dumps(body),
            created_at=now(),
        )
        db.add(row)
        try:
            db.commit()
        except Exception as exc:
            # Memory capture must not destabilize runtime operations.
            db.rollback()
            logger.warning(
                "memory_append_failed stream=%s org=%s event_type=%s error=%s",
                stream_key,
                organization_id,
                event_type,
                exc,
            )
            return {
                "event_id": memory_event_id,
                "replay_key": replay_key,
                "deduplicated": False,
                "recorded_at": body["recorded_at"],
                "write_failed": True,
            }
        return {
            "event_id": memory_event_id,
            "replay_key": replay_key,
            "deduplicated": False,
            "recorded_at": body["recorded_at"],
        }

    @classmethod
    def list_events(
        cls,
        db: Session,
        *,
        organization_id: str,
        stream: str,
        role: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        stream_key = str(stream or "").strip().lower()
        if stream_key not in STREAM_EVENT_TYPE:
            raise ValueError(f"Unsupported memory stream: {stream}")

        normalized_role = normalize_role(role)
        rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(HealthISFWorkflowAuditLog.organization_id == organization_id)
            .filter(HealthISFWorkflowAuditLog.event_type == STREAM_EVENT_TYPE[stream_key])
            .order_by(HealthISFWorkflowAuditLog.created_at.desc())
            .limit(limit)
            .all()
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = cls._loads(row.payload)
            allowed_roles = payload.get("role_scope") or DEFAULT_ROLE_SCOPE[stream_key]
            if normalized_role not in set(str(item) for item in allowed_roles):
                continue
            out.append(
                {
                    "event_id": payload.get("event_id") or row.id,
                    "organization_id": organization_id,
                    "stream": stream_key,
                    "event_type": payload.get("event_type") or "unknown",
                    "tenant_scope": payload.get("tenant_scope") or organization_id,
                    "role_scope": allowed_roles,
                    "payload": payload.get("payload") or {},
                    "replay_key": payload.get("replay_key") or "",
                    "immutable": True,
                    "recorded_at": payload.get("recorded_at") or row.created_at.isoformat(),
                    "actor_user_id": row.actor_user_id,
                }
            )
        return out
