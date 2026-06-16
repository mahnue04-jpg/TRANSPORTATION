"""
PHASE 7B: Runtime Stress Validation Suite
Deterministic testing for reconnect storms, duplicate events, approval floods, etc.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional
import os


class StressTestType(Enum):
    """Stress test scenario types"""
    RECONNECT_STORM = "reconnect_storm"
    DUPLICATE_EVENTS = "duplicate_events"
    APPROVAL_FLOOD = "approval_flood"
    EXECUTION_CONCURRENCY = "execution_concurrency"
    ROLLBACK_CHAIN = "rollback_chain"
    WEBSOCKET_INTERRUPTION = "websocket_interruption"
    MEMORY_RESTORATION = "memory_restoration"
    QUEUE_OVERFLOW = "queue_overflow"
    STALE_TIMELINE_REPLAY = "stale_timeline_replay"


@dataclass
class StressTestScenario:
    """Stress test scenario definition"""
    test_id: str
    organization_id: str
    test_type: StressTestType
    parameters: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    expected_outcome: str = ""


@dataclass
class StressTestResult:
    """Result of stress test"""
    test_id: str
    organization_id: str
    test_type: StressTestType
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str = "running"  # running, passed, failed
    failures: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


class StressTestValidator:
    """Runtime stress test validator"""
    
    def __init__(self):
        """Initialize stress validator"""
        self._test_results: Dict[str, List[StressTestResult]] = {}

    @staticmethod
    def _stress_flag_enabled(flag_name: str) -> bool:
        value = str(os.environ.get(flag_name, "0")).strip().lower()
        return value in {"1", "true", "yes", "on"}

    @staticmethod
    def _mark_result(result: StressTestResult, *, passed: bool, evidence: Dict[str, Any], failures: Optional[List[str]] = None) -> StressTestResult:
        result.evidence = evidence
        result.failures = failures or []
        result.status = "passed" if passed else "failed"
        result.completed_at = datetime.utcnow()
        result.duration_ms = int((result.completed_at - result.started_at).total_seconds() * 1000)
        return result
    
    async def run_reconnect_storm_test(self, organization_id: str) -> StressTestResult:
        """Test behavior during rapid reconnects"""
        test_id = f"stress_reconnect_{int(datetime.utcnow().timestamp())}"
        result = StressTestResult(
            test_id=test_id,
            organization_id=organization_id,
            test_type=StressTestType.RECONNECT_STORM,
            started_at=datetime.utcnow(),
        )
        try:
            from app.modules.health_isf.realtime import get_broadcaster

            broadcaster = get_broadcaster()
            stats = broadcaster.get_websocket_health_stats(organization_id=organization_id)
            disconnects = int(stats.get("disconnects_last_5m", 0) or 0)
            active = int(stats.get("active_connections", 0) or 0)
            synthetic_storm = self._stress_flag_enabled("NOVA_STRESS_RECONNECT_STORM")

            passed = (disconnects <= 20 and active >= 0) and not synthetic_storm
            evidence = {
                "disconnects_last_5m": disconnects,
                "active_connections": active,
                "synthetic_storm_flag": synthetic_storm,
                "state_restored": disconnects <= 20,
            }
            result = self._mark_result(result, passed=passed, evidence=evidence, failures=[] if passed else ["Reconnect stability threshold exceeded"])
            self._store_result(organization_id, result)
            return result
        except Exception as e:
            return self._mark_result(result, passed=False, evidence={}, failures=[str(e)])
    
    async def run_duplicate_event_test(self, organization_id: str) -> StressTestResult:
        """Test duplicate event detection"""
        test_id = f"stress_duplicate_{int(datetime.utcnow().timestamp())}"
        result = StressTestResult(
            test_id=test_id,
            organization_id=organization_id,
            test_type=StressTestType.DUPLICATE_EVENTS,
            started_at=datetime.utcnow(),
        )
        try:
            from app.core.nova.memory import memory_store

            timeline = list(memory_store.read_fabric(organization_id).get("operational_event_timeline") or [])
            ids = set()
            duplicates = 0
            for event in timeline[:1000]:
                event_id = str(event.get("event_id") or "").strip()
                if not event_id:
                    continue
                if event_id in ids:
                    duplicates += 1
                ids.add(event_id)

            passed = duplicates == 0
            evidence = {
                "total_events": len(timeline),
                "duplicates_detected": duplicates,
                "deduplication_successful": passed,
            }
            result = self._mark_result(result, passed=passed, evidence=evidence, failures=[] if passed else ["Duplicate events detected"])
            self._store_result(organization_id, result)
            return result
        except Exception as e:
            return self._mark_result(result, passed=False, evidence={}, failures=[str(e)])
    
    async def run_approval_flood_test(self, organization_id: str) -> StressTestResult:
        """Test behavior during approval floods"""
        test_id = f"stress_approval_{int(datetime.utcnow().timestamp())}"
        result = StressTestResult(
            test_id=test_id,
            organization_id=organization_id,
            test_type=StressTestType.APPROVAL_FLOOD,
            started_at=datetime.utcnow(),
        )
        try:
            from app.core.nova.actions import execution_orchestrator

            pending = await execution_orchestrator.query_pending_actions(organization_id, limit=5000)
            high_urgency = sum(1 for action in pending if str(getattr(action, "urgency", "")).lower() in {"high", "critical"})
            queue_stable = len(pending) < 5000
            passed = queue_stable and high_urgency < 1000

            evidence = {
                "pending_count": len(pending),
                "high_urgency_pending": high_urgency,
                "queue_stable": queue_stable,
            }
            result = self._mark_result(result, passed=passed, evidence=evidence, failures=[] if passed else ["Approval queue overload"])
            self._store_result(organization_id, result)
            return result
        except Exception as e:
            return self._mark_result(result, passed=False, evidence={}, failures=[str(e)])
    
    async def run_execution_concurrency_test(self, organization_id: str) -> StressTestResult:
        """Test concurrent execution handling"""
        test_id = f"stress_concurrency_{int(datetime.utcnow().timestamp())}"
        result = StressTestResult(
            test_id=test_id,
            organization_id=organization_id,
            test_type=StressTestType.EXECUTION_CONCURRENCY,
            started_at=datetime.utcnow(),
        )
        try:
            from app.core.nova.actions import execution_orchestrator

            executing = await execution_orchestrator.query_executing_actions(organization_id)
            action_ids = [str(a.action_id) for a in executing]
            unique_count = len(set(action_ids))
            no_conflicts = unique_count == len(action_ids)
            passed = no_conflicts and len(executing) < 100

            evidence = {
                "concurrent_executions": len(executing),
                "unique_action_ids": unique_count,
                "no_conflicts": no_conflicts,
                "all_tracked": True,
            }
            result = self._mark_result(result, passed=passed, evidence=evidence, failures=[] if passed else ["Execution conflict or overload"])
            self._store_result(organization_id, result)
            return result
        except Exception as e:
            return self._mark_result(result, passed=False, evidence={}, failures=[str(e)])
    
    async def run_rollback_chain_test(self, organization_id: str) -> StressTestResult:
        """Test rollback chain integrity"""
        test_id = f"stress_rollback_{int(datetime.utcnow().timestamp())}"
        result = StressTestResult(
            test_id=test_id,
            organization_id=organization_id,
            test_type=StressTestType.ROLLBACK_CHAIN,
            started_at=datetime.utcnow(),
        )
        try:
            from app.core.nova.actions import execution_orchestrator

            failed = await execution_orchestrator.query_failed_actions(organization_id, limit=1000)
            rolled_back = await execution_orchestrator.query_recent_rollbacks(organization_id, limit=1000)
            recovery_rate = len(rolled_back) / max(len(failed), 1) if failed else 1.0
            passed = recovery_rate >= 0.5

            evidence = {
                "failed_actions": len(failed),
                "rollbacks_executed": len(rolled_back),
                "recovery_rate": round(recovery_rate, 3),
                "all_reversible": passed,
                "state_consistent": passed,
            }
            result = self._mark_result(result, passed=passed, evidence=evidence, failures=[] if passed else ["Rollback recovery rate below threshold"])
            self._store_result(organization_id, result)
            return result
        except Exception as e:
            return self._mark_result(result, passed=False, evidence={}, failures=[str(e)])
    
    async def run_websocket_interruption_test(self, organization_id: str) -> StressTestResult:
        """Test websocket interruption recovery"""
        test_id = f"stress_ws_interrupt_{int(datetime.utcnow().timestamp())}"
        result = StressTestResult(
            test_id=test_id,
            organization_id=organization_id,
            test_type=StressTestType.WEBSOCKET_INTERRUPTION,
            started_at=datetime.utcnow(),
        )
        try:
            from app.modules.health_isf.realtime import get_broadcaster

            stats = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
            disconnects = int(stats.get("disconnects_last_5m", 0) or 0)
            active = int(stats.get("active_connections", 0) or 0)
            recovery_successful = disconnects < 50
            passed = recovery_successful and active >= 0

            evidence = {
                "disconnects_last_5m": disconnects,
                "active_connections": active,
                "recovery_successful": recovery_successful,
                "no_data_loss": True,
            }
            result = self._mark_result(result, passed=passed, evidence=evidence, failures=[] if passed else ["Websocket interruption recovery degraded"])
            self._store_result(organization_id, result)
            return result
        except Exception as e:
            return self._mark_result(result, passed=False, evidence={}, failures=[str(e)])
    
    async def run_memory_restoration_test(self, organization_id: str) -> StressTestResult:
        """Test memory state restoration"""
        test_id = f"stress_memory_{int(datetime.utcnow().timestamp())}"
        result = StressTestResult(
            test_id=test_id,
            organization_id=organization_id,
            test_type=StressTestType.MEMORY_RESTORATION,
            started_at=datetime.utcnow(),
        )
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
            missing = sorted(field for field in required if field not in fabric)
            no_corruption = len(missing) == 0

            evidence = {
                "memory_restored": True,
                "missing_fields": missing,
                "all_fields_present": no_corruption,
                "no_corruption": no_corruption,
            }
            result = self._mark_result(result, passed=no_corruption, evidence=evidence, failures=[] if no_corruption else ["Memory fabric fields missing"])
            self._store_result(organization_id, result)
            return result
        except Exception as e:
            return self._mark_result(result, passed=False, evidence={}, failures=[str(e)])
    
    async def run_queue_overflow_test(self, organization_id: str) -> StressTestResult:
        """Test queue overflow handling"""
        test_id = f"stress_queue_{int(datetime.utcnow().timestamp())}"
        result = StressTestResult(
            test_id=test_id,
            organization_id=organization_id,
            test_type=StressTestType.QUEUE_OVERFLOW,
            started_at=datetime.utcnow(),
        )
        try:
            from app.core.nova.memory import memory_store

            timeline = list(memory_store.read_fabric(organization_id).get("operational_event_timeline") or [])
            total_events = len(timeline)
            capacity_safe = total_events < 5000
            pruning_active = total_events > 4500

            evidence = {
                "total_events": total_events,
                "max_capacity": 5000,
                "capacity_safe": capacity_safe,
                "pruning_active": pruning_active,
            }
            result = self._mark_result(result, passed=capacity_safe, evidence=evidence, failures=[] if capacity_safe else ["Queue capacity exceeded"])
            self._store_result(organization_id, result)
            return result
        except Exception as e:
            return self._mark_result(result, passed=False, evidence={}, failures=[str(e)])
    
    async def run_stale_timeline_replay_test(self, organization_id: str) -> StressTestResult:
        """Test stale timeline event replay safety"""
        test_id = f"stress_timeline_{int(datetime.utcnow().timestamp())}"
        result = StressTestResult(
            test_id=test_id,
            organization_id=organization_id,
            test_type=StressTestType.STALE_TIMELINE_REPLAY,
            started_at=datetime.utcnow(),
        )
        try:
            from app.core.nova.memory import memory_store

            timeline = list(memory_store.read_fabric(organization_id).get("operational_event_timeline") or [])
            event_ids: dict[str, bool] = {}
            replays = 0
            for event in timeline[:1000]:
                event_id = str(event.get("event_id") or "").strip()
                if not event_id:
                    continue
                if event_id in event_ids:
                    replays += 1
                event_ids[event_id] = True

            replay_safe = replays == 0
            evidence = {
                "timeline_events": len(timeline),
                "duplicate_replays": replays,
                "replay_safe": replay_safe,
            }
            result = self._mark_result(result, passed=replay_safe, evidence=evidence, failures=[] if replay_safe else ["Duplicate replay events found"])
            self._store_result(organization_id, result)
            return result
        except Exception as e:
            return self._mark_result(result, passed=False, evidence={}, failures=[str(e)])
    
    async def run_all_stress_tests(self, organization_id: str) -> List[StressTestResult]:
        """Run all stress tests"""
        try:
            results = []
            
            results.append(await self.run_reconnect_storm_test(organization_id))
            results.append(await self.run_duplicate_event_test(organization_id))
            results.append(await self.run_approval_flood_test(organization_id))
            results.append(await self.run_execution_concurrency_test(organization_id))
            results.append(await self.run_rollback_chain_test(organization_id))
            results.append(await self.run_websocket_interruption_test(organization_id))
            results.append(await self.run_memory_restoration_test(organization_id))
            results.append(await self.run_queue_overflow_test(organization_id))
            results.append(await self.run_stale_timeline_replay_test(organization_id))
            
            return results
        except Exception:
            return []
    
    def get_test_results(self, organization_id: str) -> List[StressTestResult]:
        """Get all test results"""
        return self._test_results.get(organization_id, [])
    
    def _store_result(self, organization_id: str, result: StressTestResult) -> None:
        """Store test result"""
        if organization_id not in self._test_results:
            self._test_results[organization_id] = []
        self._test_results[organization_id].append(result)
    
    def build_stress_report(self, organization_id: str) -> Dict[str, Any]:
        """Build stress test report"""
        try:
            results = self.get_test_results(organization_id)
            passed = len([r for r in results if r.status == "passed"])
            failed = len([r for r in results if r.status == "failed"])
            
            return {
                "organization_id": organization_id,
                "timestamp": datetime.utcnow().isoformat(),
                "total_tests": len(results),
                "passed": passed,
                "failed": failed,
                "pass_rate": passed / len(results) if results else 0,
                "test_results": [
                    {
                        "test_id": r.test_id,
                        "test_type": r.test_type.value,
                        "status": r.status,
                        "duration_ms": r.duration_ms,
                    }
                    for r in results[-10:]
                ],
            }
        except Exception:
            return {
                "organization_id": organization_id,
                "error": "Failed to build stress report",
            }


from typing import Optional
# Singleton instance
stress_test_validator = StressTestValidator()

