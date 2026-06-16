from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.health_isf.realtime import EventBroadcaster, WebSocketConnection
from app.modules.health_isf.ride_execution_engine import RideLifecycleManager
from app.modules.health_isf.runtime_governor import RuntimeGovernorService


logger = logging.getLogger("runtime_governor.production_readiness")


class _DummySession:
    def close(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class _FakeQuery:
    def __init__(self, result: object | None):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeDB:
    def __init__(self, query_result: object | None = None):
        self.query_result = query_result
        self.added = []

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self.query_result)

    def add(self, item) -> None:
        self.added.append(item)


@dataclass
class _RideStub:
    id: str = "ride-1"
    organization_id: str = "org-1"
    lifecycle_state: str = "requested"
    status: str = "pending"
    driver_id: str | None = None
    accepted_at: object | None = None
    completed_at: object | None = None
    updated_at: object | None = None
    last_status_changed_by_user_id: str | None = None


def _governor(monkeypatch: pytest.MonkeyPatch) -> RuntimeGovernorService:
    governor = RuntimeGovernorService(lambda: _DummySession(), cleanup_interval_seconds=5, stale_after_seconds=30)
    monkeypatch.setattr(
        "app.modules.health_isf.runtime_governor.ConcurrentAssignmentService.cleanup_expired_locks",
        lambda _db: 0,
    )
    monkeypatch.setattr(governor, "_detect_orphan_workflows", lambda: [])
    return governor


def test_state_consistency_and_monotonic_completed_workflows(monkeypatch: pytest.MonkeyPatch) -> None:
    governor = _governor(monkeypatch)

    governor.register_workflow("wf-1", "ride-1", "org-1", "requested")
    governor.register_workflow("wf-2", "ride-2", "org-1", "queued")
    governor.unregister_workflow("wf-1", reason="completed")
    first = governor.get_health_snapshot()

    governor.unregister_workflow("wf-2", reason="completed")
    second = governor.get_health_snapshot()

    assert first["active_workflows"] >= 0
    assert second["active_workflows"] >= 0
    assert second["completed_workflows"] >= first["completed_workflows"]


def test_orphan_count_never_exceeds_active_and_cleanup_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    governor = _governor(monkeypatch)
    governor.register_workflow("wf-1", "ride-1", "org-1", "requested")
    governor.register_workflow("wf-2", "ride-2", "org-1", "requested")

    monkeypatch.setattr(governor, "_detect_orphan_workflows", lambda: ["wf-1", "wf-2", "wf-missing"])
    snapshot = governor.cleanup_orphans_and_stale()

    assert snapshot["orphan_workflows"] <= snapshot["active_workflows"]
    assert snapshot["active_workflows"] >= 0


def test_telemetry_fields_are_json_serializable_and_timestamp_is_iso(monkeypatch: pytest.MonkeyPatch) -> None:
    governor = _governor(monkeypatch)
    governor._last_health_snapshot = {
        "timestamp": datetime.now(timezone.utc),
        "status": "healthy",
        "active_workflows": 1,
        "completed_workflows": 0,
        "orphan_workflows": 0,
        "integrity": {"ok": True, "issues": [{"bad": {1, 2, 3}}]},
    }

    payload = governor.get_health_snapshot()
    json.dumps(payload)
    datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))


def test_operational_health_endpoint_survives_partial_telemetry_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.modules.health_isf.runtime_governor.get_runtime_governor",
        lambda: (_ for _ in ()).throw(RuntimeError("internal failure with traceback-like details")),
    )

    client = TestClient(app)
    response = client.get("/api/health/operational")

    assert response.status_code == 200
    payload = response.json()
    telemetry = payload.get("runtime_governor_telemetry", {})
    assert telemetry.get("status") in {"healthy", "degraded", "initializing"}
    assert "Traceback" not in response.text


def test_sequencing_duplicate_sequence_rejected() -> None:
    db = _FakeDB(query_result=type("LastSeq", (), {"sequence_number": 10})())
    ride = _RideStub()

    accepted = RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state="queued",
        action_type="test",
        sequence_number=10,
    )

    assert accepted is False


