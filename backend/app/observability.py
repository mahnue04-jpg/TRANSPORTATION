"""
Observability: structured metrics, request counters, latency histograms.

Uses stdlib only — no Prometheus/OpenTelemetry dependency.
Metrics are exposed via GET /api/admin/metrics (JSON).
"""
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

logger = logging.getLogger("amicor.observability")

_lock = Lock()

# ── Counters ──────────────────────────────────────────────────────────────────
_counters: dict[str, int] = defaultdict(int)

# ── Latency tracking (rolling last-N samples per key) ─────────────────────────
_MAX_SAMPLES = 200
_latencies: dict[str, deque] = defaultdict(lambda: deque(maxlen=_MAX_SAMPLES))

# ── Error tracking (rolling window) ───────────────────────────────────────────
_MAX_ERRORS = 100
_recent_errors: deque = deque(maxlen=_MAX_ERRORS)

# ── Startup time ──────────────────────────────────────────────────────────────
_START_TIME = time.monotonic()
_START_DT = datetime.now(timezone.utc).isoformat()


def increment(key: str, amount: int = 1) -> None:
    """Increment a named counter."""
    with _lock:
        _counters[key] += amount


def record_latency(key: str, latency_ms: float) -> None:
    """Record a latency sample for a named key."""
    with _lock:
        _latencies[key].append(latency_ms)


def record_error(path: str, status_code: int, message: str) -> None:
    """Append to the rolling error log."""
    with _lock:
        _recent_errors.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "path": path,
            "status_code": status_code,
            "message": message[:256],
        })


def get_metrics() -> dict[str, Any]:
    """Return a snapshot of all collected metrics."""
    with _lock:
        uptime_s = int(time.monotonic() - _START_TIME)
        latency_summaries: dict[str, Any] = {}
        for key, samples in _latencies.items():
            if samples:
                sorted_s = sorted(samples)
                n = len(sorted_s)
                latency_summaries[key] = {
                    "count":  n,
                    "avg_ms": round(sum(sorted_s) / n, 1),
                    "p50_ms": round(sorted_s[n // 2], 1),
                    "p95_ms": round(sorted_s[int(n * 0.95)], 1),
                    "p99_ms": round(sorted_s[int(n * 0.99)], 1),
                    "max_ms": round(sorted_s[-1], 1),
                }
        return {
            "uptime_seconds": uptime_s,
            "started_at": _START_DT,
            "counters": dict(_counters),
            "latencies": latency_summaries,
            "recent_errors": list(_recent_errors)[-20:],
        }


def reset_metrics() -> None:
    """Clear all collected metrics (useful for testing)."""
    with _lock:
        _counters.clear()
        _latencies.clear()
        _recent_errors.clear()
