"""Phase 2A: Nova/legacy assistant security boundaries.

Proves JWT identity is required and client-supplied user_id cannot impersonate.
Does not expand Nova into Health ISF mutation or /app/ai-assistant chat.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.database import init_db
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    init_db()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("access_token")
    assert payload.get("user_id")
    return payload


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


UNAUTHENTICATED_ASSISTANT_CALLS = (
    ("POST", "/api/chat", {"user_id": "spoof", "message": "hello"}),
    ("POST", "/api/chat/stream", {"user_id": "spoof", "message": "hello"}),
    ("POST", "/api/reset", {"user_id": "spoof"}),
)


def test_unauthenticated_admin_endpoints_are_rejected(client: TestClient) -> None:
    dashboard = client.get("/api/admin/dashboard")
    metrics = client.get("/api/admin/metrics")
    assert dashboard.status_code == 401, dashboard.text
    assert metrics.status_code == 401, metrics.text


def test_unauthenticated_assistant_endpoints_are_rejected(client: TestClient) -> None:
    for method, path, body in UNAUTHENTICATED_ASSISTANT_CALLS:
        response = client.request(method, path, json=body)
        assert response.status_code == 401, f"{path} -> {response.status_code} {response.text}"

    history = client.get("/api/history/spoof")
    assert history.status_code == 401, history.text

    upload = client.post(
        "/api/upload",
        files={"file": ("note.txt", b"hello from phase 2a", "text/plain")},
    )
    assert upload.status_code == 401, upload.text

    voice_providers = client.get("/api/voice/providers")
    assert voice_providers.status_code == 401, voice_providers.text

    voice_speak = client.post("/api/voice/speak", json={"text": "hello"})
    assert voice_speak.status_code == 401, voice_speak.text


def test_authenticated_users_retain_permitted_assistant_functionality(client: TestClient) -> None:
    auth = _login(client, "rider@amicor.local")
    headers = _headers(auth["access_token"])
    user_id = auth["user_id"]

    with patch("app.main.route_message") as mock_route:
        mock_route.return_value = {
            "response": "phase 2a ok",
            "tool": "openai",
            "sources": [],
            "status": "success",
            "capability": {},
            "meta": {},
        }
        chat = client.post(
            "/api/chat",
            headers=headers,
            json={"user_id": user_id, "message": "hello"},
        )
        assert chat.status_code == 200, chat.text
        body = chat.json()
        assert body.get("ok") is True
        assert body.get("data", {}).get("reply") == "phase 2a ok"
        mock_route.assert_called_once()
        assert mock_route.call_args.kwargs.get("user_id") == user_id

    history = client.get(f"/api/history/{user_id}", headers=headers)
    assert history.status_code == 200, history.text
    assert history.json().get("user_id") == user_id

    reset = client.post("/api/reset", headers=headers, json={"user_id": user_id})
    assert reset.status_code == 200, reset.text
    assert reset.json().get("success") is True

    upload = client.post(
        "/api/upload",
        headers=headers,
        files={"file": ("note.txt", b"hello from phase 2a", "text/plain")},
    )
    assert upload.status_code == 200, upload.text

    voice = client.get("/api/voice/providers", headers=headers)
    assert voice.status_code == 200, voice.text
    assert "available" in voice.json()


def test_client_supplied_user_id_cannot_impersonate_another_user(client: TestClient) -> None:
    rider = _login(client, "rider@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")
    headers = _headers(rider["access_token"])
    foreign_id = dispatcher["user_id"]
    assert foreign_id != rider["user_id"]

    chat = client.post(
        "/api/chat",
        headers=headers,
        json={"user_id": foreign_id, "message": "hello"},
    )
    assert chat.status_code == 403, chat.text

    stream = client.post(
        "/api/chat/stream",
        headers=headers,
        json={"user_id": foreign_id, "message": "hello"},
    )
    assert stream.status_code == 403, stream.text

    history = client.get(f"/api/history/{foreign_id}", headers=headers)
    assert history.status_code == 403, history.text

    reset = client.post("/api/reset", headers=headers, json={"user_id": foreign_id})
    assert reset.status_code == 403, reset.text

    memory = client.get(
        "/api/memory/retrieve",
        headers=headers,
        params={"user_id": foreign_id, "query": "hello"},
    )
    assert memory.status_code == 403, memory.text


def test_authenticated_admin_can_read_admin_endpoints_other_roles_cannot(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    rider = _login(client, "rider@amicor.local")

    admin_headers = _headers(admin["access_token"])
    rider_headers = _headers(rider["access_token"])

    dashboard = client.get("/api/admin/dashboard", headers=admin_headers)
    metrics = client.get("/api/admin/metrics", headers=admin_headers)
    assert dashboard.status_code == 200, dashboard.text
    assert metrics.status_code == 200, metrics.text
    assert "observability" in dashboard.json() or "platform" in dashboard.json()

    denied_dashboard = client.get("/api/admin/dashboard", headers=rider_headers)
    denied_metrics = client.get("/api/admin/metrics", headers=rider_headers)
    assert denied_dashboard.status_code == 403, denied_dashboard.text
    assert denied_metrics.status_code == 403, denied_metrics.text


def test_nova_command_center_rejects_unauthorized_roles(client: TestClient) -> None:
    unauthenticated = client.get("/api/nova/command-center/dashboard/snapshot")
    assert unauthenticated.status_code == 401, unauthenticated.text

    rider = _login(client, "rider@amicor.local")
    driver = _login(client, "driver@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")

    rider_resp = client.get(
        "/api/nova/command-center/dashboard/snapshot",
        headers=_headers(rider["access_token"]),
    )
    driver_resp = client.get(
        "/api/nova/command-center/dashboard/snapshot",
        headers=_headers(driver["access_token"]),
    )
    dispatcher_resp = client.get(
        "/api/nova/command-center/dashboard/snapshot",
        headers=_headers(dispatcher["access_token"]),
    )

    assert rider_resp.status_code == 403, rider_resp.text
    assert driver_resp.status_code == 403, driver_resp.text
    assert dispatcher_resp.status_code == 200, dispatcher_resp.text


def test_legacy_memory_and_workflow_routes_require_jwt_identity(client: TestClient) -> None:
    unauthenticated = client.get("/api/workflows", params={"user_id": "spoof"})
    assert unauthenticated.status_code == 401, unauthenticated.text

    rider = _login(client, "rider@amicor.local")
    headers = _headers(rider["access_token"])
    permitted = client.get("/api/workflows", headers=headers, params={"user_id": rider["user_id"]})
    assert permitted.status_code == 200, permitted.text
    assert permitted.json().get("status") == "ok"
