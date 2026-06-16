from __future__ import annotations

import json
import os
from typing import Any

from app.monitoring.runtime_metrics import get_runtime_metrics
from app.monitoring.validation_state import get_validation_snapshot


def _phase16_operational_overview() -> dict[str, Any]:
    try:
        from app.db.session import SessionLocal
        from app.modules.health_isf.operational_workflow_orchestration import build_operational_workflow_overview

        db = SessionLocal()
        try:
            payload = build_operational_workflow_overview(db, organization_id=None)
        finally:
            db.close()

        return {
            "status": "available",
            "overview": payload,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "detail": f"phase16_overview_unavailable:{type(exc).__name__}",
            "overview": {},
        }


def _memory_persistence_status() -> dict[str, Any]:
    try:
        from app.core.nova.memory import NovaMemoryStore

        store = NovaMemoryStore()
        memory_path = store.path
        parent_dir = memory_path.parent
        parent_writable = os.access(parent_dir, os.W_OK)

        # Read-only health check: attempt to parse existing content if file exists.
        if memory_path.exists():
            with memory_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                return {
                    "status": "degraded",
                    "detail": "memory_payload_not_object",
                }

        return {
            "status": "healthy" if parent_writable else "degraded",
            "path": str(memory_path),
            "writable": bool(parent_writable),
        }
    except Exception as exc:
        return {
            "status": "degraded",
            "detail": f"memory_check_failed:{type(exc).__name__}",
        }


def _runtime_governor_status() -> dict[str, Any]:
    try:
        from app.modules.health_isf.runtime_governor import get_runtime_governor

        governor = get_runtime_governor()
        telemetry = governor.get_health_snapshot() or {}
        telemetry_status = str(telemetry.get("status") or "healthy").lower()
        return {
            "status": "alive" if telemetry_status in {"healthy", "ok"} else "degraded",
            "telemetry_status": telemetry_status,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "detail": f"runtime_governor_unavailable:{type(exc).__name__}",
        }


def _websocket_status() -> dict[str, Any]:
    try:
        from app.modules.health_isf.realtime import get_broadcaster

        stats = get_broadcaster().get_websocket_health_stats()
        active_connections = int(stats.get("active_connections", 0))
        return {
            "status": "healthy",
            "active_connections": active_connections,
            "dispatcher_connections": int(stats.get("dispatcher_connections", 0)),
            "driver_connections": int(stats.get("driver_connections", 0)),
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "detail": f"websocket_stats_unavailable:{type(exc).__name__}",
        }


def build_system_health_snapshot() -> dict[str, Any]:
    validation = get_validation_snapshot()
    runtime = get_runtime_metrics()
    memory_persistence = _memory_persistence_status()
    runtime_governor = _runtime_governor_status()
    websocket = _websocket_status()
    phase16 = _phase16_operational_overview()

    return {
        "backend_status": validation["backend_status"],
        "tests": validation["tests"],
        "runtime": runtime,
        "memory_persistence": {
            "status": memory_persistence.get("status", "unknown"),
        },
        "runtime_governor": {
            "status": runtime_governor.get("status", "unknown"),
        },
        "diagnostics": {
            "validation": validation.get("validation", {}),
            "memory_persistence": memory_persistence,
            "runtime_governor": runtime_governor,
            "websocket": websocket,
            "phase16_operational_overview": phase16,
        },
        "phase16_operational_overview": phase16,
    }