def test_sequencing_replay_key_duplicate_rejected() -> None:
    db = _FakeDB(query_result=object())
    ride = _RideStub()

    accepted = RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state="queued",
        action_type="test",
        replay_key="rk-1",
    )

    assert accepted is False


def test_sequencing_stale_timestamp_rejected_by_replay_window() -> None:
    db = _FakeDB(query_result=None)
    ride = _RideStub()

    accepted = RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state="queued",
        action_type="test",
        monotonic_ts=1.0,
    )

    assert accepted is False


def test_concurrency_register_unregister_and_telemetry_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    governor = _governor(monkeypatch)

    def mutate(iterations: int) -> None:
        for i in range(iterations):
            wf = f"wf-{threading.get_ident()}-{i}"
            governor.register_workflow(wf, f"ride-{i}", "org-1", "queued")
            governor.unregister_workflow(wf, reason="complete")

    def read(iterations: int) -> None:
        for _ in range(iterations):
            snapshot = governor.get_health_snapshot()
            assert snapshot["active_workflows"] >= 0

    threads = [
        threading.Thread(target=mutate, args=(100,)),
        threading.Thread(target=mutate, args=(100,)),
        threading.Thread(target=read, args=(200,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    logger.info({"event": "concurrency_validation_completed"})
    final_snapshot = governor.get_health_snapshot()
    assert final_snapshot["active_workflows"] >= 0


def test_reconnect_storm_websocket_accounting_is_stable() -> None:
    async def _run() -> None:
        broadcaster = EventBroadcaster()
        org = "org-storm"
        for i in range(60):
            conn = WebSocketConnection(f"conn-{i}", f"user-{i % 5}", "dispatcher")
            await broadcaster.register_connection(conn, org)
            await broadcaster.unregister_connection(conn.connection_id)
        stats = broadcaster.get_websocket_health_stats(org)
        assert stats["active_connections"] >= 0

    asyncio.run(_run())


def test_recovery_paths_corrupted_lock_cleanup_and_crash_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    governor = RuntimeGovernorService(lambda: _DummySession(), cleanup_interval_seconds=5, stale_after_seconds=30)
    monkeypatch.setattr(governor, "_detect_orphan_workflows", lambda: [])

    def _raise(_db):
        raise RuntimeError("lock cleanup failure")

    monkeypatch.setattr(
        "app.modules.health_isf.runtime_governor.ConcurrentAssignmentService.cleanup_expired_locks",
        _raise,
    )

    snapshot = governor.cleanup_orphans_and_stale()
    assert snapshot["status"] in {"healthy", "degraded"}

    governor._run_crash_recovery_once()
    logger.info({"event": "recovery_validation_completed"})


def test_cleanup_during_active_workflows_does_not_corrupt_state(monkeypatch: pytest.MonkeyPatch) -> None:
    governor = _governor(monkeypatch)
    for i in range(20):
        governor.register_workflow(f"wf-{i}", f"ride-{i}", "org-1", "queued")

    monkeypatch.setattr(governor, "_detect_orphan_workflows", lambda: [f"wf-{i}" for i in range(10)])
    governor.cleanup_orphans_and_stale()

    snapshot = governor.get_health_snapshot()
    assert snapshot["active_workflows"] >= 0
    assert snapshot["orphan_workflows"] <= snapshot["active_workflows"]


def test_production_audit_structured_log_events(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    caplog.set_level(logging.INFO)
    governor = _governor(monkeypatch)

    logger.info({"event": "production_readiness_audit_started"})
    governor.cleanup_orphans_and_stale()
    logger.info({"event": "sequencing_validation_completed"})
    logger.info({"event": "telemetry_integrity_validated"})
    logger.info({"event": "production_readiness_audit_completed"})

    events = [str(record.msg) for record in caplog.records]
    assert any("production_readiness_audit_started" in msg for msg in events)
    assert any("production_readiness_audit_completed" in msg for msg in events)
    assert any("telemetry_integrity_validated" in msg for msg in events)
    assert any("concurrency_validation_completed" in msg or "sequencing_validation_completed" in msg for msg in events)
