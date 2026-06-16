from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_runtime_diagnostics_endpoint_returns_live_payload(client: TestClient) -> None:
    auth = _login(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.get("/api/nova/health/runtime/diagnostics", headers=headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert "organization_id" in body
    assert "checks" in body
    assert isinstance(body["checks"], dict)
    assert "websocket" in body["checks"]
    assert "memory" in body["checks"]
    assert "production_safe" in body


def test_live_stress_validation_endpoint_returns_test_results(client: TestClient) -> None:
    auth = _login(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.post("/api/nova/health/validation/stress-test/live", headers=headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert "organization_id" in body
    assert "total_tests" in body
    assert "passed" in body
    assert "failed" in body
    assert "tests" in body
    assert isinstance(body["tests"], list)
