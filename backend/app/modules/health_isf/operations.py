"""
Operational intelligence and reliability support for Health ISF.

This module adds non-breaking, incremental operational capabilities:
- structured event logging with request correlation
- in-memory operational metrics registry
- health checks (db, websocket, queue, latency, dependencies)
- alert evaluation (stuck rides, unassigned rides, disconnect spikes, failures)
- dashboard payload builders for operational visualization
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app import observability
from app.db.session import check_db_connection
from app.helpers import now
from app import logging_utils
from app.modules.health_isf.models import (
    HealthISFDriver,
    HealthISFRide,
    DispatcherActivityLog,
    RealTimeEvent,
    RideStatus,
    DriverStatus,
)

logger = logging.getLogger("amicor.health_isf.operations")


class OperationalMetricsRegistry:
    """Thread-safe in-memory counters + rolling samples for dispatch operations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=500))
        self._timestamps: dict[str, deque[datetime]] = defaultdict(lambda: deque(maxlen=500))

    def increment(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[key] += amount

    def record_sample(self, key: str, value: float) -> None:
        with self._lock:
            self._samples[key].append(float(value))

    def record_event_ts(self, key: str, event_time: Optional[datetime] = None) -> None:
        with self._lock:
            self._timestamps[key].append(event_time or now())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counter_copy = dict(self._counters)
            sample_summary: dict[str, Any] = {}
            for key, values in self._samples.items():
                if not values:
                    continue
                arr = list(values)
                arr_sorted = sorted(arr)
                n = len(arr_sorted)
                sample_summary[key] = {
                    "count": n,
                    "avg": round(sum(arr_sorted) / n, 3),
                    "p50": round(arr_sorted[n // 2], 3),
                    "p95": round(arr_sorted[min(n - 1, int(n * 0.95))], 3),
                    "max": round(arr_sorted[-1], 3),
                }

            now_dt = now()
            throughput: dict[str, int] = {}
            for key, values in self._timestamps.items():
                throughput[f"{key}_last_1m"] = sum(1 for ts in values if (now_dt - ts).total_seconds() <= 60)
                throughput[f"{key}_last_5m"] = sum(1 for ts in values if (now_dt - ts).total_seconds() <= 300)

            return {
                "counters": counter_copy,
                "samples": sample_summary,
                "throughput": throughput,
            }


_metrics_registry = OperationalMetricsRegistry()


def get_operational_metrics_registry() -> OperationalMetricsRegistry:
    """Return global operational metrics registry."""
    return _metrics_registry


def log_operational_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Emit centralized structured JSON logs enriched with request correlation ID."""
    payload = {
        "event": event,
        "request_id": logging_utils.get_request_id(),
        "timestamp": now().isoformat(),
        **fields,
    }
    # Keep logs single-line JSON for easy indexing/search in production systems.
    logger.log(level, json.dumps(payload, default=str, separators=(",", ":")))


def build_operational_metrics(db: Session, organization_id: Optional[str] = None) -> dict[str, Any]:
    """Build operational metrics required for dispatch reliability visibility."""
    ride_query = db.query(HealthISFRide)
    driver_query = db.query(HealthISFDriver)
    if organization_id:
        ride_query = ride_query.filter(HealthISFRide.organization_id == organization_id)
        driver_query = driver_query.filter(HealthISFDriver.organization_id == organization_id)

    active_rides = ride_query.filter(HealthISFRide.status.in_([RideStatus.ACCEPTED, RideStatus.IN_TRANSIT])).count()
    unassigned_rides = ride_query.filter(
        HealthISFRide.status == RideStatus.PENDING,
        HealthISFRide.driver_id.is_(None),
    ).count()

    completed_rows = ride_query.filter(
        HealthISFRide.completed_at.is_not(None),
        HealthISFRide.accepted_at.is_not(None),
    ).all()

    assignment_times: list[float] = []
    completion_durations: list[float] = []
    pickup_delays: list[float] = []
    for ride in completed_rows:
        if ride.accepted_at and ride.requested_at:
            assignment_times.append((ride.accepted_at - ride.requested_at).total_seconds())
        if ride.completed_at and ride.accepted_at:
            completion_durations.append((ride.completed_at - ride.accepted_at).total_seconds())
        if ride.accepted_at and ride.requested_at:
            pickup_delays.append((ride.accepted_at - ride.requested_at).total_seconds())

    total_drivers = driver_query.count() or 1
    busy_drivers = driver_query.filter(HealthISFDriver.status.in_([
        DriverStatus.ASSIGNED,
        DriverStatus.EN_ROUTE_PICKUP,
        DriverStatus.WAITING_AT_PICKUP,
        DriverStatus.IN_TRANSIT,
        DriverStatus.BUSY,
    ])).count()

    utilization = round((busy_drivers / total_drivers) * 100.0, 2)

    retry_stats = _metrics_registry.snapshot()
    dispatch_throughput = retry_stats.get("throughput", {}).get("dispatch_events_last_1m", 0)
    ws_connections = retry_stats.get("counters", {}).get("websocket.connections.active", 0)
    failed_events = retry_stats.get("counters", {}).get("dispatch.events.failed", 0)

    return {
        "active_rides": active_rides,
        "average_assignment_time_seconds": _avg(assignment_times),
        "pickup_delay_seconds": _avg(pickup_delays),
        "completion_duration_seconds": _avg(completion_durations),
        "driver_utilization_percent": utilization,
        "dispatch_throughput_per_minute": dispatch_throughput,
        "websocket_connection_count": ws_connections,
        "failed_event_count": failed_events,
        "unassigned_rides": unassigned_rides,
        "registry": retry_stats,
    }


def build_health_snapshot(
    db: Session,
    websocket_stats: dict[str, Any],
    queue_stats: dict[str, Any],
    dependency_health: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build health payload with required subsystem checks."""
    db_ok = check_db_connection()
    latency = observability.get_metrics().get("latencies", {}).get("http.requests.latency_ms", {})
    query_optimization = validate_query_optimization(db)

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": {
            "healthy": db_ok,
        },
        "websocket": {
            "healthy": websocket_stats.get("active_connections", 0) >= 0,
            **websocket_stats,
        },
        "event_queue": {
            "healthy": queue_stats.get("dead_letter", 0) < 50,
            **queue_stats,
        },
        "api_latency": {
            "healthy": float(latency.get("p95_ms", 0) or 0) < 2000,
            "latency": latency,
        },
        "query_optimization": query_optimization,
        "dependencies": dependency_health or {"healthy": True, "details": {}},
        "timestamp": now().isoformat(),
    }


def validate_query_optimization(db: Session) -> dict[str, Any]:
    """Validate presence of key indexes needed for operational query performance."""
    inspector = inspect(db.bind)
    required = {
        "health_isf_realtime_events": {"idx_events_org_timestamp", "idx_events_ride_type"},
        "health_isf_dispatcher_activity": {"idx_activity_org_timestamp", "idx_activity_ride"},
        "health_isf_assignment_locks": {"idx_locks_expires_at"},
    }
    missing: dict[str, list[str]] = {}
    for table, expected_indexes in required.items():
        existing = {item.get("name") for item in inspector.get_indexes(table)}
        table_missing = sorted(index_name for index_name in expected_indexes if index_name not in existing)
        if table_missing:
            missing[table] = table_missing

    return {
        "healthy": len(missing) == 0,
        "missing_indexes": missing,
    }


def evaluate_operational_alerts(
    db: Session,
    queue_stats: dict[str, Any],
    websocket_stats: dict[str, Any],
    organization_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return live alerts based on operational thresholds."""
    alerts: list[dict[str, Any]] = []
    ride_query = db.query(HealthISFRide)
    activity_query = db.query(DispatcherActivityLog)
    if organization_id:
        ride_query = ride_query.filter(HealthISFRide.organization_id == organization_id)
        activity_query = activity_query.filter(DispatcherActivityLog.organization_id == organization_id)

    current_time = now()

    stuck_cutoff = current_time - timedelta(minutes=45)
    stuck_rides = ride_query.filter(
        HealthISFRide.status.in_([RideStatus.ACCEPTED, RideStatus.IN_TRANSIT]),
        HealthISFRide.updated_at < stuck_cutoff,
    ).count()
    if stuck_rides > 0:
        alerts.append(_alert("stuck_rides", "high", f"{stuck_rides} rides appear stuck", {"count": stuck_rides}))

    unassigned_cutoff = current_time - timedelta(minutes=20)
    unassigned = ride_query.filter(
        HealthISFRide.status == RideStatus.PENDING,
        HealthISFRide.driver_id.is_(None),
        HealthISFRide.requested_at < unassigned_cutoff,
    ).count()
    if unassigned > 0:
        alerts.append(_alert("unassigned_rides", "medium", f"{unassigned} rides unassigned for >20m", {"count": unassigned}))

    disconnect_spikes = websocket_stats.get("disconnects_last_5m", 0)
    if disconnect_spikes >= 20:
        alerts.append(_alert("websocket_disconnect_spike", "high", "WebSocket disconnect spike detected", {"count": disconnect_spikes}))

    failed_events = queue_stats.get("failed", 0)
    if failed_events > 10:
        alerts.append(_alert("failed_dispatch_events", "high", f"{failed_events} failed dispatch events", {"count": failed_events}))

    inactive_drivers = db.query(HealthISFDriver).filter(
        HealthISFDriver.status == DriverStatus.AVAILABLE,
        HealthISFDriver.updated_at < current_time - timedelta(hours=2),
    )
    if organization_id:
        inactive_drivers = inactive_drivers.filter(HealthISFDriver.organization_id == organization_id)
    inactive_count = inactive_drivers.count()
    if inactive_count > 0:
        alerts.append(_alert("driver_inactivity", "medium", f"{inactive_count} available drivers inactive >2h", {"count": inactive_count}))

    cancellation_cutoff = current_time - timedelta(hours=1)
    cancellation_count = ride_query.filter(
        HealthISFRide.status == RideStatus.CANCELLED,
        HealthISFRide.updated_at >= cancellation_cutoff,
    ).count()
    if cancellation_count >= 10:
        alerts.append(_alert("excessive_cancellations", "high", f"{cancellation_count} cancellations in last hour", {"count": cancellation_count}))

    return alerts


def build_operational_dashboard(
    db: Session,
    organization_id: Optional[str] = None,
    include_queue_details: bool = False,
    include_driver_availability: bool = False,
) -> dict[str, Any]:
    """Build dashboard payload for live operational panel and charts."""
    metrics = build_operational_metrics(db, organization_id=organization_id)
    _ = include_queue_details, include_driver_availability
    now_dt = now()
    ten_min_ago = now_dt - timedelta(minutes=10)

    event_query = db.query(RealTimeEvent).filter(RealTimeEvent.created_at >= ten_min_ago)
    if organization_id:
        event_query = event_query.filter(RealTimeEvent.organization_id == organization_id)
    event_rows = event_query.all()
    throughput_bucket: dict[str, int] = defaultdict(int)
    for row in event_rows:
        minute = row.created_at.replace(second=0, microsecond=0).isoformat()
        throughput_bucket[minute] += 1

    driver_query = db.query(HealthISFDriver).filter(HealthISFDriver.updated_at >= ten_min_ago)
    if organization_id:
        driver_query = driver_query.filter(HealthISFDriver.organization_id == organization_id)
    driver_rows = driver_query.all()
    utilization_bucket: dict[str, int] = defaultdict(int)
    for row in driver_rows:
        minute = row.updated_at.replace(second=0, microsecond=0).isoformat()
        utilization_bucket[minute] += 1

    return {
        "live_metrics_panel": metrics,
        "ride_throughput_chart": [
            {"minute": minute, "value": count}
            for minute, count in sorted(throughput_bucket.items())
        ],
        "driver_utilization_chart": [
            {"minute": minute, "value": count}
            for minute, count in sorted(utilization_bucket.items())
        ],
        "dispatch_latency_tracking": metrics.get("registry", {}).get("samples", {}).get("dispatch.assignment.seconds", {}),
        "operational_error_tracking": {
            "failed_events": metrics.get("failed_event_count", 0),
            "recent_errors": observability.get_metrics().get("recent_errors", []),
        },
        "timestamp": now().isoformat(),
    }


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 3)


def _alert(alert_type: str, severity: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": alert_type,
        "severity": severity,
        "message": message,
        "details": details,
        "timestamp": now().isoformat(),
    }
