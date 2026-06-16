from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.health_isf.operational_event_models import OperationalEventType
from app.modules.health_isf.operational_sync_engine import OperationalSynchronizationEngine


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


def _org_id(email: str = "admin@amicor.local") -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        assert user.organization_id
        return str(user.organization_id)


def _publish_stream_event(org_id: str, event_type: OperationalEventType, role_scope: list[str], correlation_id: str) -> None:
    result = OperationalSynchronizationEngine.publish_event(
        organization_id=org_id,
        event_type=event_type,
        payload={
            "source": "pytest_stream",
            "correlation_id": correlation_id,
            "severity": "medium",
            "advisory_only": True,
            "execution_disabled": True,
        },
        role_scope=role_scope,
        source_nonce=f"pytest:{event_type.value}:{correlation_id}:{'-'.join(role_scope)}",
    )
    assert result["accepted"] is True


def test_ops_stream_event_contract_shape(client: TestClient) -> None:
    token = _login(client, "admin@amicor.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    org_id = _org_id()

    _publish_stream_event(org_id, OperationalEventType.RIDE_UPDATED, ["rider", "driver", "provider", "admin"], "phase23-contract")

    response = client.get("/api/ops/stream?after_sequence=0&limit=50&role_view=admin", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["append_only"] is True
    assert payload["replay_safe"] is True
    assert payload["governance"]["execution_disabled"] is True
    assert payload["governance"]["advisory_only"] is True
    assert payload["governance"]["mutation_enabled"] is False

    assert isinstance(payload.get("contract_events"), list)
    assert len(payload["contract_events"]) > 0

    event = payload["contract_events"][-1]
    required_keys = {
        "event_id",
        "event_type",
        "role_scope",
        "severity",
        "timestamp",
        "correlation_id",
        "source",
        "advisory_only",
        "replay_safe",
        "append_only",
        "supervision_required",
    }
    assert required_keys.issubset(set(event.keys()))


def test_ops_stream_append_only_ordering(client: TestClient) -> None:
    token = _login(client, "admin@amicor.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    org_id = _org_id()

    _publish_stream_event(org_id, OperationalEventType.WORKFLOW_TRANSITION, ["admin"], "phase23-ordering-a")
    _publish_stream_event(org_id, OperationalEventType.WORKFLOW_TRANSITION, ["admin"], "phase23-ordering-b")

    response = client.get("/api/ops/stream?after_sequence=0&limit=200&role_view=admin", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    sequences = [int(item.get("sequence", 0) or 0) for item in payload.get("contract_events", [])]
    assert sequences == sorted(sequences)
    assert payload["next_cursor"] >= 0
    assert payload["ordering"] == "sequence_ascending"


def test_ops_stream_role_scoped_visibility(client: TestClient) -> None:
    token = _login(client, "admin@amicor.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    org_id = _org_id()

    _publish_stream_event(org_id, OperationalEventType.DRIVER_STATE_CHANGED, ["driver", "admin"], "phase23-driver-scope")
    _publish_stream_event(org_id, OperationalEventType.PROVIDER_STATE_CHANGED, ["provider", "admin"], "phase23-provider-scope")

    driver_response = client.get("/api/ops/stream?after_sequence=0&limit=200&role_view=driver", headers=headers)
    provider_response = client.get("/api/ops/stream?after_sequence=0&limit=200&role_view=provider", headers=headers)
    admin_response = client.get("/api/ops/stream?after_sequence=0&limit=200&role_view=admin", headers=headers)

    assert driver_response.status_code == 200, driver_response.text
    assert provider_response.status_code == 200, provider_response.text
    assert admin_response.status_code == 200, admin_response.text

    driver_payload = driver_response.json()
    provider_payload = provider_response.json()
    admin_payload = admin_response.json()

    for event in driver_payload.get("contract_events", []):
        assert "driver" in event.get("role_scope", [])

    for event in provider_payload.get("contract_events", []):
        assert "provider" in event.get("role_scope", [])

    assert len(admin_payload.get("contract_events", [])) >= len(driver_payload.get("contract_events", []))
    assert len(admin_payload.get("contract_events", [])) >= len(provider_payload.get("contract_events", []))


def test_ops_stream_no_mutation_or_dispatch_paths(client: TestClient) -> None:
    token = _login(client, "admin@amicor.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/ops/stream?after_sequence=0&limit=20&role_view=admin", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    governance = payload.get("governance", {})
    assert governance.get("execution_disabled") is True
    assert governance.get("advisory_only") is True
    assert governance.get("replay_safe") is True
    assert governance.get("append_only") is True
    assert governance.get("supervision_required") is True
    assert governance.get("mutation_enabled") is False
    assert governance.get("dispatch_actions_enabled") is False
    assert governance.get("autonomous_execution") is False


def test_ops_stream_fallback_polling_behavior(client: TestClient) -> None:
    token = _login(client, "admin@amicor.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(
        "/api/ops/stream?after_sequence=0&limit=20&role_view=admin&simulate_stream_unavailable=true",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    stream = payload.get("stream_status", {})
    assert stream.get("connected") is False
    assert stream.get("mode") == "polling_fallback"
    assert stream.get("fallback_polling_active") is True


def test_ops_shell_routes_still_200(client: TestClient) -> None:
    for path in [
        "/dashboard",
        "/rides",
        "/drivers",
        "/providers",
        "/operations",
        "/system-health",
        "/ai-assistant",
    ]:
        response = client.get(path)
        assert response.status_code == 200, f"{path} => {response.status_code}"
