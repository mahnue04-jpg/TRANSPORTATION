"""Growth Agent owner gate: admin/support same-tenant only."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"
os.environ.setdefault("TESTING", "true")

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.main import app

STATUS_PATH = "/api/nova/growth-agent/receptionist/status"


@pytest.fixture()
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert res.status_code == 200, res.text
    token = res.json().get("access_token") or res.json().get("token")
    assert token
    return {"Authorization": f"Bearer {token}"}


def test_anonymous_receptionist_denied(client: TestClient) -> None:
    assert client.get(STATUS_PATH).status_code in {401, 403}


def test_dispatcher_denied(client: TestClient) -> None:
    headers = _login(client, "dispatcher@amicor.local")
    assert client.get(STATUS_PATH, headers=headers).status_code == 403


def test_driver_denied(client: TestClient) -> None:
    headers = _login(client, "driver@amicor.local")
    assert client.get(STATUS_PATH, headers=headers).status_code == 403


def test_staff_denied(client: TestClient) -> None:
    headers = _login(client, "staff@amicor.local")
    assert client.get(STATUS_PATH, headers=headers).status_code == 403


def test_analytics_readonly_denied(client: TestClient) -> None:
    try:
        headers = _login(client, "analytics@amicor.local")
    except AssertionError:
        pytest.skip("analytics@amicor.local not seeded in test environment")
    assert client.get(STATUS_PATH, headers=headers).status_code == 403


def test_foreign_organization_query_denied(client: TestClient) -> None:
    headers = _login(client, "admin@amicor.local")
    foreign_org = "foreign-org-aaaaaaaa-bbbb-cccc-dddd"
    res = client.get(STATUS_PATH, headers=headers, params={"organization_id": foreign_org})
    assert res.status_code == 403


def test_admin_receptionist_status_success(client: TestClient) -> None:
    headers = _login(client, "admin@amicor.local")
    res = client.get(STATUS_PATH, headers=headers)
    assert res.status_code == 200, res.text