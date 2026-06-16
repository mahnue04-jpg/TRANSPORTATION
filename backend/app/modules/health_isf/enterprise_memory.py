"""Persistent enterprise operational memory with tenant isolation and TTL."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.models import HealthISFWorkflowAuditLog


class EnterpriseMemoryLayer:
    _locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def _lock(cls, organization_id: str) -> asyncio.Lock:
        lock = cls._locks.get(organization_id)
        if lock is None:
            lock = asyncio.Lock()
            cls._locks[organization_id] = lock
        return lock

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

    @classmethod
    async def write_memory(
        cls,
        db: Session,
        *,
        organization_id: str,
        memory_type: str,
        context: dict[str, Any],
        actor_user_id: str | None,
        ttl_seconds: int = 86400,
        replay_key: str | None = None,
    ) -> dict[str, Any]:
        async with cls._lock(organization_id):
            key_seed = replay_key or cls._dumps({"memory_type": memory_type, "context": context})
            memory_key = hashlib.sha256(key_seed.encode("utf-8")).hexdigest()

            existing = (
                db.query(HealthISFWorkflowAuditLog)
                .filter(
                    HealthISFWorkflowAuditLog.organization_id == organization_id,
                    HealthISFWorkflowAuditLog.event_type == f"enterprise_memory.{memory_type}",
                )
                .order_by(HealthISFWorkflowAuditLog.created_at.desc())
                .limit(100)
                .all()
            )
            for row in existing:
                payload = cls._loads(row.payload)
                if payload.get("memory_key") == memory_key:
                    return {
                        "memory_id": payload.get("memory_id") or row.id,
                        "memory_key": memory_key,
                        "deduplicated": True,
                        "expires_at": payload.get("expires_at"),
                    }

            expires_at = now() + timedelta(seconds=max(60, int(ttl_seconds)))
            memory_id = str(uuid4())
            payload = {
                "memory_id": memory_id,
                "memory_key": memory_key,
                "memory_type": memory_type,
                "organization_id": organization_id,
                "context": context,
                "recorded_at": now().isoformat(),
                "expires_at": expires_at.isoformat(),
                "ttl_seconds": int(ttl_seconds),
                "actor_user_id": actor_user_id,
            }
            record = HealthISFWorkflowAuditLog(
                id=str(uuid4()),
                organization_id=organization_id,
                workflow_execution_id=None,
                incident_id=None,
                escalation_id=None,
                event_type=f"enterprise_memory.{memory_type}",
                actor_user_id=actor_user_id,
                payload=cls._dumps(payload),
                created_at=now(),
            )
            db.add(record)
            db.commit()
            return {
                "memory_id": memory_id,
                "memory_key": memory_key,
                "deduplicated": False,
                "expires_at": expires_at.isoformat(),
            }

    @classmethod
    def query_memory(
        cls,
        db: Session,
        *,
        organization_id: str,
        memory_type: str | None = None,
        limit: int = 200,
        include_expired: bool = False,
    ) -> list[dict[str, Any]]:
        query = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(HealthISFWorkflowAuditLog.organization_id == organization_id)
            .filter(HealthISFWorkflowAuditLog.event_type.like("enterprise_memory.%"))
            .order_by(HealthISFWorkflowAuditLog.created_at.desc())
            .limit(limit)
        )
        rows = query.all()
        out: list[dict[str, Any]] = []
        now_iso = now().isoformat()
        for row in rows:
            payload = cls._loads(row.payload)
            mtype = str(payload.get("memory_type") or row.event_type.replace("enterprise_memory.", ""))
            if memory_type and mtype != memory_type:
                continue
            expires_at = str(payload.get("expires_at") or "")
            is_expired = bool(expires_at and expires_at < now_iso)
            if is_expired and not include_expired:
                continue
            out.append(
                {
                    "memory_id": payload.get("memory_id") or row.id,
                    "memory_type": mtype,
                    "organization_id": organization_id,
                    "context": payload.get("context") or {},
                    "recorded_at": payload.get("recorded_at") or row.created_at.isoformat(),
                    "expires_at": expires_at or None,
                    "is_expired": is_expired,
                    "memory_key": payload.get("memory_key"),
                    "event_correlation": payload.get("context", {}).get("event_correlation"),
                }
            )
        return out

    @classmethod
    def prune_expired(
        cls,
        db: Session,
        *,
        organization_id: str,
        limit: int = 500,
    ) -> int:
        rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(HealthISFWorkflowAuditLog.organization_id == organization_id)
            .filter(HealthISFWorkflowAuditLog.event_type.like("enterprise_memory.%"))
            .order_by(HealthISFWorkflowAuditLog.created_at.asc())
            .limit(limit)
            .all()
        )
        now_iso = now().isoformat()
        deleted = 0
        for row in rows:
            payload = cls._loads(row.payload)
            expires_at = str(payload.get("expires_at") or "")
            if expires_at and expires_at < now_iso:
                db.delete(row)
                deleted += 1
        if deleted:
            db.commit()
        return deleted

    @classmethod
    async def record_incident_history(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        context: dict[str, Any],
        ttl_seconds: int = 30 * 24 * 3600,
    ) -> dict[str, Any]:
        return await cls.write_memory(
            db,
            organization_id=organization_id,
            memory_type="incident_history",
            context=context,
            actor_user_id=actor_user_id,
            ttl_seconds=ttl_seconds,
        )

    @classmethod
    async def record_performance_memory(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        context: dict[str, Any],
        ttl_seconds: int = 14 * 24 * 3600,
    ) -> dict[str, Any]:
        return await cls.write_memory(
            db,
            organization_id=organization_id,
            memory_type="performance_memory",
            context=context,
            actor_user_id=actor_user_id,
            ttl_seconds=ttl_seconds,
        )

    @classmethod
    async def record_dispatch_pattern_memory(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        context: dict[str, Any],
        ttl_seconds: int = 14 * 24 * 3600,
    ) -> dict[str, Any]:
        return await cls.write_memory(
            db,
            organization_id=organization_id,
            memory_type="dispatch_pattern_memory",
            context=context,
            actor_user_id=actor_user_id,
            ttl_seconds=ttl_seconds,
        )

    @classmethod
    async def record_escalation_memory(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        context: dict[str, Any],
        ttl_seconds: int = 30 * 24 * 3600,
    ) -> dict[str, Any]:
        return await cls.write_memory(
            db,
            organization_id=organization_id,
            memory_type="escalation_memory",
            context=context,
            actor_user_id=actor_user_id,
            ttl_seconds=ttl_seconds,
        )

    @classmethod
    async def record_workload_trend_memory(
        cls,
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None,
        context: dict[str, Any],
        ttl_seconds: int = 7 * 24 * 3600,
    ) -> dict[str, Any]:
        return await cls.write_memory(
            db,
            organization_id=organization_id,
            memory_type="workload_trend_memory",
            context=context,
            actor_user_id=actor_user_id,
            ttl_seconds=ttl_seconds,
        )
