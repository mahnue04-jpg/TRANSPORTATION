from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import now, uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFProvider, HealthISFRide
from app.modules.health_isf.realtime_service import OperationalAlertService


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        assert user.organization_id is not None
        return str(user.organization_id)


def _ensure_provider(organization_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if provider:
            return str(provider.id)

        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Ops Cmd Center Provider {uuid4()[:6]}",
            address="500 Ops Command Way",
            phone="212-555-7010",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _create_pending_ride_for_sla(client: TestClient, token: str, provider_id: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "passenger_name": f"SLA Rider {uuid4()[:6]}",
        "passenger_phone": "+1 212-555-7733",
        "pickup_address": "10 SLA Avenue, New York, NY 10001",
        "dropoff_address": "20 SLA Avenue, New York, NY 10002",
        "service_type": "medical_transport",
        "provider_id": provider_id,
        "priority_tag": "high",
    }
    created = client.post("/api/health-isf/rides", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    ride_id = created.json()["id"]

    # Force the ride into an SLA-breach age window for deterministic incident detection.
    with SessionLocal() as db:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
        assert ride is not None
        ride.requested_at = now() - timedelta(minutes=35)
        ride.updated_at = now() - timedelta(minutes=35)
        db.commit()

    return str(ride_id)


def _ensure_open_alert(organization_id: str) -> str:
    with SessionLocal() as db:
        seeded = OperationalAlertService.log_alert(
            db,
            organization_id=organization_id,
            alert_type="sla_breach_monitoring",
            severity="high",
            message="Seeded open alert for escalation sequencing",
            payload={"seeded": True},
            incident_key=f"seeded_open_alert:{uuid4()}",
            target_roles=["dispatcher", "admin"],
            notification_channels=["dispatcher_board"],
            deduplicate_open_incident=False,
        )
        return str(seeded.id)


def test_incident_generation_and_alert_persistence(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    org_id = _org_id_for("admin@amicor.local")
    provider_id = _ensure_provider(org_id)
    _ = _create_pending_ride_for_sla(client, admin["access_token"], provider_id)

    refreshed = client.post(
        "/api/health-isf/ops/command-center/incidents/refresh",
        headers=headers,
        params={"organization_id": org_id},
    )
    assert refreshed.status_code == 200, refreshed.text
    payload = refreshed.json()
    assert int(payload.get("incident_count", 0)) > 0
    assert int(payload.get("persisted_alert_count", 0)) > 0

    history = client.get(
        "/api/health-isf/ops/command-center/alerts/history",
        headers=headers,
        params={"organization_id": org_id, "limit": 300},
    )
    assert history.status_code == 200, history.text
    rows = history.json().get("alerts", [])
    assert any(str(row.get("alert_type")) == "sla_breach_monitoring" for row in rows)


def test_escalation_sequencing(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    org_id = _org_id_for("admin@amicor.local")
    _ensure_open_alert(org_id)

    history = client.get(
        "/api/health-isf/ops/command-center/alerts/history",
        headers=headers,
        params={"organization_id": org_id, "state": "open", "limit": 200},
    )
    assert history.status_code == 200, history.text
    alerts = history.json().get("alerts", [])
    assert len(alerts) > 0
    alert_id = alerts[0]["id"]

    first = client.post(
        f"/api/health-isf/ops/command-center/alerts/{alert_id}/escalate",
        headers=headers,
        params={"organization_id": org_id},
        json="Initial escalation",
    )
    assert first.status_code == 200, first.text
    first_level = int(first.json().get("escalation_level", 0))

    second = client.post(
        f"/api/health-isf/ops/command-center/alerts/{alert_id}/escalate",
        headers=headers,
        params={"organization_id": org_id},
        json="Second escalation",
    )
    assert second.status_code == 200, second.text
    second_level = int(second.json().get("escalation_level", 0))

    assert second_level > first_level >= 1


def test_sla_breach_detection_visible_in_runtime(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    org_id = _org_id_for("admin@amicor.local")

    runtime = client.get(
        "/api/health-isf/ops/command-center/runtime",
        headers=headers,
        params={"organization_id": org_id, "auto_refresh_incidents": True},
    )
    assert runtime.status_code == 200, runtime.text
    payload = runtime.json()

    incidents = payload.get("active_incidents", [])
    assert any(str(item.get("incident_type")) == "sla_breach_monitoring" for item in incidents)
    assert float(payload.get("realtime_sla_risk", {}).get("pickup_sla_compliance_percent", 100.0)) <= 100.0
    summary = payload.get("operational_state_summary") or {}
    assert summary.get("state") in {"operational", "degraded", "fallback", "replay_recovery", "read_only", "unavailable"}
    modules = summary.get("modules") or {}
    assert isinstance(modules, dict)
    assert "orchestration" in modules
    assert "compliance" in modules
    assert str((payload.get("organization_health") or {}).get("normalized_status") or "") in {"operational", "degraded", "fallback", "replay_recovery", "read_only", "unavailable"}


def test_reconnect_alert_recovery_lifecycle(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    org_id = _org_id_for("admin@amicor.local")

    with SessionLocal() as db:
        seeded = OperationalAlertService.log_alert(
            db,
            organization_id=org_id,
            alert_type="websocket_disconnect_degradation_alert",
            severity="high",
            message="Reconnect degradation requires intervention",
            payload={"disconnects_last_5m": 9},
            incident_key=f"reconnect:{uuid4()}",
            target_roles=["dispatcher", "admin"],
            notification_channels=["dispatcher_board"],
            deduplicate_open_incident=False,
        )
        alert_id = seeded.id

    ack = client.post(
        f"/api/health-isf/ops/command-center/alerts/{alert_id}/acknowledge",
        headers=headers,
        params={"organization_id": org_id},
    )
    assert ack.status_code == 200, ack.text
    assert ack.json().get("state") == "acknowledged"

    resolved = client.post(
        f"/api/health-isf/ops/command-center/alerts/{alert_id}/resolve",
        headers=headers,
        params={"organization_id": org_id, "note": "Reconnect stabilized"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json().get("state") == "resolved"


def test_operational_alert_persistence_history(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    org_id = _org_id_for("admin@amicor.local")

    history = client.get(
        "/api/health-isf/ops/command-center/alerts/history",
        headers=headers,
        params={"organization_id": org_id, "limit": 500},
    )
    assert history.status_code == 200, history.text
    payload = history.json()
    assert int(payload.get("count", 0)) >= 1
    first = payload.get("alerts", [])[0]
    assert "state" in first
    assert "occurrence_count" in first
    assert "incident_key" in first


def test_multi_user_command_center_consistency(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")
    org_id = _org_id_for("admin@amicor.local")

    admin_runtime = client.get(
        "/api/health-isf/ops/command-center/runtime",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
        params={"organization_id": org_id},
    )
    dispatcher_runtime = client.get(
        "/api/health-isf/ops/command-center/runtime",
        headers={"Authorization": f"Bearer {dispatcher['access_token']}"},
        params={"organization_id": org_id},
    )

    assert admin_runtime.status_code == 200, admin_runtime.text
    assert dispatcher_runtime.status_code == 200, dispatcher_runtime.text

    a = admin_runtime.json()
    b = dispatcher_runtime.json()

    assert a.get("command_center_consistency_token") == b.get("command_center_consistency_token")
    assert len(a.get("live_ride_board", {}).get("pending_rides", [])) == len(b.get("live_ride_board", {}).get("pending_rides", []))
    assert len(a.get("operational_alerts", [])) == len(b.get("operational_alerts", []))


def test_replay_safe_incident_reconstruction(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    org_id = _org_id_for("admin@amicor.local")

    first_refresh = client.post(
        "/api/health-isf/ops/command-center/incidents/refresh",
        headers=headers,
        params={"organization_id": org_id},
    )
    second_refresh = client.post(
        "/api/health-isf/ops/command-center/incidents/refresh",
        headers=headers,
        params={"organization_id": org_id},
    )
    assert first_refresh.status_code == 200, first_refresh.text
    assert second_refresh.status_code == 200, second_refresh.text

    runtime = client.get(
        "/api/health-isf/ops/command-center/runtime",
        headers=headers,
        params={"organization_id": org_id},
    )
    assert runtime.status_code == 200, runtime.text
    payload = runtime.json()
    assert payload.get("distributed_coordination_hardening", {}).get("replay_safe_event_ordering") is True
    assert payload.get("replay_recovery_status", {}).get("replay_safe") is True

    history = client.get(
        "/api/health-isf/ops/command-center/alerts/history",
        headers=headers,
        params={"organization_id": org_id, "state": "open", "limit": 500},
    )
    assert history.status_code == 200, history.text
    alerts = history.json().get("alerts", [])
    if alerts:
        assert max(int(item.get("occurrence_count", 0)) for item in alerts) >= 1
