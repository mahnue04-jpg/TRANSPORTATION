"""
PHASE 7B: Full Live Health Check Engine
Centralized health validation system for all Nova components.
Validates 14 system areas with automatic periodic checks and recovery recommendations.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
import asyncio
from collections import deque
import hashlib


class HealthCheckType(Enum):
    """14 types of health checks"""
    WEBSOCKET_CONNECTIVITY = "websocket_connectivity"
    API_RESPONSIVENESS = "api_responsiveness"
    MEMORY_PERSISTENCE = "memory_persistence"
    EVENT_QUEUE_HEALTH = "event_queue_health"
    EXECUTION_ENGINE = "execution_engine"
    APPROVAL_PIPELINE = "approval_pipeline"
    ROLLBACK_INTEGRITY = "rollback_integrity"
    TIMELINE_APPEND = "timeline_append"
    RECONNECT_RECOVERY = "reconnect_recovery"
    STALE_EXECUTION = "stale_execution"
    DUPLICATE_DETECTION = "duplicate_detection"
    RUNTIME_LATENCY = "runtime_latency"
    COMMAND_CENTER_HYDRATION = "command_center_hydration"
    METRICS_FRESHNESS = "metrics_freshness"


class CheckStatus(Enum):
    """Check result status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a single health check"""
    check_type: HealthCheckType
    status: CheckStatus
    timestamp: datetime
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    last_check: Optional[datetime] = None
    check_duration_ms: int = 0
    recovery_applicable: bool = False


@dataclass
class RecoveryRecommendation:
    """Recommendation for recovery action"""
    recovery_type: str
    severity: str  # critical, high, medium, low
    description: str
    proposed_action: str
    rollback_safe: bool
    requires_approval: bool
    evidence: List[str] = field(default_factory=list)


@dataclass
class HealthCheckReport:
    """Complete health status report"""
    organization_id: str
    timestamp: datetime
    overall_status: CheckStatus
    total_checks: int
    healthy_count: int
    degraded_count: int
    critical_count: int
    checks: List[HealthCheckResult] = field(default_factory=list)
    recovery_recommendations: List[RecoveryRecommendation] = field(default_factory=list)
    next_check_timestamp: Optional[datetime] = None
    check_history: List["HealthCheckReport"] = field(default_factory=list)


class HealthCheckEngine:
    """Centralized health validation system"""
    
    def __init__(self):
        """Initialize health check engine"""
        self._organization_checks: Dict[str, Dict[HealthCheckType, HealthCheckResult]] = {}
        self._organization_reports: Dict[str, deque] = {}  # Last 100 reports per org
        self._check_intervals: Dict[HealthCheckType, int] = {
            HealthCheckType.WEBSOCKET_CONNECTIVITY: 30,  # every 30s
            HealthCheckType.API_RESPONSIVENESS: 60,
            HealthCheckType.MEMORY_PERSISTENCE: 120,
            HealthCheckType.EVENT_QUEUE_HEALTH: 45,
            HealthCheckType.EXECUTION_ENGINE: 90,
            HealthCheckType.APPROVAL_PIPELINE: 120,
            HealthCheckType.ROLLBACK_INTEGRITY: 180,
            HealthCheckType.TIMELINE_APPEND: 120,
            HealthCheckType.RECONNECT_RECOVERY: 45,
            HealthCheckType.STALE_EXECUTION: 60,
            HealthCheckType.DUPLICATE_DETECTION: 90,
            HealthCheckType.RUNTIME_LATENCY: 30,
            HealthCheckType.COMMAND_CENTER_HYDRATION: 60,
            HealthCheckType.METRICS_FRESHNESS: 90,
        }
        self._last_check_time: Dict[tuple, datetime] = {}
        self._recovery_lock = asyncio.Lock()

    async def _load_action_state(self, organization_id: str) -> dict[str, list[Any]]:
        """Fetch action state via async-safe orchestrator APIs."""
        from app.core.nova.actions import execution_orchestrator

        pending = await execution_orchestrator.query_pending_actions(organization_id, limit=1000)
        executing = await execution_orchestrator.query_executing_actions(organization_id)
        failed = await execution_orchestrator.query_failed_actions(organization_id, limit=1000)
        rolled_back = await execution_orchestrator.query_recent_rollbacks(organization_id, limit=1000)
        return {
            "pending": pending,
            "executing": executing,
            "failed": failed,
            "rolled_back": rolled_back,
        }
    
    async def run_health_check(
        self,
        organization_id: str,
        check_type: Optional[HealthCheckType] = None,
    ) -> HealthCheckResult:
        """
        Run a specific health check or all checks if check_type is None.
        Returns the result of the check.
        """
        try:
            if organization_id not in self._organization_checks:
                self._organization_checks[organization_id] = {}
            
            start_time = datetime.utcnow()
            
            # Delegate to specific check method
            if check_type == HealthCheckType.WEBSOCKET_CONNECTIVITY:
                result = await self._check_websocket_connectivity(organization_id)
            elif check_type == HealthCheckType.API_RESPONSIVENESS:
                result = await self._check_api_responsiveness(organization_id)
            elif check_type == HealthCheckType.MEMORY_PERSISTENCE:
                result = await self._check_memory_persistence(organization_id)
            elif check_type == HealthCheckType.EVENT_QUEUE_HEALTH:
                result = await self._check_event_queue_health(organization_id)
            elif check_type == HealthCheckType.EXECUTION_ENGINE:
                result = await self._check_execution_engine(organization_id)
            elif check_type == HealthCheckType.APPROVAL_PIPELINE:
                result = await self._check_approval_pipeline(organization_id)
            elif check_type == HealthCheckType.ROLLBACK_INTEGRITY:
                result = await self._check_rollback_integrity(organization_id)
            elif check_type == HealthCheckType.TIMELINE_APPEND:
                result = await self._check_timeline_append(organization_id)
            elif check_type == HealthCheckType.RECONNECT_RECOVERY:
                result = await self._check_reconnect_recovery(organization_id)
            elif check_type == HealthCheckType.STALE_EXECUTION:
                result = await self._check_stale_execution(organization_id)
            elif check_type == HealthCheckType.DUPLICATE_DETECTION:
                result = await self._check_duplicate_detection(organization_id)
            elif check_type == HealthCheckType.RUNTIME_LATENCY:
                result = await self._check_runtime_latency(organization_id)
            elif check_type == HealthCheckType.COMMAND_CENTER_HYDRATION:
                result = await self._check_command_center_hydration(organization_id)
            elif check_type == HealthCheckType.METRICS_FRESHNESS:
                result = await self._check_metrics_freshness(organization_id)
            else:
                result = HealthCheckResult(
                    check_type=check_type or HealthCheckType.WEBSOCKET_CONNECTIVITY,
                    status=CheckStatus.UNKNOWN,
                    timestamp=start_time,
                    message="Unknown check type",
                )
            
            # Update duration
            result.check_duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # Store result
            if check_type:
                self._organization_checks[organization_id][check_type] = result
            
            return result
        except Exception as e:
            return HealthCheckResult(
                check_type=check_type or HealthCheckType.WEBSOCKET_CONNECTIVITY,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Check failed: {str(e)}",
            )
    
    async def _check_websocket_connectivity(self, organization_id: str) -> HealthCheckResult:
        """Check websocket connection health"""
        try:
            from app.modules.health_isf.realtime import get_broadcaster

            snapshot = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
            if not snapshot:
                return HealthCheckResult(
                    check_type=HealthCheckType.WEBSOCKET_CONNECTIVITY,
                    status=CheckStatus.UNKNOWN,
                    timestamp=datetime.utcnow(),
                    message="No websocket data available",
                )
            
            # Evaluate status based on reconnect frequency
            status = CheckStatus.HEALTHY
            if snapshot.get("disconnects_last_5m", 0) > 3:
                status = CheckStatus.DEGRADED
            if snapshot.get("disconnects_last_5m", 0) > 10:
                status = CheckStatus.CRITICAL
            
            return HealthCheckResult(
                check_type=HealthCheckType.WEBSOCKET_CONNECTIVITY,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"Websocket {status.value}: {snapshot.get('disconnects_last_5m', 0)} disconnects (5m)",
                details=snapshot,
                recovery_applicable=status != CheckStatus.HEALTHY,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.WEBSOCKET_CONNECTIVITY,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Websocket check failed: {str(e)}",
            )
    
    async def _check_api_responsiveness(self, organization_id: str) -> HealthCheckResult:
        """Check API responsiveness"""
        try:
            from app.modules.health_isf.operations import get_operational_metrics_registry

            registry = get_operational_metrics_registry().snapshot()
            latency_sample = (
                registry.get("samples", {})
                .get("dispatch.assignment.seconds", {})
            )
            avg_latency = float(latency_sample.get("avg", 0.0)) * 1000.0
            status = CheckStatus.HEALTHY
            if avg_latency > 2000:
                status = CheckStatus.DEGRADED
            if avg_latency > 5000:
                status = CheckStatus.CRITICAL
            
            return HealthCheckResult(
                check_type=HealthCheckType.API_RESPONSIVENESS,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"API {status.value}: avg latency {avg_latency}ms",
                details={
                    "avg_latency_ms": round(avg_latency, 2),
                    "latency_sample": latency_sample,
                    "throughput": registry.get("throughput", {}),
                },
                recovery_applicable=False,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.API_RESPONSIVENESS,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"API check failed: {str(e)}",
            )
    
    async def _check_memory_persistence(self, organization_id: str) -> HealthCheckResult:
        """Check memory persistence"""
        try:
            from app.core.nova.memory import memory_store

            fabric = memory_store.read_fabric(organization_id)

            required_fields = [
                "founder_continuity", "operational_history", "workflow_history",
                "execution_timeline", "operational_event_timeline", "pending_actions",
                "recommendation_history"
            ]
            missing = [f for f in required_fields if f not in fabric]

            sample_payload = {
                "execution_timeline": len(list(fabric.get("execution_timeline") or [])),
                "operational_event_timeline": len(list(fabric.get("operational_event_timeline") or [])),
                "pending_actions": len(list(fabric.get("pending_actions") or [])),
            }
            checksum = hashlib.sha256(str(sample_payload).encode("utf-8")).hexdigest()[:16]

            status = CheckStatus.HEALTHY if not missing else CheckStatus.CRITICAL
            
            return HealthCheckResult(
                check_type=HealthCheckType.MEMORY_PERSISTENCE,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"Memory {status.value}: {len(missing)} fields missing" if missing else "Memory healthy",
                details={
                    "missing_fields": missing,
                    "fabric_keys": list(fabric.keys()),
                    "fabric_checksum": checksum,
                    **sample_payload,
                },
                recovery_applicable=len(missing) > 0,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.MEMORY_PERSISTENCE,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Memory check failed: {str(e)}",
            )
    
    async def _check_event_queue_health(self, organization_id: str) -> HealthCheckResult:
        """Check event queue health"""
        try:
            from app.core.nova.memory import memory_store
            from app.modules.health_isf.operations import get_operational_metrics_registry

            fabric = memory_store.read_fabric(organization_id)
            timeline_events = list(fabric.get("operational_event_timeline") or [])
            queue_depth = len(timeline_events)
            registry = get_operational_metrics_registry().snapshot()
            failed_events = int(registry.get("counters", {}).get("dispatch.events.failed", 0) or 0)

            status = CheckStatus.HEALTHY
            if queue_depth > 4000 or failed_events > 20:
                status = CheckStatus.DEGRADED
            if queue_depth > 4900 or failed_events > 100:
                status = CheckStatus.CRITICAL
            
            return HealthCheckResult(
                check_type=HealthCheckType.EVENT_QUEUE_HEALTH,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"Event queue {status.value}: {queue_depth} events",
                details={
                    "event_count": queue_depth,
                    "max_capacity": 5000,
                    "failed_events": failed_events,
                    "throughput": registry.get("throughput", {}),
                },
                recovery_applicable=queue_depth > 4000 or failed_events > 20,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.EVENT_QUEUE_HEALTH,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Event queue check failed: {str(e)}",
            )
    
    async def _check_execution_engine(self, organization_id: str) -> HealthCheckResult:
        """Check execution engine health"""
        try:
            state = await self._load_action_state(organization_id)
            executing = state["executing"]
            
            # Executing actions >5min old are concerning
            now = datetime.utcnow()
            stuck = []
            for action in executing:
                started_at = getattr(action, "executed_at", None)
                if started_at:
                    age = (now - started_at).total_seconds()
                    if age > 300:  # 5 minutes
                        stuck.append(action.action_id)
            
            status = CheckStatus.HEALTHY
            if stuck:
                status = CheckStatus.DEGRADED
            if len(stuck) > 3:
                status = CheckStatus.CRITICAL
            
            return HealthCheckResult(
                check_type=HealthCheckType.EXECUTION_ENGINE,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"Execution engine {status.value}: {len(stuck)} stuck executions",
                details={"stuck_actions": stuck, "executing_count": len(executing)},
                recovery_applicable=len(stuck) > 0,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.EXECUTION_ENGINE,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Execution engine check failed: {str(e)}",
            )
    
    async def _check_approval_pipeline(self, organization_id: str) -> HealthCheckResult:
        """Check approval pipeline health"""
        try:
            state = await self._load_action_state(organization_id)
            pending = state["pending"]
            
            # Many pending approvals is concerning
            status = CheckStatus.HEALTHY
            if len(pending) > 50:
                status = CheckStatus.DEGRADED
            if len(pending) > 100:
                status = CheckStatus.CRITICAL
            
            return HealthCheckResult(
                check_type=HealthCheckType.APPROVAL_PIPELINE,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"Approval pipeline {status.value}: {len(pending)} pending",
                details={"pending_count": len(pending)},
                recovery_applicable=False,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.APPROVAL_PIPELINE,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Approval pipeline check failed: {str(e)}",
            )
    
    async def _check_rollback_integrity(self, organization_id: str) -> HealthCheckResult:
        """Check rollback recovery integrity"""
        try:
            state = await self._load_action_state(organization_id)
            failed = state["failed"]
            rolled_back = state["rolled_back"]

            failed_count = len(failed)
            rolled_back_count = len(rolled_back)
            # No failed actions means no recovery debt and should be treated as healthy.
            if failed_count == 0:
                recovery_rate = 1.0
                status = CheckStatus.HEALTHY
                message = "Rollback integrity healthy: no failed actions"
            else:
                recovery_rate = rolled_back_count / failed_count
                status = CheckStatus.HEALTHY
                if recovery_rate < 0.5:
                    status = CheckStatus.DEGRADED
                if recovery_rate < 0.2:
                    status = CheckStatus.CRITICAL
                message = f"Rollback integrity {status.value}: {recovery_rate:.1%} recovery rate"
            
            return HealthCheckResult(
                check_type=HealthCheckType.ROLLBACK_INTEGRITY,
                status=status,
                timestamp=datetime.utcnow(),
                message=message,
                details={
                    "failed_count": failed_count,
                    "rolled_back_count": rolled_back_count,
                    "recovery_rate": round(recovery_rate, 4),
                },
                recovery_applicable=False,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.ROLLBACK_INTEGRITY,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Rollback check failed: {str(e)}",
            )
    
    async def _check_timeline_append(self, organization_id: str) -> HealthCheckResult:
        """Check timeline append-only integrity"""
        try:
            from app.core.nova.memory import memory_store

            timeline = list(memory_store.read_fabric(organization_id).get("operational_event_timeline") or [])
            recent = timeline[:150]
            seen = set()
            duplicate_count = 0
            for entry in recent:
                event_id = str(entry.get("event_id") or "").strip()
                if not event_id:
                    continue
                if event_id in seen:
                    duplicate_count += 1
                seen.add(event_id)
            status = CheckStatus.HEALTHY if duplicate_count == 0 else CheckStatus.DEGRADED
            
            return HealthCheckResult(
                check_type=HealthCheckType.TIMELINE_APPEND,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"Timeline append {status.value}: {len(timeline)} events",
                details={"event_count": len(timeline), "duplicate_events_recent": duplicate_count},
                recovery_applicable=duplicate_count > 0,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.TIMELINE_APPEND,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Timeline check failed: {str(e)}",
            )
    
    async def _check_reconnect_recovery(self, organization_id: str) -> HealthCheckResult:
        """Check reconnect recovery capability"""
        try:
            from app.modules.health_isf.realtime import get_broadcaster

            snapshot = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
            if not snapshot:
                return HealthCheckResult(
                    check_type=HealthCheckType.RECONNECT_RECOVERY,
                    status=CheckStatus.UNKNOWN,
                    timestamp=datetime.utcnow(),
                    message="No websocket data",
                )
            
            # Check reconnect success rate
            reconnects = int(snapshot.get("active_connections", 0) or 0)
            disconnects = int(snapshot.get("disconnects_last_5m", 0) or 0)
            recovery_rate = reconnects / max(disconnects, 1) if disconnects > 0 else 1.0
            
            status = CheckStatus.HEALTHY if recovery_rate > 0.9 else CheckStatus.DEGRADED
            if recovery_rate < 0.5:
                status = CheckStatus.CRITICAL
            
            return HealthCheckResult(
                check_type=HealthCheckType.RECONNECT_RECOVERY,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"Reconnect recovery {status.value}: {recovery_rate:.1%} success rate",
                details={"reconnects": reconnects, "disconnects": disconnects},
                recovery_applicable=recovery_rate < 0.9,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.RECONNECT_RECOVERY,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Reconnect check failed: {str(e)}",
            )
    
    async def _check_stale_execution(self, organization_id: str) -> HealthCheckResult:
        """Check for stale executions"""
        try:
            state = await self._load_action_state(organization_id)
            executing = state["executing"]
            
            # Find executions >10min old
            now = datetime.utcnow()
            stale = []
            for action in executing:
                started_at = getattr(action, "executed_at", None)
                if started_at:
                    age = (now - started_at).total_seconds()
                    if age > 600:  # 10 minutes
                        stale.append((action.action_id, int(age)))
            
            status = CheckStatus.HEALTHY if not stale else CheckStatus.CRITICAL
            
            return HealthCheckResult(
                check_type=HealthCheckType.STALE_EXECUTION,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"Stale execution check {status.value}: {len(stale)} stale actions",
                details={"stale_actions": stale},
                recovery_applicable=len(stale) > 0,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.STALE_EXECUTION,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Stale execution check failed: {str(e)}",
            )
    
    async def _check_duplicate_detection(self, organization_id: str) -> HealthCheckResult:
        """Check duplicate event detection"""
        try:
            from app.core.nova.memory import memory_store

            timeline = list(memory_store.read_fabric(organization_id).get("operational_event_timeline") or [])
            event_ids = set()
            duplicates = []
            for event in timeline[:500]:
                event_id = str(event.get("event_id") or "").strip()
                if not event_id:
                    continue
                if event_id in event_ids:
                    duplicates.append(event_id)
                event_ids.add(event_id)
            
            status = CheckStatus.HEALTHY if not duplicates else CheckStatus.CRITICAL
            
            return HealthCheckResult(
                check_type=HealthCheckType.DUPLICATE_DETECTION,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"Duplicate detection {status.value}: {len(duplicates)} duplicates found",
                details={"duplicate_count": len(duplicates)},
                recovery_applicable=len(duplicates) > 0,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.DUPLICATE_DETECTION,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Duplicate detection check failed: {str(e)}",
            )
    
    async def _check_runtime_latency(self, organization_id: str) -> HealthCheckResult:
        """Check runtime latency"""
        try:
            from app.modules.health_isf.operations import get_operational_metrics_registry

            registry = get_operational_metrics_registry().snapshot()
            latency_sample = registry.get("samples", {}).get("dispatch.assignment.seconds", {})
            latency = float(latency_sample.get("p95", latency_sample.get("avg", 0.0)) or 0.0) * 1000.0
            status = CheckStatus.HEALTHY
            if latency > 1000:
                status = CheckStatus.DEGRADED
            if latency > 3000:
                status = CheckStatus.CRITICAL
            
            return HealthCheckResult(
                check_type=HealthCheckType.RUNTIME_LATENCY,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"Runtime latency {status.value}: {latency}ms",
                details={"latency_ms": round(latency, 2), "sample": latency_sample},
                recovery_applicable=False,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.RUNTIME_LATENCY,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Latency check failed: {str(e)}",
            )
    
    async def _check_command_center_hydration(self, organization_id: str) -> HealthCheckResult:
        """Check command center hydration"""
        try:
            from app.core.nova.command_center_hydration import command_center_hydration

            snapshot = command_center_hydration.build_full_hydration(organization_id)
            components = snapshot.get("components", {}) if isinstance(snapshot, dict) else {}
            if not components:
                return HealthCheckResult(
                    check_type=HealthCheckType.COMMAND_CENTER_HYDRATION,
                    status=CheckStatus.CRITICAL,
                    timestamp=datetime.utcnow(),
                    message="Command center snapshot missing",
                    recovery_applicable=True,
                )
            
            # Verify key snapshot fields
            required = ["incident_cards", "execution_stream", "approval_inbox", "runtime_counters"]
            missing = [k for k in required if k not in components]
            
            status = CheckStatus.HEALTHY if not missing else CheckStatus.DEGRADED
            
            return HealthCheckResult(
                check_type=HealthCheckType.COMMAND_CENTER_HYDRATION,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"Command center hydration {status.value}" + (f": {len(missing)} fields missing" if missing else ""),
                details={"missing_fields": missing},
                recovery_applicable=len(missing) > 0,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.COMMAND_CENTER_HYDRATION,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Command center check failed: {str(e)}",
            )
    
    async def _check_metrics_freshness(self, organization_id: str) -> HealthCheckResult:
        """Check operational metrics freshness"""
        try:
            from app.core.nova.operational_metrics import operational_metrics
            
            snapshot = operational_metrics.build_snapshot(organization_id)
            if not snapshot:
                return HealthCheckResult(
                    check_type=HealthCheckType.METRICS_FRESHNESS,
                    status=CheckStatus.CRITICAL,
                    timestamp=datetime.utcnow(),
                    message="Metrics snapshot missing",
                    recovery_applicable=True,
                )
            
            # Check if metrics were updated recently (within last 5 minutes)
            if hasattr(snapshot, 'timestamp'):
                age = (datetime.utcnow() - snapshot.timestamp).total_seconds()
                status = CheckStatus.HEALTHY if age < 300 else CheckStatus.DEGRADED
                if age > 600:
                    status = CheckStatus.CRITICAL
            else:
                age = 0
                status = CheckStatus.HEALTHY
            
            return HealthCheckResult(
                check_type=HealthCheckType.METRICS_FRESHNESS,
                status=status,
                timestamp=datetime.utcnow(),
                message=f"Metrics freshness {status.value}: {int(age)}s old",
                details={"age_seconds": int(age)},
                recovery_applicable=age > 600,
            )
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.METRICS_FRESHNESS,
                status=CheckStatus.UNKNOWN,
                timestamp=datetime.utcnow(),
                message=f"Metrics check failed: {str(e)}",
            )
    
    async def run_all_checks(self, organization_id: str) -> HealthCheckReport:
        """Run all health checks and generate report"""
        try:
            checks = []
            
            for check_type in HealthCheckType:
                result = await self.run_health_check(organization_id, check_type)
                checks.append(result)
            
            # Aggregate results
            healthy = sum(1 for c in checks if c.status == CheckStatus.HEALTHY)
            degraded = sum(1 for c in checks if c.status == CheckStatus.DEGRADED)
            critical = sum(1 for c in checks if c.status == CheckStatus.CRITICAL)
            
            # Overall status: critical if any critical, degraded if any degraded, else healthy
            if critical > 0:
                overall = CheckStatus.CRITICAL
            elif degraded > 0:
                overall = CheckStatus.DEGRADED
            else:
                overall = CheckStatus.HEALTHY
            
            # Get recovery recommendations
            recommendations = self._build_recovery_recommendations(checks)
            
            # Build report
            report = HealthCheckReport(
                organization_id=organization_id,
                timestamp=datetime.utcnow(),
                overall_status=overall,
                total_checks=len(checks),
                healthy_count=healthy,
                degraded_count=degraded,
                critical_count=critical,
                checks=checks,
                recovery_recommendations=recommendations,
                next_check_timestamp=datetime.utcnow() + timedelta(minutes=5),
            )
            
            # Store report history
            if organization_id not in self._organization_reports:
                self._organization_reports[organization_id] = deque(maxlen=100)
            self._organization_reports[organization_id].append(report)
            
            return report
        except Exception as e:
            # Graceful degradation
            return HealthCheckReport(
                organization_id=organization_id,
                timestamp=datetime.utcnow(),
                overall_status=CheckStatus.UNKNOWN,
                total_checks=0,
                healthy_count=0,
                degraded_count=0,
                critical_count=0,
            )
    
    def _build_recovery_recommendations(self, checks: List[HealthCheckResult]) -> List[RecoveryRecommendation]:
        """Build recovery recommendations based on check results"""
        recommendations = []
        
        for check in checks:
            if check.status == CheckStatus.CRITICAL:
                if check.check_type == HealthCheckType.WEBSOCKET_CONNECTIVITY:
                    recommendations.append(RecoveryRecommendation(
                        recovery_type="WEBSOCKET_RESTART",
                        severity="critical",
                        description="Websocket connections unstable",
                        proposed_action="Force reconnect all websocket clients",
                        rollback_safe=True,
                        requires_approval=True,
                        evidence=["excessive disconnects"],
                    ))
                elif check.check_type == HealthCheckType.STALE_EXECUTION:
                    recommendations.append(RecoveryRecommendation(
                        recovery_type="TIMEOUT_RECOVERY",
                        severity="critical",
                        description="Stale executions detected",
                        proposed_action="Trigger timeout-based rollback for stale actions",
                        rollback_safe=True,
                        requires_approval=True,
                        evidence=["executions >10min old"],
                    ))
                elif check.check_type == HealthCheckType.MEMORY_PERSISTENCE:
                    recommendations.append(RecoveryRecommendation(
                        recovery_type="MEMORY_REBUILD",
                        severity="critical",
                        description="Memory fabric corrupted",
                        proposed_action="Rebuild memory state from timeline",
                        rollback_safe=True,
                        requires_approval=True,
                        evidence=["missing memory fields"],
                    ))
            
            elif check.status == CheckStatus.DEGRADED:
                if check.check_type == HealthCheckType.WEBSOCKET_CONNECTIVITY:
                    recommendations.append(RecoveryRecommendation(
                        recovery_type="WEBSOCKET_OPTIMIZE",
                        severity="high",
                        description="Websocket performance degraded",
                        proposed_action="Monitor and optimize websocket health",
                        rollback_safe=False,
                        requires_approval=False,
                        evidence=["recent disconnects"],
                    ))
                elif check.check_type == HealthCheckType.EVENT_QUEUE_HEALTH:
                    recommendations.append(RecoveryRecommendation(
                        recovery_type="EVENT_CLEANUP",
                        severity="high",
                        description="Event queue near capacity",
                        proposed_action="Prune old events and archive",
                        rollback_safe=False,
                        requires_approval=False,
                        evidence=["event count >80% capacity"],
                    ))
        
        return recommendations
    
    def get_all_checks(self, organization_id: str) -> Dict[HealthCheckType, HealthCheckResult]:
        """Get all check results for organization"""
        return self._organization_checks.get(organization_id, {})
    
    def get_check_by_type(self, organization_id: str, check_type: HealthCheckType) -> Optional[HealthCheckResult]:
        """Get specific check result"""
        return self._organization_checks.get(organization_id, {}).get(check_type)
    
    def get_recovery_recommendations(self, organization_id: str) -> List[RecoveryRecommendation]:
        """Get recovery recommendations for organization"""
        checks = self._organization_checks.get(organization_id, {}).values()
        return self._build_recovery_recommendations(list(checks))
    
    def build_diagnostic_report(self, organization_id: str) -> Dict[str, Any]:
        """Build complete diagnostic report"""
        try:
            checks = self._organization_checks.get(organization_id, {})
            history = list(self._organization_reports.get(organization_id, []))
            
            return {
                "organization_id": organization_id,
                "timestamp": datetime.utcnow().isoformat(),
                "current_checks": {
                    k.value: {
                        "status": v.status.value,
                        "message": v.message,
                        "duration_ms": v.check_duration_ms,
                    }
                    for k, v in checks.items()
                },
                "recommendations": [
                    {
                        "type": r.recovery_type,
                        "severity": r.severity,
                        "description": r.description,
                        "action": r.proposed_action,
                        "requires_approval": r.requires_approval,
                    }
                    for r in self.get_recovery_recommendations(organization_id)
                ],
                "history_reports": len(history),
                "last_report": history[-1].__dict__ if history else None,
            }
        except Exception:
            return {
                "organization_id": organization_id,
                "timestamp": datetime.utcnow().isoformat(),
                "error": "Failed to build diagnostic report",
            }


# Singleton instance
health_check_engine = HealthCheckEngine()

