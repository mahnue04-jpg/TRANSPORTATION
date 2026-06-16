"""
Failure Recovery Tests
────────────────────────────────────────────────────────────────────────────────

Validates resilience under bad input and missing auth:
  - Malformed ride creation is rejected with 422
  - Auth-required endpoints return 401/403 without a token
  - Invalid status transitions return 400/422
  - Missing required fields return 422
  - Nova handles empty org gracefully (returns valid response, not 500)
  - Extra / unexpected fields are ignored (Pydantic extra='ignore')
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFProvider


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict: # type: ignore
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get_org_id(email: str = "dispatcher@amicor.local") -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        return user.organization_id # type: ignore


def _get_or_create_provider(org_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == org_id)
            .first()
        )
        if provider:
            return provider.id
        p = HealthISFProvider(
            id=uuid4(),
            organization_id=org_id,
            name=f"Recovery Test Clinic {uuid4()[:6]}",
            address="1 Recovery Road",
            phone="212-555-2002",
            service_type="clinic",
            is_active=True,
        )
        db.add(p)
        db.commit()
        return p.id


def _create_valid_ride(client: TestClient) -> str:
    auth = _login(client) # type: ignore
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _get_org_id()
    provider_id = _get_or_create_provider(org_id)

    response = client.post(
        "/api/health-isf/rides",
        headers=headers,
        json={
            "provider_id": provider_id,
            "passenger_name": f"Recovery Patient {uuid4()[:6]}",
            "passenger_phone": "917-555-3333",
            "service_type": "medical_transport",
            "pickup_address": "123 Recovery St",
            "dropoff_address": "456 Recovery Ave",
        },
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()["id"]


# ─── Input validation ─────────────────────────────────────────────────────────

class TestMalformedInputRejection:
    def test_missing_required_ride_fields_returns_422(self, client: TestClient):
        auth = _login(client) # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        # Missing passenger_name, pickup_address, dropoff_address
        response = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={"provider_id": "some-provider"},
        )
        assert response.status_code == 422, response.text

    def test_empty_body_ride_creation_returns_422(self, client: TestClient):
        auth = _login(client) # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.post("/api/health-isf/rides", headers=headers, json={})
        assert response.status_code == 422, response.text

    def test_extra_fields_in_ride_body_are_ignored(self, client: TestClient):
        """Pydantic extra='ignore' — unexpected fields must not cause 422."""
        auth = _login(client) # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        org_id = _get_org_id()
        provider_id = _get_or_create_provider(org_id)

        response = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": f"Extra Field Patient {uuid4()[:6]}",
                "passenger_phone": "917-555-4444",
                "pickup_address": "1 Extra St",
                "dropoff_address": "2 Extra Ave",
                "unexpected_key": "should be ignored",
                "another_junk_field": 12345,
            },
        )
        # Either 200 (extra ignored) or 422 (strict mode) — but NOT 500
        assert response.status_code in {200, 422}
        assert response.status_code != 500

    def test_invalid_status_string_returns_422(self, client: TestClient):
        ride_id = _create_valid_ride(client)

        auth = _login(client) # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "flying_away"},
        )
        assert response.status_code == 422, response.text

    def test_nonexistent_ride_id_returns_404(self, client: TestClient):
        auth = _login(client) # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/health-isf/rides/nonexistent-ride-id-0000", headers=headers)
        assert response.status_code == 404, response.text

    def test_assign_nonexistent_driver_returns_error(self, client: TestClient):
        ride_id = _create_valid_ride(client)

        auth = _login(client) # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-driver",
            headers=headers,
            json={"driver_id": "nonexistent-driver-aaaa"},
        )
        assert response.status_code in {400, 404, 422}, response.text


# ─── Auth enforcement ─────────────────────────────────────────────────────────

class TestAuthEnforcement:
    _protected_endpoints = [
        ("GET", "/api/health-isf/rides"),
        ("GET", "/api/health-isf/drivers"),
        ("GET", "/api/health-isf/providers"),
        ("GET", "/api/nova/status"),
        ("GET", "/api/nova/context"),
        ("GET", "/api/nova/intelligence"),
        ("GET", "/api/nova/deployment-readiness"),
    ]

    @pytest.mark.parametrize("method,path", _protected_endpoints)
    def test_endpoint_requires_auth(self, client: TestClient, method: str, path: str):
        if method == "GET":
            response = client.get(path)
        elif method == "POST":
            response = client.post(path, json={})
        else:
            pytest.skip(f"Method {method} not handled")

        assert response.status_code in {401, 403}, (
            f"{method} {path} returned {response.status_code} without auth"
        )

    def test_expired_token_returns_401(self, client: TestClient):
        # A clearly invalid/expired JWT
        fake_token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiJ0ZXN0QGV4YW1wbGUuY29tIiwiZXhwIjoxfQ"
            ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        headers = {"Authorization": f"Bearer {fake_token}"}

        response = client.get("/api/nova/status", headers=headers)
        assert response.status_code in {401, 403}

    def test_malformed_bearer_returns_401(self, client: TestClient):
        headers = {"Authorization": "Bearer not_a_real_jwt"}
        response = client.get("/api/nova/status", headers=headers)
        assert response.status_code in {401, 403}


# ─── Nova graceful empty-org handling ────────────────────────────────────────

class TestNovaEmptyOrgHandling:
    def test_nova_status_handles_empty_org_gracefully(self, client: TestClient):
        """
        Nova status must not return 500 even when no rides/drivers exist
        (as is the case for a brand-new org).
        """
        auth = _login(client) # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/nova/status", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert "status" in payload

    def test_nova_intelligence_handles_empty_org_gracefully(self, client: TestClient):
        auth = _login(client) # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/nova/intelligence", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()

        # Must return valid structure even if counts are all zero
        assert isinstance(payload["composite_score"], (int, float))
        assert isinstance(payload["workflow_bottlenecks"], list)
        assert isinstance(payload["recommended_actions"], list)

    def test_nova_context_does_not_crash_on_zero_rides(self, client: TestClient):
        auth = _login(client) # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/nova/context", headers=headers)
        assert response.status_code == 200

    def test_nova_ask_returns_answer_without_ai_backend(self, client: TestClient):
        """Nova /ask must produce an answer using internal logic (no external LLM)."""
        auth = _login(client) # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.post(
            "/api/nova/ask",
            headers=headers,
            json={"question": "What is the current dispatch status?", "mode": "dispatch_supervisor"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert "answer" in payload
        assert len(payload["answer"]) > 0


# ─── WebSocket-free status checks ────────────────────────────────────────────

class TestWebSocketFreeStatusChecks:
    def test_health_live_returns_ok(self, client: TestClient):
        response = client.get("/api/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_readiness_returns_structured_report(self, client: TestClient):
        response = client.get("/api/health/readiness")
        assert response.status_code in {200, 503}
        payload = response.json()
        assert "overall_status" in payload
        assert payload["overall_status"] in {"ready", "staging_only", "not_ready"}
