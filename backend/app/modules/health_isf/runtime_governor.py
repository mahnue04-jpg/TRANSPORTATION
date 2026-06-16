"""
Runtime governor for Health ISF operational stability.

This module adds centralized runtime supervision without changing existing
dispatch, lifecycle, websocket, or persistence semantics.
"""

from __future__ import annotations

import logging
import threading
import time
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.modules.health_isf.models import HealthISFRide, RideStatus
from app.modules.health_isf.realtime_service import ConcurrentAssignmentService

logger = logging.getLogger("amicor.health_isf.runtime_governor")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_iso_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return value
        except Exception:
            return _utcnow().isoformat()
    return _utcnow().isoformat()


def _json_safe(value: Any) -> Any:
    """Normalize telemetry payloads to JSON-serializable primitives."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class RuntimeGovernorService:
    """Centralized runtime supervisor with failure-isolated background cleanup."""

    def __init__(
        self,
        db_session_factory: Callable[[], Session],
        cleanup_interval_seconds: int = 60,
        stale_after_seconds: int = 300,
    ) -> None:
        self._db_session_factory = db_session_factory
        self._cleanup_interval_seconds = max(5, int(cleanup_interval_seconds))
        self._stale_after_seconds = max(30, int(stale_after_seconds))

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._cleanup_thread: Optional[threading.Thread] = None

        self._active_workflows: dict[str, dict[str, Any]] = {}
        self._completed_workflows = 0
        self._cleanup_cycles = 0
        self._orphan_workflows_detected = 0
        self._stale_events_rejected = 0
        self._replay_events_rejected = 0
        self._duplicate_events_rejected = 0
        self._lifecycle_transition_rejects = 0
        self._websocket_connects = 0
        self._websocket_disconnects = 0
        self._websocket_reconnects = 0
        self._crash_recovery_runs = 0
        self._latest_cleanup_timestamp: str | None = None
        self._latest_crash_recovery_timestamp: str | None = None
        self._last_health_snapshot: dict[str, Any] = {
            "timestamp": _utcnow().isoformat(),
            "status": "initializing",
            "active_workflows": 0,
            "completed_workflows": 0,
            "orphan_workflows": 0,
            "orphan_workflows_detected": 0,
            "stale_events_rejected": 0,
            "replay_events_rejected": 0,
            "duplicate_events_rejected": 0,
            "lifecycle_transition_rejects": 0,
            "websocket_connects": 0,
            "websocket_disconnects": 0,
            "websocket_reconnects": 0,
            "expired_locks_cleaned": 0,
            "cleanup_cycles": 0,
            "crash_recovery_runs": 0,
            "latest_cleanup_timestamp": None,
            "latest_crash_recovery_timestamp": None,
            "integrity": {
                "ok": True,
                "issues": [],
            },
        }

    # ---------------------------------------------------------------------
    # Lifecycle hooks
    # ---------------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._cleanup_thread and self._cleanup_thread.is_alive():
                logger.info({
                    "event": "runtime_governor_start_skipped",
                    "reason": "already_running",
                })
                return

            self._stop_event.clear()
            self._run_crash_recovery_once()

            self._cleanup_thread = threading.Thread(
                target=self._cleanup_scheduler_loop,
                name="runtime-governor-cleanup",
                daemon=True,
            )
            self._cleanup_thread.start()

            logger.info({
                "event": "runtime_governor_started",
                "cleanup_interval_seconds": self._cleanup_interval_seconds,
                "stale_after_seconds": self._stale_after_seconds,
            })

    def shutdown(self, join_timeout_seconds: float = 5.0) -> None:
        thread: Optional[threading.Thread]
        with self._lock:
            thread = self._cleanup_thread
            self._stop_event.set()

        if thread and thread.is_alive():
            thread.join(timeout=max(0.1, float(join_timeout_seconds)))

        with self._lock:
            self._cleanup_thread = None

        logger.info({"event": "runtime_governor_stopped"})

    # ---------------------------------------------------------------------
    # Registry operations
    # ---------------------------------------------------------------------
    def register_workflow(
        self,
        workflow_id: str,
        ride_id: str,
        organization_id: str,
        lifecycle_state: str,
        driver_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = _utcnow()
        payload = {
            "workflow_id": workflow_id,
            "ride_id": ride_id,
            "organization_id": organization_id,
            "driver_id": driver_id,
            "lifecycle_state": lifecycle_state,
            "last_seen": now,
            "registered_at": now,
            "metadata": dict(metadata or {}),
        }
        with self._lock:
            existing = self._active_workflows.get(workflow_id)
            if existing:
                # Duplicate registration prevention: merge instead of re-adding.
                existing.update(payload)
                existing["registered_at"] = existing.get("registered_at", now)
                logger.info({
                    "event": "runtime_workflow_registration_deduped",
                    "workflow_id": workflow_id,
                    "ride_id": ride_id,
                    "state": lifecycle_state,
                })
                return
            self._active_workflows[workflow_id] = payload

        logger.info({
            "event": "runtime_workflow_registered",
            "workflow_id": workflow_id,
            "ride_id": ride_id,
            "state": lifecycle_state,
            "driver_id": driver_id,
        })

    def update_workflow(
        self,
        workflow_id: str,
        lifecycle_state: str,
        driver_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = _utcnow()
        with self._lock:
            existing = self._active_workflows.get(workflow_id)
            if not existing:
                logger.info({
                    "event": "runtime_workflow_update_skipped",
                    "workflow_id": workflow_id,
                    "reason": "not_registered",
                })
                return
            existing["lifecycle_state"] = lifecycle_state
            existing["driver_id"] = driver_id
            existing["last_seen"] = now
            if metadata:
                merged = dict(existing.get("metadata") or {})
                merged.update(metadata)
                existing["metadata"] = merged

        logger.info({
            "event": "runtime_workflow_updated",
            "workflow_id": workflow_id,
            "state": lifecycle_state,
            "driver_id": driver_id,
        })

    def unregister_workflow(self, workflow_id: str, reason: str) -> None:
        removed = None
        with self._lock:
            removed = self._active_workflows.pop(workflow_id, None)
            if removed is not None:
                self._increment_completed_workflows(1)

        if removed:
            logger.info({
                "event": "runtime_workflow_unregistered",
                "workflow_id": workflow_id,
                "ride_id": removed.get("ride_id"),
                "reason": reason,
            })

    # ---------------------------------------------------------------------
    # Health, integrity, and cleanup
    # ---------------------------------------------------------------------
    def get_health_snapshot(self) -> dict[str, Any]:
        with self._lock:
            snapshot = dict(self._last_health_snapshot)
        return self._normalize_snapshot(snapshot)

    def generate_health_snapshot(self) -> dict[str, Any]:
        integrity = self._validate_integrity_invariants()
        orphan_ids = self._detect_orphan_workflows()
        with self._lock:
            active_count = len(self._active_workflows)
            orphan_count = min(active_count, len(orphan_ids))
            snapshot = {
                "timestamp": _utcnow().isoformat(),
                "status": "degraded" if not integrity["ok"] else "healthy",
                "active_workflows": active_count,
                "completed_workflows": int(self._completed_workflows),
                "orphan_workflows": orphan_count,
                "orphan_workflows_detected": int(self._orphan_workflows_detected),
                "stale_events_rejected": int(self._stale_events_rejected),
                "replay_events_rejected": int(self._replay_events_rejected),
                "duplicate_events_rejected": int(self._duplicate_events_rejected),
                "lifecycle_transition_rejects": int(self._lifecycle_transition_rejects),
                "websocket_connects": int(self._websocket_connects),
                "websocket_disconnects": int(self._websocket_disconnects),
                "websocket_reconnects": int(self._websocket_reconnects),
                "expired_locks_cleaned": 0,
                "cleanup_cycles": int(self._cleanup_cycles),
                "crash_recovery_runs": int(self._crash_recovery_runs),
                "latest_cleanup_timestamp": self._latest_cleanup_timestamp,
                "latest_crash_recovery_timestamp": self._latest_crash_recovery_timestamp,
                "integrity": integrity,
            }
            self._last_health_snapshot = snapshot
            return self._normalize_snapshot(snapshot)

    def record_duplicate_event_reject(self) -> None:
        with self._lock:
            self._duplicate_events_rejected += 1

    def record_replay_event_reject(self) -> None:
        with self._lock:
            self._replay_events_rejected += 1

    def record_stale_event_reject(self) -> None:
        with self._lock:
            self._stale_events_rejected += 1

    def record_lifecycle_transition_reject(self) -> None:
        with self._lock:
            self._lifecycle_transition_rejects += 1

    def record_websocket_connect(self) -> None:
        with self._lock:
            self._websocket_connects += 1

    def record_websocket_disconnect(self) -> None:
        with self._lock:
            self._websocket_disconnects += 1

    def record_websocket_reconnect(self) -> None:
        with self._lock:
            self._websocket_reconnects += 1

    def _validate_integrity_invariants(self) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        with self._lock:
            entries = list(self._active_workflows.values())

        driver_bindings: dict[str, str] = {}
        ride_bindings: set[str] = set()
        for entry in entries:
            ride_id = str(entry.get("ride_id") or "")
            driver_id = str(entry.get("driver_id") or "")
            state = str(entry.get("lifecycle_state") or "")
            if not ride_id:
                issues.append({"type": "missing_ride_id", "workflow_id": entry.get("workflow_id")})
                continue
            if ride_id in ride_bindings and state not in {
                RideStatus.COMPLETED.value,
                RideStatus.CANCELLED.value,
                RideStatus.FAILED.value,
            }:
                issues.append({"type": "duplicate_ride_binding", "ride_id": ride_id})
            ride_bindings.add(ride_id)

            if driver_id:
                bound_ride = driver_bindings.get(driver_id)
                if bound_ride and bound_ride != ride_id:
                    issues.append({
                        "type": "driver_double_booking",
                        "driver_id": driver_id,
                        "ride_a": bound_ride,
                        "ride_b": ride_id,
                    })
                else:
                    driver_bindings[driver_id] = ride_id

        return {
            "ok": len(issues) == 0,
            "issues": issues,
        }

    def _detect_orphan_workflows(self) -> list[str]:
        stale_cutoff = _utcnow() - timedelta(seconds=self._stale_after_seconds)
        with self._lock:
            entries = list(self._active_workflows.items())

        orphan_ids: list[str] = []
        ride_ids = [str(item[1].get("ride_id") or "") for item in entries if item[1].get("ride_id")]

        ride_state_by_id: dict[str, str] = {}
        if ride_ids:
            db = self._db_session_factory()
            try:
                rides = db.query(HealthISFRide).filter(HealthISFRide.id.in_(ride_ids)).all()
                for ride in rides:
                    normalized_state = str(getattr(ride, "lifecycle_state", None) or ride.status or "")
                    ride_state_by_id[str(ride.id)] = normalized_state
            finally:
                db.close()

        for workflow_id, entry in entries:
            last_seen = entry.get("last_seen")
            ride_id = str(entry.get("ride_id") or "")
            if isinstance(last_seen, datetime) and last_seen < stale_cutoff:
                orphan_ids.append(workflow_id)
                continue

            ride_state = ride_state_by_id.get(ride_id)
            if ride_state is None:
                orphan_ids.append(workflow_id)
                continue

            if ride_state in {
                RideStatus.COMPLETED.value,
                RideStatus.CANCELLED.value,
                RideStatus.FAILED.value,
            }:
                orphan_ids.append(workflow_id)

        return orphan_ids

    def cleanup_orphans_and_stale(self) -> dict[str, Any]:
        logger.info({"event": "production_readiness_audit_started"})
        orphan_ids = self._detect_orphan_workflows()
        cleanup_timestamp = _utcnow().isoformat()
        cleaned = 0
        for workflow_id in list(dict.fromkeys(orphan_ids)):
            try:
                with self._lock:
                    exists = workflow_id in self._active_workflows
                if not exists:
                    continue
                self.unregister_workflow(workflow_id, reason="orphan_or_stale")
                cleaned += 1
            except Exception as exc:
                logger.warning({
                    "event": "runtime_governor_cleanup_unregister_failed",
                    "workflow_id": workflow_id,
                    "error": str(exc),
                })

        expired_locks_cleaned = 0
        db = self._db_session_factory()
        try:
            expired_locks_cleaned = int(ConcurrentAssignmentService.cleanup_expired_locks(db) or 0)
        except Exception as exc:
            logger.error({
                "event": "runtime_governor_lock_cleanup_failed",
                "error": str(exc),
            })
            db.rollback()
        finally:
            db.close()

        integrity = self._validate_integrity_invariants()
        with self._lock:
            self._orphan_workflows_detected += len(orphan_ids)
            self._cleanup_cycles += 1
            self._latest_cleanup_timestamp = cleanup_timestamp
            active_count = len(self._active_workflows)
            orphan_remaining = max(0, len(orphan_ids) - cleaned)
            orphan_remaining = min(active_count, orphan_remaining)

        snapshot = {
            "timestamp": cleanup_timestamp,
            "status": "degraded" if not integrity["ok"] else "healthy",
            "active_workflows": active_count,
            "completed_workflows": int(self._completed_workflows),
            "orphan_workflows": orphan_remaining,
            "orphan_workflows_detected": int(self._orphan_workflows_detected),
            "orphans_cleaned": cleaned,
            "stale_events_rejected": int(self._stale_events_rejected),
            "replay_events_rejected": int(self._replay_events_rejected),
            "duplicate_events_rejected": int(self._duplicate_events_rejected),
            "lifecycle_transition_rejects": int(self._lifecycle_transition_rejects),
            "websocket_connects": int(self._websocket_connects),
            "websocket_disconnects": int(self._websocket_disconnects),
            "websocket_reconnects": int(self._websocket_reconnects),
            "expired_locks_cleaned": expired_locks_cleaned,
            "cleanup_cycles": int(self._cleanup_cycles),
            "crash_recovery_runs": int(self._crash_recovery_runs),
            "latest_cleanup_timestamp": self._latest_cleanup_timestamp,
            "latest_crash_recovery_timestamp": self._latest_crash_recovery_timestamp,
            "integrity": integrity,
        }
        with self._lock:
            self._last_health_snapshot = snapshot

        logger.info({
            "event": "runtime_governor_cleanup_cycle",
            "orphans_detected": len(orphan_ids),
            "orphans_cleaned": cleaned,
            "expired_locks_cleaned": expired_locks_cleaned,
            "integrity_ok": integrity["ok"],
        })
        logger.info({"event": "production_readiness_audit_completed"})
        return self._normalize_snapshot(snapshot)

    @property
    def active_workflow_count(self) -> int:
        with self._lock:
            return len(self._active_workflows)

    def _run_crash_recovery_once(self) -> None:
        logger.info({"event": "runtime_governor_crash_recovery_start"})
        with self._lock:
            self._crash_recovery_runs += 1
            self._latest_crash_recovery_timestamp = _utcnow().isoformat()
        try:
            recovery = self.cleanup_orphans_and_stale()
            logger.info({
                "event": "runtime_governor_crash_recovery_complete",
                "recovery": recovery,
            })
        except Exception as exc:
            logger.error({
                "event": "runtime_governor_crash_recovery_failed",
                "error": str(exc),
            })

    def _normalize_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        normalized = _json_safe(snapshot)
        normalized["timestamp"] = _as_iso_timestamp(normalized.get("timestamp"))
        normalized["active_workflows"] = max(0, int(normalized.get("active_workflows", 0) or 0))
        normalized["completed_workflows"] = max(0, int(normalized.get("completed_workflows", 0) or 0))
        normalized["orphan_workflows"] = max(0, int(normalized.get("orphan_workflows", 0) or 0))
        normalized["orphan_workflows_detected"] = max(0, int(normalized.get("orphan_workflows_detected", 0) or 0))
        normalized["stale_events_rejected"] = max(0, int(normalized.get("stale_events_rejected", 0) or 0))
        normalized["replay_events_rejected"] = max(0, int(normalized.get("replay_events_rejected", 0) or 0))
        normalized["duplicate_events_rejected"] = max(0, int(normalized.get("duplicate_events_rejected", 0) or 0))
        normalized["lifecycle_transition_rejects"] = max(0, int(normalized.get("lifecycle_transition_rejects", 0) or 0))
        normalized["websocket_connects"] = max(0, int(normalized.get("websocket_connects", 0) or 0))
        normalized["websocket_disconnects"] = max(0, int(normalized.get("websocket_disconnects", 0) or 0))
        normalized["websocket_reconnects"] = max(0, int(normalized.get("websocket_reconnects", 0) or 0))
        normalized["cleanup_cycles"] = max(0, int(normalized.get("cleanup_cycles", 0) or 0))
        normalized["crash_recovery_runs"] = max(0, int(normalized.get("crash_recovery_runs", 0) or 0))
        normalized["latest_cleanup_timestamp"] = (
            _as_iso_timestamp(normalized.get("latest_cleanup_timestamp"))
            if normalized.get("latest_cleanup_timestamp")
            else None
        )
        normalized["latest_crash_recovery_timestamp"] = (
            _as_iso_timestamp(normalized.get("latest_crash_recovery_timestamp"))
            if normalized.get("latest_crash_recovery_timestamp")
            else None
        )
        normalized["orphan_workflows"] = min(normalized["orphan_workflows"], normalized["active_workflows"])
        # Defensive validation that telemetry remains serializable.
        try:
            json.dumps(normalized)
        except Exception:
            normalized = {
                "timestamp": _utcnow().isoformat(),
                "status": "degraded",
                "active_workflows": max(0, self.active_workflow_count),
                "completed_workflows": max(0, int(self._completed_workflows)),
                "orphan_workflows": 0,
                "orphan_workflows_detected": max(0, int(self._orphan_workflows_detected)),
                "stale_events_rejected": max(0, int(self._stale_events_rejected)),
                "replay_events_rejected": max(0, int(self._replay_events_rejected)),
                "duplicate_events_rejected": max(0, int(self._duplicate_events_rejected)),
                "lifecycle_transition_rejects": max(0, int(self._lifecycle_transition_rejects)),
                "websocket_connects": max(0, int(self._websocket_connects)),
                "websocket_disconnects": max(0, int(self._websocket_disconnects)),
                "websocket_reconnects": max(0, int(self._websocket_reconnects)),
                "cleanup_cycles": max(0, int(self._cleanup_cycles)),
                "crash_recovery_runs": max(0, int(self._crash_recovery_runs)),
                "latest_cleanup_timestamp": self._latest_cleanup_timestamp,
                "latest_crash_recovery_timestamp": self._latest_crash_recovery_timestamp,
                "integrity": {"ok": False, "issues": [{"type": "telemetry_serialization_failure"}]},
            }
        return normalized

    def _increment_completed_workflows(self, amount: int) -> None:
        """Monotonic counter; protects against accidental decrements."""
        self._completed_workflows = max(self._completed_workflows, self._completed_workflows + max(0, int(amount)))

    def _cleanup_scheduler_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.cleanup_orphans_and_stale()
            except Exception as exc:
                # Failure isolation boundary: cleanup thread errors do not break dispatch runtime.
                logger.error({
                    "event": "runtime_governor_scheduler_error",
                    "error": str(exc),
                })
            self._stop_event.wait(self._cleanup_interval_seconds)


_runtime_governor: Optional[RuntimeGovernorService] = None
_runtime_governor_lock = threading.Lock()


def initialize_runtime_governor(
    db_session_factory: Callable[[], Session],
    cleanup_interval_seconds: int = 60,
    stale_after_seconds: int = 300,
) -> RuntimeGovernorService:
    global _runtime_governor
    with _runtime_governor_lock:
        if _runtime_governor is None:
            _runtime_governor = RuntimeGovernorService(
                db_session_factory=db_session_factory,
                cleanup_interval_seconds=cleanup_interval_seconds,
                stale_after_seconds=stale_after_seconds,
            )
        _runtime_governor.start()
        return _runtime_governor


def get_runtime_governor() -> RuntimeGovernorService:
    global _runtime_governor
    if _runtime_governor is None:
        raise RuntimeError("RuntimeGovernorService is not initialized")
    return _runtime_governor


def shutdown_runtime_governor() -> None:
    global _runtime_governor
    with _runtime_governor_lock:
        if _runtime_governor is not None:
            _runtime_governor.shutdown()
