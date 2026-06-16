from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _login() -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@amicor.local", "password": "Amicor123!"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_assistant_events_are_auth_protected_and_readable() -> None:
    unauthenticated = client.get("/api/assistant/events")
    assert unauthenticated.status_code == 401

    headers = _login()
    session_id = "phase37-test-session"
    correlation_id = "corr-phase37-test"

    posted = client.post(
        "/api/assistant/events",
        headers=headers,
        json={
            "eventType": "workflow",
            "eventName": "assistant_execution_submitted",
            "status": "success",
            "sessionId": session_id,
            "route": "/app/ai-assistant",
            "correlationId": correlation_id,
            "payload": {"source": "pytest"},
        },
    )
    assert posted.status_code == 200
    assert posted.json()["status"] == "logged"
    assert posted.json()["event"]["event_name"] == "assistant_execution_submitted"

    events = client.get(
        "/api/assistant/events",
        params={"session_id": session_id, "limit": 5},
        headers=headers,
    )
    assert events.status_code == 200
    body = events.json()
    assert body["count"] >= 1
    assert any(
        item["event_name"] == "assistant_execution_submitted"
        and item["correlation_id"] == correlation_id
        and item["type"] == "workflow"
        for item in body["items"]
    )

    memory = client.get("/api/assistant/memory", headers=headers)
    executions = client.get("/api/assistant/executions", headers=headers)
    assert memory.status_code == 200
    assert executions.status_code == 200
