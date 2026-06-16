from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.health_isf.realtime import EventBroadcaster, WebSocketConnection
from app.modules.health_isf.runtime_governor import RuntimeGovernorService


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


def test_phase39_reconnect_replay_continuity_metrics() -> None:
    async def _run() -> None:
        broadcaster = EventBroadcaster()
        org_id = "org-phase39"

        first = WebSocketConnection("conn-1", "user-1", "dispatcher")
        first.subscribe("dispatcher_board")
        await broadcaster.register_connection(first, org_id)

        await broadcaster.broadcast_event(
            event_type="ride_created",
            payload={"event_id": "evt-1", "ride_id": "ride-1"},
            organization_id=org_id,
            subscription_types=["dispatcher_board"],
        )
        await broadcaster.broadcast_event(
            event_type="ride_updated",
            payload={"event_id": "evt-2", "ride_id": "ride-1"},
            organization_id=org_id,
            subscription_types=["dispatcher_board"],
        )

        await broadcaster.unregister_connection("conn-1")

        second = WebSocketConnection("conn-2", "user-1", "dispatcher")
        second.subscribe("dispatcher_board")
        await broadcaster.register_connection(second, org_id)

        replay = broadcaster.get_replay_events(org_id, since_sequence=0, limit=200)
        assert len(replay) == 2
        assert replay[0]["sequence"] < replay[1]["sequence"]

        out_of_order = broadcaster.get_replay_events(org_id, since_sequence=9999, limit=200)
        assert out_of_order == []

        stats = broadcaster.get_websocket_health_stats(org_id)
        assert stats["reconnects_last_5m"] >= 1
        assert stats["replay_requests_total"] >= 2
        assert stats["replay_out_of_order_requests"] >= 1

    asyncio.run(_run())


def test_phase39_duplicate_replay_suppression() -> None:
    async def _run() -> None:
        broadcaster = EventBroadcaster()
        org_id = "org-phase39-dup"

        conn = WebSocketConnection("conn-dup", "user-dup", "dispatcher")
        conn.subscribe("dispatcher_board")
        await broadcaster.register_connection(conn, org_id)

        await broadcaster.broadcast_event(
            event_type="ride_updated",
            payload={"event_id": "dup-event", "ride_id": "ride-dup"},
            organization_id=org_id,
            subscription_types=["dispatcher_board"],
        )
        await broadcaster.broadcast_event(
            event_type="ride_updated",
            payload={"event_id": "dup-event", "ride_id": "ride-dup"},
            organization_id=org_id,
            subscription_types=["dispatcher_board"],
        )

        replay = broadcaster.get_replay_events(org_id, since_sequence=0, limit=200)
        assert len(replay) == 1

        stats = broadcaster.get_websocket_health_stats(org_id)
        assert stats["replay_duplicate_drop_count"] >= 1

    asyncio.run(_run())


def test_phase39_runtime_governor_cleanup_metrics(monkeypatch) -> None:
    governor = RuntimeGovernorService(lambda: _DummySession(), cleanup_interval_seconds=5, stale_after_seconds=30)

    monkeypatch.setattr(
        "app.modules.health_isf.runtime_governor.ConcurrentAssignmentService.cleanup_expired_locks",
        lambda _db: 0,
    )

    governor.register_workflow("wf-1", "ride-1", "org-governor", "queued")
    with governor._lock:  # noqa: SLF001 - test-only access for deterministic stale simulation
        governor._active_workflows["wf-1"]["last_seen"] = datetime.now(timezone.utc) - timedelta(minutes=10)

    monkeypatch.setattr(governor, "_detect_orphan_workflows", lambda: ["wf-1"])

    snapshot = governor.cleanup_orphans_and_stale()
    assert snapshot["orphan_execution_cleanup_count"] >= 1
    assert snapshot["stale_execution_cleanup_count"] >= 1
    assert snapshot["recovery_attempts"] >= 1
    assert snapshot["recovery_successes"] >= 1


def test_phase39_runtime_diagnostics_endpoint_contract() -> None:
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

    assert payload["organization_id"] == org_id
    assert "runtime" in payload
    assert "queue" in payload
    assert "runtime_governor" in payload
    assert "continuity" in payload
    assert "operational_state_summary" in payload

    runtime = payload["runtime"]
    assert "reconnect_count" in runtime
    assert "replay_count" in runtime
    assert "queue_replay_metrics" in runtime
    assert "recovery_attempts" in runtime

    continuity = payload["continuity"]
    assert continuity["degraded_mode_state"] in {"healthy", "degraded"}
    assert isinstance(continuity["degraded_mode_reasons"], list)

    summary = payload["operational_state_summary"]
    assert summary["state"] in {"operational", "degraded", "fallback", "replay_recovery", "read_only", "unavailable"}
    assert isinstance(summary.get("modules"), dict)
    assert "orchestration" in summary["modules"]
    assert "compliance" in summary["modules"]
    assert summary["modules"]["orchestration"]["state"] in {"operational", "degraded", "fallback", "replay_recovery", "read_only", "unavailable"}
    assert summary["modules"]["compliance"]["state"] in {"operational", "degraded", "fallback", "replay_recovery", "read_only", "unavailable"}
