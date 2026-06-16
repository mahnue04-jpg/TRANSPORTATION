from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

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


def test_phase41_distributed_ownership_and_routing_contract() -> None:
    governor = _governor()
    governor.register_runtime_worker(
        worker_id="worker-41-a",
        organization_id="org-41",
        runtime_name="runtime-a",
        capacity=2,
        domain="dispatch",
        pressure_score=0.2,
    )
    governor.register_workflow("wf-41-route", "ride-41", "org-41", "queued")
    governor.register_execution_chain(
        chain_id="chain:wf-41-route",
        workflow_id="wf-41-route",
        organization_id="org-41",
        initial_state="queued",
        priority_class="critical",
        execution_domain="dispatch",
    )

    routed = governor.route_workflow_task(
        chain_id="chain:wf-41-route",
        organization_id="org-41",
        workflow_id="wf-41-route",
        task_id="task-41-route",
        priority_class="critical",
        execution_domain="dispatch",
        payload={"ride_id": "ride-41"},
    )

    assert routed["ok"] is True
    assert routed["worker_id"] == "worker-41-a"

    diagnostics = governor.get_distributed_governance_diagnostics("org-41")
    assert diagnostics["active_runtimes"] == 1
    assert diagnostics["distributed_queue_depth"] == 0
    assert diagnostics["workflow_ownership_map"]
    assert diagnostics["workload_pressure"]["priority_distribution"].get("critical", 0) == 0


def test_phase41_stale_lease_failover_and_isolation_violation() -> None:
    governor = _governor()
    governor.register_runtime_worker(
        worker_id="worker-41-b",
        organization_id="org-41",
        runtime_name="runtime-b",
        capacity=1,
        domain="dispatch",
        pressure_score=0.1,
    )
    governor.register_runtime_worker(
        worker_id="worker-41-c",
        organization_id="org-41",
        runtime_name="runtime-c",
        capacity=1,
        domain="provider",
        pressure_score=0.1,
    )
    governor.register_execution_chain(
        chain_id="chain:wf-41-failover",
        workflow_id="wf-41-failover",
        organization_id="org-41",
        initial_state="running",
        priority_class="high",
        execution_domain="dispatch",
    )
    lease = governor.acquire_execution_lease(
        chain_id="chain:wf-41-failover",
        worker_id="worker-41-b",
        organization_id="org-41",
        workflow_id="wf-41-failover",
        priority_class="high",
        execution_domain="dispatch",
    )
    assert lease["ok"] is True

    with governor._lock:  # noqa: SLF001 - deterministic stale simulation for regression coverage
        governor._execution_leases["chain:wf-41-failover"]["last_renewed_at"] = datetime.now(timezone.utc) - timedelta(minutes=10)

    reassigned = governor.reassign_stale_leases(stale_after_seconds=30)
    assert reassigned >= 1

    forbidden = governor.acquire_execution_lease(
        chain_id="chain:wf-41-failover-2",
        worker_id="worker-41-c",
        organization_id="org-41",
        workflow_id="wf-41-failover-2",
        priority_class="high",
        execution_domain="dispatch",
    )
    assert forbidden["ok"] is False
    assert forbidden["reason"] == "domain_isolation_violation"

    diagnostics = governor.get_distributed_governance_diagnostics("org-41")
    assert diagnostics["task_reassignment_count"] >= 1
    assert diagnostics["runtime_failover_count"] >= 1
    assert diagnostics["isolation_violation_count"] >= 1


def test_phase41_distributed_governance_diagnostics_endpoint_contract() -> None:
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id("dispatcher@amicor.local")

    response = client.get(
        f"/api/health-isf/ops/distributed-governance-diagnostics?organization_id={org_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["organization_id"] == org_id
    assert "workflow_ownership_map" in payload
    assert "worker_heartbeat_health" in payload
    assert "workload_pressure" in payload
    assert payload["supervised_isolation"]["ownership_leases"] is True


def test_phase41_websocket_includes_distributed_governance_snapshot() -> None:
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    auth = _login(client, "dispatcher@amicor.local")
    org_id = _org_id("dispatcher@amicor.local")

    try:
        governor = get_runtime_governor()
    except RuntimeError:
        governor = None
    if governor is not None:
        governor.register_runtime_worker(
            worker_id="worker-41-ws",
            organization_id=org_id,
            runtime_name="runtime-ws",
            capacity=1,
            domain="default",
            pressure_score=0.2,
        )
        governor.register_workflow("wf-41-ws", "ride-41-ws", org_id, "queued")
        governor.register_execution_chain(
            chain_id="chain:wf-41-ws",
            workflow_id="wf-41-ws",
            organization_id=org_id,
            initial_state="queued",
            priority_class="normal",
        )

    ws_url = (
        f"/api/health-isf/ws/live/{org_id}/{auth['user_id']}"
        f"?role=dispatcher&token={auth['access_token']}"
    )

    with client.websocket_connect(ws_url) as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "connected"
        assert "workflow_coordination" in connected
        assert "distributed_governance" in connected

        websocket.send_json({"type": "workflow_timeline", "chain_id": "chain:wf-41-ws"})
        timeline = websocket.receive_json()
        assert timeline["type"] == "workflow_timeline"
        assert timeline["chain_id"] == "chain:wf-41-ws"
        assert "timeline" in timeline
