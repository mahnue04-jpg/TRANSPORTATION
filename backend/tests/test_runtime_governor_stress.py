import pytest
import asyncio
from backend.runtime.governor import RuntimeGovernorService
from backend.runtime.governor import get_governor_telemetry
from backend.runtime.governor import reset_governor_telemetry
from backend.runtime.governor import simulate_crash_recovery
from backend.runtime.governor import trigger_cleanup_cycle
from backend.runtime.governor import simulate_websocket_event
from backend.runtime.governor import register_workflow, submit_event
import logging

pytestmark = pytest.mark.asyncio

logger = logging.getLogger("runtime_governor_stress")

class TestRuntimeGovernorStress:
    @classmethod
    def setup_class(cls):
        reset_governor_telemetry()
        logger.info("stress_validation_started")

    @classmethod
    def teardown_class(cls):
        logger.info("stress_validation_completed")

    async def test_concurrent_workflow_registration(self):
        N = 50
        tasks = [register_workflow(f"wf_{i}") for i in range(N)]
        await asyncio.gather(*tasks)
        telemetry = get_governor_telemetry()
        assert telemetry['active_workflows'] >= N
        await trigger_cleanup_cycle()
        telemetry2 = get_governor_telemetry()
        assert telemetry2['active_workflows'] <= telemetry['active_workflows']
        assert telemetry2['orphaned_workflows'] == 0

    async def test_replay_protection(self):
        event_id = "evt-dup-1"
        await submit_event(event_id=event_id)
        await submit_event(event_id=event_id)  # duplicate
        telemetry = get_governor_telemetry()
        assert telemetry['replay_events_rejected'] >= 1
        assert telemetry['duplicate_events_rejected'] >= 1
        logger.info("replay_attack_detected")

    async def test_stale_event_rejection(self):
        stale_ts = 1  # monotonic_ts far in the past
        await submit_event(event_id="evt-stale-1", monotonic_ts=stale_ts)
        telemetry = get_governor_telemetry()
        assert telemetry['stale_events_rejected'] >= 1
        logger.info("stale_event_detected")

    async def test_websocket_telemetry(self):
        for _ in range(10):
            await simulate_websocket_event("connect")
            await simulate_websocket_event("disconnect")
            await simulate_websocket_event("reconnect")
        telemetry = get_governor_telemetry()
        assert telemetry['websocket_connects'] >= 10
        assert telemetry['websocket_disconnects'] >= 10
        assert telemetry['websocket_reconnects'] >= 10

    async def test_cleanup_cycles(self):
        await trigger_cleanup_cycle()
        telemetry = get_governor_telemetry()
        assert telemetry['governor_cleanup_cycles'] >= 1
        assert telemetry['expired_locks_cleaned'] >= 0
        assert telemetry['orphaned_workflows'] == 0
        logger.info("orphan_cleanup_executed")

    async def test_crash_recovery(self):
        await simulate_crash_recovery()
        telemetry = get_governor_telemetry()
        assert telemetry['crash_recovery_runs'] >= 1

# Note: The actual implementations of the imported functions must exist in backend.runtime.governor
# and must update the telemetry counters as described in the test assertions.
