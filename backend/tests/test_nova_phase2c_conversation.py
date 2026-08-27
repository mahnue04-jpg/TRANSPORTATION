"""Phase 2C: connect authenticated Nova conversation to /app/ai-assistant.

Reuses Phase 2A JWT chat endpoints. Does not migrate /workspace or change Health ISF.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.database import init_db
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")


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


def test_conversation_pane_uses_existing_authenticated_endpoints() -> None:
    pane = OPS_JS.split("function renderNovaConversationPane()", 1)[1].split(
        "function updateNovaConversationStreamDom", 1
    )[0]
    for fragment in [
        "/api/chat/stream",
        "/api/chat",
        "/api/history/",
        "/api/reset",
        "function novaConversationAuthFetch",
        "function novaAuthenticatedUserId",
        "function sendNovaConversationMessage",
        "function consumeNovaChatStream",
        "function loadNovaConversationHistory",
        "function resetNovaConversation",
        'id="nova-conversation-form"',
        "data-nova-conversation-reset",
        "AmiCorSession.authFetch",
    ]:
        assert fragment in OPS_JS, fragment
    assert "novaConversationAuthFetch" in pane or "/api/chat" in pane
    convo_block = OPS_JS.split("function renderNovaConversationPane()", 1)[1].split(
        "function renderAssistant()", 1
    )[0]
    assert 'fetch("/api/ops/workspace/action"' not in convo_block
    assert "<iframe" not in convo_block.lower()
    assert "iframe src" not in convo_block.lower()
    conversation_def = OPS_JS.split('id: "conversation"', 1)[1][:500]
    assert "Live" in conversation_def
    assert "function renderNovaConversationPane()" in OPS_JS.split("function renderAssistant()", 1)[0]
    assert "pane.id === \"conversation\"" in OPS_JS.split("function renderAssistant()", 1)[1][:400]
    health_def = OPS_JS.split('id: "health-isf"', 1)[1][:500]
    assert "Live" in health_def


def test_unauthenticated_conversation_requests_are_rejected(client: TestClient) -> None:
    chat = client.post("/api/chat", json={"user_id": "spoof", "message": "hello"})
    stream = client.post("/api/chat/stream", json={"user_id": "spoof", "message": "hello"})
    history = client.get("/api/history/spoof")
    reset = client.post("/api/reset", json={"user_id": "spoof"})
    assert chat.status_code == 401, chat.text
    assert stream.status_code == 401, stream.text
    assert history.status_code == 401, history.text
    assert reset.status_code == 401, reset.text


def test_authenticated_nova_conversation_and_history_reset_are_identity_scoped(client: TestClient) -> None:
    rider = _login(client, "rider@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")
    headers = _headers(rider["access_token"])
    user_id = rider["user_id"]
    foreign_id = dispatcher["user_id"]
    assert foreign_id != user_id

    with patch("app.main.route_message") as mock_route:
        mock_route.return_value = {
            "response": "phase 2c ok",
            "tool": "openai",
            "sources": [],
            "status": "success",
            "capability": {},
            "meta": {},
        }
        chat = client.post(
            "/api/chat",
            headers=headers,
            json={"user_id": user_id, "message": "hello nova"},
        )
        assert chat.status_code == 200, chat.text
        assert chat.json().get("data", {}).get("reply") == "phase 2c ok"
        assert mock_route.call_args.kwargs.get("user_id") == user_id

        impersonate = client.post(
            "/api/chat",
            headers=headers,
            json={"user_id": foreign_id, "message": "hello nova"},
        )
        assert impersonate.status_code == 403, impersonate.text

        stream_impersonate = client.post(
            "/api/chat/stream",
            headers=headers,
            json={"user_id": foreign_id, "message": "hello nova"},
        )
        assert stream_impersonate.status_code == 403, stream_impersonate.text

    history = client.get(f"/api/history/{user_id}", headers=headers)
    assert history.status_code == 200, history.text
    assert history.json().get("user_id") == user_id

    foreign_history = client.get(f"/api/history/{foreign_id}", headers=headers)
    assert foreign_history.status_code == 403, foreign_history.text

    reset = client.post("/api/reset", headers=headers, json={"user_id": user_id})
    assert reset.status_code == 200, reset.text
    assert reset.json().get("success") is True

    history_after_reset = client.get(f"/api/history/{user_id}", headers=headers)
    assert history_after_reset.status_code == 200, history_after_reset.text
    assert history_after_reset.json().get("user_id") == user_id
    assert history_after_reset.json().get("messages") == []

    foreign_reset = client.post("/api/reset", headers=headers, json={"user_id": foreign_id})
    assert foreign_reset.status_code == 403, foreign_reset.text


def test_streaming_path_remains_functional_for_authenticated_user(client: TestClient) -> None:
    auth = _login(client, "admin@amicor.local")
    headers = _headers(auth["access_token"])
    user_id = auth["user_id"]

    async def fake_stream(_message: str, bound_user_id: str):
        assert bound_user_id == user_id
        yield 'data: {"type": "token", "content": "hello"}\n\n'
        yield "data: [DONE]\n\n"

    with patch("app.main._stream_openai", side_effect=fake_stream):
        response = client.post(
            "/api/chat/stream",
            headers=headers,
            json={"user_id": user_id, "message": "xyzzy phase2c stream probe"},
        )
    assert response.status_code == 200, response.text
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert '"type": "token"' in body or '"type":"token"' in body
    assert "[DONE]" in body


def test_governance_and_nova_shell_remain_intact_and_workspace_stays_available() -> None:
    client = TestClient(app)
    for path in ["/app", "/app/ai-assistant", "/workspace"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} -> {response.status_code}"

    chassis = OPS_JS.split("function renderNovaGovernanceChassis()", 1)[1].split(
        "var novaConversationAbort", 1
    )[0]
    for control in ["preview", "inspect", "simulate", "confirm", "cancel"]:
        assert 'data-assistant-intent="' + control + '"' in chassis, control
    assert "renderSafetyIndicators()" in chassis
    assert "NOVA_SHELL_PANES" in OPS_JS
    assert "function renderNovaShellChrome()" in OPS_JS
    assert 'data-route="ai-assistant"' in OPS_HTML
    assert "/workspace remains the live conversation source" in OPS_JS
    assert "function renderOperationsHome()" in OPS_JS
    assert "function renderNovaConversationPane()" in OPS_JS
    assert 'id: "voice"' in OPS_JS
    assert "iframe" not in chassis.lower()
