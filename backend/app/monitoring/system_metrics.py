"""
backend/app/monitoring/system_metrics.py

Runtime system metrics — all helpers are fail-safe and never raise.

Provides:
- Active request counter (thread-safe, managed by ErrorBoundaryMiddleware)
- Optional psutil-based process memory and CPU metrics
- Uptime human-readable formatting
- Aggregate snapshot helper
"""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger("amicor.monitoring.system_metrics")

# ── Active request counter ────────────────────────────────────────────────────

_request_lock = threading.Lock()
_active_request_count: int = 0


def increment_active_requests() -> None:
    """Increment the active request counter (called by ErrorBoundaryMiddleware on entry)."""
    global _active_request_count
    with _request_lock:
        _active_request_count += 1


def decrement_active_requests() -> None:
    """Decrement the active request counter (called by ErrorBoundaryMiddleware on exit)."""
    global _active_request_count
    with _request_lock:
        _active_request_count = max(0, _active_request_count - 1)


def get_active_request_count() -> int:
    """Return current in-flight request count."""
    with _request_lock:
        return _active_request_count


# ── Process metrics (psutil — optional dependency) ───────────────────────────

def get_process_memory_mb() -> float | None:
    """
    Return process RSS memory in MB.
    Returns None if psutil is unavailable or the call fails.
    """
    try:
        import psutil  # optional

        proc = psutil.Process()
        return round(proc.memory_info().rss / (1024 * 1024), 2)
    except Exception as exc:
        logger.debug("process_memory_mb unavailable: %s", exc)
        return None


def get_process_cpu_percent() -> float | None:
    """
    Return process CPU usage percent (cumulative since last call or process start).
    Returns None if psutil is unavailable or the call fails.
    """
    try:
        import psutil  # optional

        proc = psutil.Process()
        return round(proc.cpu_percent(interval=None), 2)
    except Exception as exc:
        logger.debug("process_cpu_percent unavailable: %s", exc)
        return None


# ── Uptime formatting ─────────────────────────────────────────────────────────

def _seconds_to_human(seconds: float) -> str:
    """Convert seconds to a human-readable string like '2d 3h 14m 7s'."""
    seconds = max(0.0, seconds)
    days = int(seconds // 86400)
    rem = seconds % 86400
    hours = int(rem // 3600)
    rem = rem % 3600
    minutes = int(rem // 60)
    secs = int(rem % 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m {secs}s"
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def get_uptime_human_readable(uptime_seconds: float) -> str:
    """Convert raw uptime seconds to a human-readable string."""
    return _seconds_to_human(uptime_seconds)


# ── Aggregate snapshot ────────────────────────────────────────────────────────

def get_system_metrics_snapshot(uptime_seconds: float = 0.0) -> dict[str, Any]:
    """
    Return an aggregate fail-safe system metrics snapshot.
    All subsystem failures return safe defaults (None or 0).
    """
    return {
        "active_request_count": get_active_request_count(),
        "process_memory_mb": get_process_memory_mb(),
        "process_cpu_percent": get_process_cpu_percent(),
        "uptime_human_readable": get_uptime_human_readable(uptime_seconds),
    }
