from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.monitoring.runtime_metrics import get_runtime_metrics
from app.monitoring.runtime_logger import (
    get_recent_supervision_events,
    get_supervision_log_status,
    record_supervision_event,
)
from app.monitoring.validation_state import get_validation_snapshot
from app.monitoring.system_metrics import (
    get_active_request_count,
    get_process_memory_mb,
    get_process_cpu_percent,
    get_uptime_human_readable,
)


def _runtime_governor_snapshot() -> dict[str, Any]:
    try:
        from app.modules.health_isf.runtime_governor import get_runtime_governor

        governor = get_runtime_governor()
        telemetry = governor.get_health_snapshot() or {}
        status = str(telemetry.get("status") or "healthy").lower()
        active_workflows = int(telemetry.get("active_workflows") or 0)
        return {
            "status": "alive" if status in {"healthy", "ok"} else "degraded",
            "telemetry_status": status,
            "active_workflows": active_workflows,
            "raw": telemetry,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "telemetry_status": "unavailable",
            "active_workflows": 0,
            "detail": f"runtime_governor_unavailable:{type(exc).__name__}",
        }


def _websocket_snapshot() -> dict[str, Any]:
    try:
        from app.modules.health_isf.realtime import get_broadcaster

        stats = get_broadcaster().get_websocket_health_stats()
        dispatcher_connections = int(stats.get("dispatcher_connections") or 0)
        return {
            "status": "available",
            "active_connections": int(stats.get("active_connections") or 0),
            "dispatcher_connections": dispatcher_connections,
            "driver_connections": int(stats.get("driver_connections") or 0),
            "dispatcher_operational_status": "active" if dispatcher_connections > 0 else "standby",
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "active_connections": 0,
            "dispatcher_connections": 0,
            "driver_connections": 0,
            "dispatcher_operational_status": "unknown",
            "detail": f"websocket_unavailable:{type(exc).__name__}",
        }


def _memory_persistence_snapshot() -> dict[str, Any]:
    try:
        from app.core.nova.memory import NovaMemoryStore

        store = NovaMemoryStore()
        memory_path = store.path
        can_write = memory_path.parent.exists()
        return {
            "status": "healthy" if can_write else "degraded",
            "path": str(memory_path),
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "detail": f"memory_persistence_unavailable:{type(exc).__name__}",
        }


def _classify_health(
    runtime_governor_status: str,
    memory_persistence_status: str,
    websocket_status: str,
) -> str:
    """
    Classify overall health.

    CRITICAL  — a required subsystem (runtime_governor or memory_persistence) is unavailable.
    DEGRADED  — any subsystem is degraded, or the optional websocket subsystem is unavailable.
    HEALTHY   — all subsystems are available/alive/healthy.
    """
    required_statuses = (runtime_governor_status, memory_persistence_status)
    if any(s == "unavailable" for s in required_statuses):
        return "CRITICAL"
    all_statuses = (runtime_governor_status, memory_persistence_status, websocket_status)
    if any(s in {"degraded", "unavailable"} for s in all_statuses):
        return "DEGRADED"
    return "HEALTHY"


def build_supervision_snapshot() -> dict[str, Any]:
    runtime = get_runtime_metrics()
    validation = get_validation_snapshot()
    runtime_governor = _runtime_governor_snapshot()
    websocket = _websocket_snapshot()
    memory_persistence = _memory_persistence_snapshot()

    backend_status = str(validation.get("backend_status") or "unknown")
    supervision_status = "healthy"
    for status in (
        runtime_governor.get("status"),
        websocket.get("status"),
        memory_persistence.get("status"),
    ):
        if status in {"degraded", "unavailable"}:
            supervision_status = "degraded"
            break

    # Phase 7: health classification based on required vs optional subsystems
    health_classification = _classify_health(
        runtime_governor_status=str(runtime_governor.get("status") or "unknown"),
        memory_persistence_status=str(memory_persistence.get("status") or "unknown"),
        websocket_status=str(websocket.get("status") or "unknown"),
    )

    # Phase 7: process and request metrics (all fail-safe)
    uptime_s: float = float(runtime.get("uptime_seconds") or 0.0)
    active_request_count = get_active_request_count()
    process_memory_mb = get_process_memory_mb()
    process_cpu_percent = get_process_cpu_percent()
    uptime_human_readable = get_uptime_human_readable(uptime_s)

    record_supervision_event(
        subsystem="supervision",
        event="validation_baseline_snapshot",
        details={
            "backend_status": backend_status,
            "tests": validation.get("tests", {}),
        },
    )
    if supervision_status != "healthy":
        record_supervision_event(
            level="WARNING",
            subsystem="supervision",
            event="degraded_subsystem_detected",
            details={
                "runtime_governor": runtime_governor.get("status", "unknown"),
                "websocket": websocket.get("status", "unknown"),
                "memory_persistence": memory_persistence.get("status", "unknown"),
            },
        )

    diagnostics_summary = {
        "active_queue_counts": {
            "runtime_governor_active_workflows": int(runtime_governor.get("active_workflows") or 0),
        },
        "dispatcher_operational_status": websocket.get("dispatcher_operational_status", "unknown"),
        "subsystems": {
            "runtime_governor": runtime_governor.get("status", "unknown"),
            "websocket": websocket.get("status", "unknown"),
            "memory_persistence": memory_persistence.get("status", "unknown"),
        },
        "note": "informational_only_no_automatic_correction",
    }

    recent_events = get_recent_supervision_events(limit=20)
    supervision_log_status = get_supervision_log_status()

    return {
        "backend_status": backend_status,
        "supervision_status": supervision_status,
        "health_classification": health_classification,
        "validation_baseline": {
            "tests": validation.get("tests", {}),
            "last_updated": validation.get("validation", {}).get("last_updated"),
            "source": validation.get("validation", {}).get("source"),
        },
        "runtime_governor": {
            "status": runtime_governor.get("status", "unknown"),
            "telemetry_status": runtime_governor.get("telemetry_status", "unknown"),
        },
        "websocket_status": {
            "status": websocket.get("status", "unknown"),
            "active_connections": websocket.get("active_connections", 0),
            "dispatcher_connections": websocket.get("dispatcher_connections", 0),
            "driver_connections": websocket.get("driver_connections", 0),
        },
        "memory_persistence": {
            "status": memory_persistence.get("status", "unknown"),
        },
        # Phase 7: expanded process + request metrics
        "active_request_count": active_request_count,
        "process_memory_mb": process_memory_mb,
        "process_cpu_percent": process_cpu_percent,
        "uptime_seconds": uptime_s,
        "uptime_human_readable": uptime_human_readable,
        "generated_at": runtime.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "runtime_mode": "monitoring_only",
        "diagnostics_version": "1.2.0",
        "recent_events": recent_events,
        "supervision_log_status": supervision_log_status,
        "diagnostics_summary": diagnostics_summary,
    }
