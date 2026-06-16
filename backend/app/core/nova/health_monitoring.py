"""
PHASE 7A: Live Health Monitoring
Runtime health tracking and performance metrics collection.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum
from collections import deque


class HealthStatus(str, Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class HealthMetric:
    """Single health metric value."""
    name: str
    value: float
    unit: str
    timestamp: datetime
    status: HealthStatus = HealthStatus.HEALTHY
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "metadata": self.metadata,
        }


@dataclass
class HealthSnapshot:
    """Complete health status snapshot."""
    organization_id: str
    timestamp: datetime
    overall_status: HealthStatus
    websocket_health: Dict[str, Any] = field(default_factory=dict)
    execution_health: Dict[str, Any] = field(default_factory=dict)
    memory_health: Dict[str, Any] = field(default_factory=dict)
    runtime_health: Dict[str, Any] = field(default_factory=dict)
    metrics: List[HealthMetric] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "organization_id": self.organization_id,
            "timestamp": self.timestamp.isoformat(),
            "overall_status": self.overall_status.value,
            "websocket_health": self.websocket_health,
            "execution_health": self.execution_health,
            "memory_health": self.memory_health,
            "runtime_health": self.runtime_health,
            "metrics": [m.to_dict() for m in self.metrics],
        }


class HealthMonitor:
    """Monitors runtime health and collects metrics."""

    def __init__(self, window_size: int = 300):
        """Initialize health monitor.
        
        Args:
            window_size: Keep last N metric values for averaging
        """
        self._metrics: Dict[str, deque] = {}
        self._window_size = window_size
        self._health_snapshots: Dict[str, List[HealthSnapshot]] = {}
        self._org_health_counters: Dict[str, Dict[str, int]] = {}

    def record_metric(
        self,
        organization_id: str,
        name: str,
        value: float,
        unit: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> HealthMetric:
        """Record a health metric."""
        metric = HealthMetric(
            name=name,
            value=value,
            unit=unit,
            timestamp=datetime.utcnow(),
            metadata=metadata or {},
        )

        # Store in sliding window
        key = f"{organization_id}:{name}"
        if key not in self._metrics:
            self._metrics[key] = deque(maxlen=self._window_size)
        self._metrics[key].append(metric)

        return metric

    def get_metric_history(
        self, organization_id: str, metric_name: str
    ) -> List[HealthMetric]:
        """Get history of metric values."""
        key = f"{organization_id}:{metric_name}"
        if key not in self._metrics:
            return []
        return list(self._metrics[key])

    def get_metric_average(
        self, organization_id: str, metric_name: str
    ) -> Optional[float]:
        """Get average value of metric over window."""
        history = self.get_metric_history(organization_id, metric_name)
        if not history:
            return None
        return sum(m.value for m in history) / len(history)

    def record_websocket_event(
        self,
        organization_id: str,
        event_type: str,  # "connected", "disconnected", "reconnected", "error"
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record websocket event."""
        counter_key = f"{organization_id}:ws_{event_type}"
        org_counters = self._org_health_counters.setdefault(organization_id, {})
        org_counters[counter_key] = org_counters.get(counter_key, 0) + 1

        self.record_metric(
            organization_id,
            f"websocket_{event_type}",
            org_counters[counter_key],
            unit="count",
            metadata=metadata,
        )

    def record_execution_event(
        self,
        organization_id: str,
        execution_status: str,  # "started", "completed", "failed"
        duration_ms: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record execution event."""
        counter_key = f"{organization_id}:exec_{execution_status}"
        org_counters = self._org_health_counters.setdefault(organization_id, {})
        org_counters[counter_key] = org_counters.get(counter_key, 0) + 1

        self.record_metric(
            organization_id,
            f"execution_{execution_status}_count",
            org_counters[counter_key],
            unit="count",
            metadata=metadata or {},
        )

        if duration_ms is not None:
            self.record_metric(
                organization_id,
                "execution_duration_ms",
                duration_ms,
                unit="ms",
                metadata=metadata or {},
            )

    def record_approval_event(
        self,
        organization_id: str,
        result: str,  # "approved", "rejected"
        duration_seconds: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record approval event."""
        counter_key = f"{organization_id}:approval_{result}"
        org_counters = self._org_health_counters.setdefault(organization_id, {})
        org_counters[counter_key] = org_counters.get(counter_key, 0) + 1

        self.record_metric(
            organization_id,
            f"approval_{result}_count",
            org_counters[counter_key],
            unit="count",
            metadata=metadata or {},
        )

        if duration_seconds is not None:
            self.record_metric(
                organization_id,
                "approval_latency_seconds",
                duration_seconds,
                unit="s",
                metadata=metadata or {},
            )

    def build_websocket_health(self, organization_id: str) -> Dict[str, Any]:
        """Build websocket health summary."""
        try:
            from app.modules.health_isf.realtime import get_broadcaster

            snapshot = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
            disconnects_last_5m = int(snapshot.get("disconnects_last_5m", 0) or 0)
            status = HealthStatus.HEALTHY.value
            if disconnects_last_5m > 5:
                status = HealthStatus.DEGRADED.value
            if disconnects_last_5m > 20:
                status = HealthStatus.CRITICAL.value

            return {
                "active_connections": int(snapshot.get("active_connections", 0) or 0),
                "dispatcher_connections": int(snapshot.get("dispatcher_connections", 0) or 0),
                "driver_connections": int(snapshot.get("driver_connections", 0) or 0),
                "disconnects_last_5m": disconnects_last_5m,
                "status": status,
            }
        except Exception:
            disconnects = self.get_metric_history(organization_id, "websocket_disconnected")
            reconnects = self.get_metric_history(organization_id, "websocket_reconnected")
            errors = self.get_metric_history(organization_id, "websocket_error")

            return {
                "total_disconnects": len(disconnects),
                "total_reconnects": len(reconnects),
                "total_errors": len(errors),
                "last_disconnect": disconnects[-1].timestamp.isoformat() if disconnects else None,
                "last_reconnect": reconnects[-1].timestamp.isoformat() if reconnects else None,
                "status": HealthStatus.HEALTHY.value if len(errors) == 0 else HealthStatus.DEGRADED.value,
            }

    def build_execution_health(self, organization_id: str) -> Dict[str, Any]:
        """Build execution health summary."""
        try:
            from app.core.nova.memory import memory_store

            actions = list(memory_store.read_fabric(organization_id).get("pending_actions") or [])
            total_started = len(actions)
            total_completed = sum(1 for a in actions if str(a.get("execution_status") or "").lower() == "completed")
            total_failed = sum(1 for a in actions if str(a.get("execution_status") or "").lower() == "failed")

            durations: list[float] = []
            for a in actions:
                started_at = a.get("executed_at")
                completed_at = a.get("completed_at")
                if not started_at or not completed_at:
                    continue
                try:
                    start_dt = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
                    durations.append((end_dt - start_dt).total_seconds() * 1000.0)
                except Exception:
                    continue
            avg_duration = (sum(durations) / len(durations)) if durations else 0.0
        except Exception:
            started = self.get_metric_history(organization_id, "execution_started_count")
            completed = self.get_metric_history(organization_id, "execution_completed_count")
            failed = self.get_metric_history(organization_id, "execution_failed_count")

            total_started = started[-1].value if started else 0
            total_completed = completed[-1].value if completed else 0
            total_failed = failed[-1].value if failed else 0
            avg_duration = self.get_metric_average(organization_id, "execution_duration_ms") or 0.0

        return {
            "total_started": total_started,
            "total_completed": total_completed,
            "total_failed": total_failed,
            "success_rate": (
                (total_completed / total_started * 100)
                if total_started > 0
                else 0
            ),
            "average_duration_ms": avg_duration,
            "status": HealthStatus.HEALTHY.value if total_failed == 0 else HealthStatus.DEGRADED.value,
        }

    def build_memory_health(self, organization_id: str) -> Dict[str, Any]:
        """Build memory persistence health summary."""
        try:
            from app.core.nova.memory import memory_store

            fabric = memory_store.read_fabric(organization_id)
            required = {
                "founder_continuity",
                "operational_history",
                "workflow_history",
                "execution_timeline",
                "operational_event_timeline",
                "pending_actions",
                "recommendation_history",
            }
            missing = [field for field in required if field not in fabric]
            checkpoint_count = len(list(fabric.get("operational_event_timeline") or []))
            return {
                "status": HealthStatus.HEALTHY.value if not missing else HealthStatus.CRITICAL.value,
                "last_checkpoint": str(fabric.get("updated_at") or datetime.utcnow().isoformat()),
                "checkpoint_count": checkpoint_count,
                "corruption_detected": len(missing) > 0,
                "missing_fields": missing,
            }
        except Exception:
            return {
                "status": HealthStatus.UNKNOWN.value,
                "last_checkpoint": None,
                "checkpoint_count": 0,
                "corruption_detected": True,
            }

    def build_runtime_health(self, organization_id: str) -> Dict[str, Any]:
        """Build overall runtime health summary."""
        try:
            from app.core.nova.memory import memory_store

            fabric = memory_store.read_fabric(organization_id)
            queue_backlog = len(list(fabric.get("operational_event_timeline") or []))
            stale_execution_count = 0
            now_dt = datetime.utcnow()
            for action in list(fabric.get("pending_actions") or []):
                if str(action.get("execution_status") or "").lower() != "executing":
                    continue
                executed_at = action.get("executed_at")
                if not executed_at:
                    continue
                try:
                    started_at = datetime.fromisoformat(str(executed_at).replace("Z", "+00:00"))
                    age_seconds = (now_dt - started_at.replace(tzinfo=None)).total_seconds() if started_at.tzinfo else (now_dt - started_at).total_seconds()
                    if age_seconds > 300:
                        stale_execution_count += 1
                except Exception:
                    continue

            status = HealthStatus.HEALTHY.value
            if stale_execution_count > 0 or queue_backlog > 4500:
                status = HealthStatus.DEGRADED.value
            if stale_execution_count > 3 or queue_backlog >= 5000:
                status = HealthStatus.CRITICAL.value

            return {
                "uptime_seconds": 0,
                "active_processes": 1,
                "queue_backlog": queue_backlog,
                "stale_execution_count": stale_execution_count,
                "status": status,
            }
        except Exception:
            return {
                "uptime_seconds": 0,
                "active_processes": 0,
                "queue_backlog": 0,
                "stale_execution_count": 0,
                "status": HealthStatus.UNKNOWN.value,
            }

    def build_snapshot(self, organization_id: str) -> HealthSnapshot:
        """Build complete health snapshot."""
        ws_health = self.build_websocket_health(organization_id)
        exec_health = self.build_execution_health(organization_id)
        mem_health = self.build_memory_health(organization_id)
        runtime_health = self.build_runtime_health(organization_id)

        # Determine overall status
        statuses = [
            ws_health.get("status"),
            exec_health.get("status"),
            mem_health.get("status"),
            runtime_health.get("status"),
        ]

        if HealthStatus.CRITICAL.value in statuses:
            overall = HealthStatus.CRITICAL
        elif HealthStatus.DEGRADED.value in statuses:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        snapshot = HealthSnapshot(
            organization_id=organization_id,
            timestamp=datetime.utcnow(),
            overall_status=overall,
            websocket_health=ws_health,
            execution_health=exec_health,
            memory_health=mem_health,
            runtime_health=runtime_health,
        )

        # Store snapshot history
        if organization_id not in self._health_snapshots:
            self._health_snapshots[organization_id] = []
        self._health_snapshots[organization_id].append(snapshot)

        # Keep last 1000 snapshots
        if len(self._health_snapshots[organization_id]) > 1000:
            self._health_snapshots[organization_id] = (
                self._health_snapshots[organization_id][-1000:]
            )

        return snapshot

    def get_snapshot_history(
        self, organization_id: str, limit: int = 100
    ) -> List[HealthSnapshot]:
        """Get snapshot history for organization."""
        snapshots = self._health_snapshots.get(organization_id, [])
        return snapshots[-limit:]


# Singleton instance
health_monitor = HealthMonitor()
