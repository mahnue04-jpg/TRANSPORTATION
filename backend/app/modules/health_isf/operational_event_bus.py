"""Tenant-scoped operational event bus with persistent replay and audit recovery."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import json
from threading import RLock
from typing import Any

from app.db.session import SessionLocal
from app.helpers import uuid4
from app.modules.health_isf.models import HealthISFWorkflowAuditLog
from app.modules.health_isf.operational_event_models import OperationalEvent, OperationalEventEnvelope


class OperationalEventBus:
    _PERSIST_PREFIX = "operational.event_bus."

    def __init__(self) -> None:
        self._lock = RLock()
        self._sequences: dict[str, int] = defaultdict(int)
        self._events: dict[str, deque[OperationalEvent]] = defaultdict(lambda: deque(maxlen=3000))
        self._nonce_seen: dict[str, dict[str, datetime]] = defaultdict(dict)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _coerce_role_scope(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        if isinstance(value, str):
            stripped = value.strip()
            return [stripped] if stripped else []
        return []

    @staticmethod
    def _coerce_payload(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        return {"value": value}

    def _seed_sequence_from_persistence(self, organization_id: str) -> None:
        if int(self._sequences.get(organization_id, 0)) > 0:
            return
        db = SessionLocal()
        try:
            rows = (
                db.query(HealthISFWorkflowAuditLog)
                .filter(HealthISFWorkflowAuditLog.organization_id == organization_id)
                .filter(HealthISFWorkflowAuditLog.event_type.like(f"{self._PERSIST_PREFIX}%"))
                .order_by(HealthISFWorkflowAuditLog.created_at.desc())
                .limit(400)
                .all()
            )
            max_sequence = 0
            for row in rows:
                raw = str(getattr(row, "payload", "") or "")
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                max_sequence = max(max_sequence, int(payload.get("sequence", 0) or 0))
            self._sequences[organization_id] = max_sequence
        except Exception:
            # Persistence is best-effort; event flow remains available from memory path.
            pass
        finally:
            db.close()

    def _persist_event(self, event: OperationalEvent) -> bool:
        db = SessionLocal()
        try:
            emitted_at = self._utc(event.emitted_at)
            row = HealthISFWorkflowAuditLog(
                id=str(uuid4()),
                organization_id=event.organization_id,
                workflow_execution_id=None,
                incident_id=None,
                escalation_id=None,
                event_type=f"{self._PERSIST_PREFIX}{str(event.event_type.value)}",
                actor_user_id=None,
                payload=json.dumps(
                    {
                        "event_id": event.event_id,
                        "sequence": int(event.sequence),
                        "event_type": str(event.event_type.value),
                        "role_scope": list(event.role_scope),
                        "payload": dict(event.payload),
                        "emitted_at": emitted_at.isoformat(),
                        "approval_governed": bool(event.approval_governed),
                        "replayable": bool(event.replayable),
                        "metadata": dict(event.metadata or {}),
                    }
                ),
            )
            db.add(row)
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    def _persisted_replay(self, organization_id: str, after_sequence: int, limit: int) -> list[OperationalEventEnvelope]:
        db = SessionLocal()
        try:
            rows = (
                db.query(HealthISFWorkflowAuditLog)
                .filter(HealthISFWorkflowAuditLog.organization_id == organization_id)
                .filter(HealthISFWorkflowAuditLog.event_type.like(f"{self._PERSIST_PREFIX}%"))
                .order_by(HealthISFWorkflowAuditLog.created_at.asc())
                .limit(max(1, limit * 8))
                .all()
            )
            envelopes: list[OperationalEventEnvelope] = []
            for row in rows:
                raw = str(getattr(row, "payload", "") or "")
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                sequence = int(payload.get("sequence", 0) or 0)
                if sequence <= max(0, after_sequence):
                    continue
                try:
                    envelopes.append(
                        OperationalEventEnvelope(
                            organization_id=organization_id,
                            sequence=sequence,
                            event_type=str(payload.get("event_type") or ""),
                            role_scope=self._coerce_role_scope(payload.get("role_scope")),
                            payload=self._coerce_payload(payload.get("payload")),
                            emitted_at=str(payload.get("emitted_at") or ""),
                            approval_governed=bool(payload.get("approval_governed", True)),
                            replayable=bool(payload.get("replayable", True)),
                        )
                    )
                except Exception:
                    # Skip malformed persisted rows while preserving replay continuity.
                    continue

            envelopes.sort(key=lambda item: int(item.sequence))
            return envelopes[:max(1, limit)]
        except Exception:
            return []
        finally:
            db.close()

    def publish(self, event: OperationalEvent, stale_after_seconds: int = 180) -> tuple[bool, str, OperationalEvent | None]:
        now_dt = datetime.now(timezone.utc)
        emitted_at = self._utc(event.emitted_at)
        if abs((now_dt - emitted_at).total_seconds()) > max(1, stale_after_seconds):
            return False, "stale_event_rejected", None

        with self._lock:
            self._seed_sequence_from_persistence(event.organization_id)
            if event.source_nonce:
                nonce_cache = self._nonce_seen[event.organization_id]
                first_seen = nonce_cache.get(event.source_nonce)
                if first_seen is not None:
                    return False, "duplicate_event_rejected", None
                nonce_cache[event.source_nonce] = now_dt.replace(tzinfo=None)
                cutoff = now_dt - timedelta(minutes=20)
                expired = [nonce for nonce, ts in nonce_cache.items() if self._utc(ts) < cutoff]
                for nonce in expired:
                    nonce_cache.pop(nonce, None)

            self._sequences[event.organization_id] += 1
            event.sequence = self._sequences[event.organization_id]
            self._events[event.organization_id].append(event)
            persisted = self._persist_event(event)
            return True, ("published_persisted" if persisted else "published_memory_only"), event

    def replay(self, organization_id: str, after_sequence: int = 0, limit: int = 200) -> list[OperationalEventEnvelope]:
        with self._lock:
            events = list(self._events.get(organization_id, []))

        filtered = [item for item in events if item.sequence > max(0, after_sequence)]
        memory_envelopes = [
            OperationalEventEnvelope(
                organization_id=item.organization_id,
                sequence=item.sequence,
                event_type=str(item.event_type.value),
                role_scope=list(item.role_scope),
                payload=dict(item.payload),
                emitted_at=self._utc(item.emitted_at).isoformat(),
                approval_governed=bool(item.approval_governed),
                replayable=bool(item.replayable),
            )
            for item in filtered
        ]
        persisted_envelopes = self._persisted_replay(organization_id, after_sequence, max(1, limit))

        merged: dict[int, OperationalEventEnvelope] = {}
        for item in persisted_envelopes:
            merged[int(item.sequence)] = item
        for item in memory_envelopes:
            merged[int(item.sequence)] = item

        ordered = [merged[key] for key in sorted(merged.keys()) if key > max(0, after_sequence)]
        max_limit = max(1, limit)
        if len(ordered) <= max_limit:
            return ordered

        # Initial reconnect bootstrap should favor latest authoritative state under high event volume.
        if int(after_sequence) <= 0:
            return ordered[-max_limit:]

        return ordered[:max_limit]

    def latest_sequence(self, organization_id: str) -> int:
        self._seed_sequence_from_persistence(organization_id)
        with self._lock:
            return int(self._sequences.get(organization_id, 0))

    def stats(self, organization_id: str) -> dict[str, Any]:
        self._seed_sequence_from_persistence(organization_id)
        with self._lock:
            total = len(self._events.get(organization_id, []))
            latest = int(self._sequences.get(organization_id, 0))
        persisted = self._persisted_replay(organization_id, after_sequence=0, limit=5000)
        return {
            "organization_id": organization_id,
            "total_events": max(total, len(persisted)),
            "in_memory_events": total,
            "persisted_events": len(persisted),
            "latest_sequence": latest,
            "tenant_scoped": True,
            "ordered": True,
            "replay_safe": True,
            "persistent_recovery_enabled": True,
        }


_event_bus = OperationalEventBus()


def get_operational_event_bus() -> OperationalEventBus:
    return _event_bus
