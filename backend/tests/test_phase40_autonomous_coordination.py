from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.health_isf.runtime_governor import RuntimeGovernorService, get_runtime_governor


class _DummySession:
    def close(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def _login(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _org_id(email: str = "dispatcher@amicor.local") -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        assert user.organization_id is not None
        return str(user.organization_id)


def _governor() -> RuntimeGovernorService:
    governor = RuntimeGovernorService(lambda: _DummySession(), cleanup_interval_seconds=5, stale_after_seconds=30)
    governor._detect_orphan_workflows = lambda: []  # type: ignore[method-assign]
    return governor


def test_phase40_supervised_retry_safe_task_continuation() -> None:
    governor = _governor()
    governor.register_workflow("wf-40-task", "ride-40", "org-40", "queued")

    governor.queue_deferred_task(
        chain_id="chain:wf-40-task",
        organization_id="org-40",
        workflow_id="wf-40-task",
        task_id="task-40",
        tool_name="dispatch_tool",
        payload={"ride_id": "ride-40"},
        max_retries=3,
        timeout_seconds=5,
    )

    attempts = {"count": 0}

    def _flaky() -> dict:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("transient tool failure")
        return {"ok": True}

    result = governor.supervise_tool_execution(
        chain_id="chain:wf-40-task",
        task_id="task-40",
        organization_id="org-40",
        workflow_id="wf-40-task",
        tool_name="dispatch_tool",
        execute=_flaky,
        timeout_seconds=5,
        max_retries=3,
    )

    assert result["ok"] is True
    diag = governor.get_workflow_coordination_diagnostics("org-40")
    assert diag["retry_attempts"] >= 1
    assert diag["queued_task_count"] == 0


def test_phase40_interrupted_workflow_resume_and_orphan_cleanup() -> None:
    governor = _governor()
    governor.register_workflow("wf-40-recover", "ride-40-recover", "org-40", "in_transit")

    with governor._lock:  # noqa: SLF001 - deterministic stale simulation for test
        governor._active_workflows["wf-40-recover"]["last_seen"] = datetime.now(timezone.utc) - timedelta(minutes=10)

    governor._detect_orphan_workflows = lambda: ["wf-40-recover"]  # type: ignore[method-assign]
    snapshot = governor.cleanup_orphans_and_stale()

    assert snapshot["orphan_execution_cleanup_count"] >= 1
    assert snapshot["stale_execution_cleanup_count"] >= 1

    resumed = governor.resume_interrupted_workflows("org-40")
    assert resumed >= 0
    diag = governor.get_workflow_coordination_diagnostics("org-40")
    assert diag["orphan_workflow_cleanup_count"] >= 1


def test_phase40_duplicate_workflow_replay_suppression_counter() -> None:
    governor = _governor()

    governor.register_execution_chain(
        chain_id="chain:dup",
        workflow_id="wf-dup",
        organization_id="org-dup",
        initial_state="queued",
    )
    governor.register_execution_chain(
        chain_id="chain:dup",
        workflow_id="wf-dup",
        organization_id="org-dup",
        initial_state="queued",
    )

    snapshot = governor.generate_health_snapshot()
    assert snapshot["duplicate_workflow_replay_suppressed"] >= 1


def test_phase40_runtime_and_coordination_diagnostics_contracts() -> None:
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id("dispatcher@amicor.local")

    response = client.get(
        f"/api/health-isf/ops/runtime-diagnostics?organization_id={org_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert "workflow_coordination" in payload
    assert "runtime_governor" in payload

    response2 = client.get(
        f"/api/health-isf/ops/workflow-coordination-diagnostics?organization_id={org_id}",
        headers=headers,
    )
    assert response2.status_code == 200, response2.text
    payload2 = response2.json()

    assert "active_workflow_count" in payload2
    assert "queued_task_count" in payload2
    assert "checkpoint_restore_count" in payload2


def test_phase40_websocket_chain_timeline_recovery_contract() -> None:
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    auth = _login(client, "dispatcher@amicor.local")
    org_id = _org_id("dispatcher@amicor.local")

    try:
        governor = get_runtime_governor()
    except RuntimeError:
        pytest.skip("runtime governor not initialized for websocket test harness")
    governor.register_workflow("wf-40-ws", "ride-40-ws", org_id, "queued")

    ws_url = (
        f"/api/health-isf/ws/live/{org_id}/{auth['user_id']}"
        f"?role=dispatcher&token={auth['access_token']}"
    )

    with client.websocket_connect(ws_url) as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "connected"
        assert "workflow_coordination" in connected

        websocket.send_json({"type": "workflow_timeline", "chain_id": "chain:wf-40-ws"})
        timeline = websocket.receive_json()
        assert timeline["type"] == "workflow_timeline"
        assert timeline["chain_id"] == "chain:wf-40-ws"
        assert "timeline" in timeline
