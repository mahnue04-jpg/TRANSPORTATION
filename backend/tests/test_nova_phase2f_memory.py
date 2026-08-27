"""Phase 2F: connect existing authenticated Nova memory/continuity to /app/ai-assistant.

Reuses GET /api/history/{user_id} and POST /api/reset already used by Conversation.
Does not add a second memory store or migrate /workspace.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.database import init_db, save_memory_summary, save_message, save_preference
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


def test_memory_pane_renders_existing_history_continuity_source() -> None:
    pane = OPS_JS.split("function renderNovaMemoryPane()", 1)[1].split(
        "function ensureNovaMemoryHydrated()", 1
    )[0]
    for fragment in [
        "function renderNovaMemoryPane",
        "function loadNovaConversationHistory",
        "function applyNovaHistoryPayload",
        "function novaMemoryState",
        "function novaMemoryAuthFetch",
        "function ensureNovaMemoryHydrated",
        "function bindNovaMemoryEvents",
        "/api/history/",
        "/api/reset",
        "novaConversationAuthFetch",
        "data-nova-memory-refresh",
        "data-nova-memory-reset",
        'id="nova-memory-empty"',
        'id="nova-memory-summary-empty"',
        'id="nova-memory-history-empty"',
        'id="nova-memory-preferences-empty"',
    ]:
        assert fragment in OPS_JS, fragment
    assert "/api/history/" in pane or "GET /api/history" in pane
    memory_block = OPS_JS.split("function renderNovaMemoryPane()", 1)[1].split(
        "function renderAssistant()", 1
    )[0]
    assert 'fetch("/api/ops/workspace/action"' not in memory_block
    assert "<iframe" not in memory_block.lower()
    assert "CREATE TABLE" not in memory_block
    memory_def = OPS_JS.split('id: "memory"', 1)[1][:500]
    assert "Live" in memory_def
    assistant = OPS_JS.split("function renderAssistant()", 1)[1][:700]
    assert 'pane.id === "memory"' in assistant
    assert 'pane.id === "conversation"' in assistant
    assert 'pane.id === "files"' in assistant
    assert 'pane.id === "voice"' in assistant


def test_unauthenticated_history_access_is_blocked(client: TestClient) -> None:
    history = client.get("/api/history/spoof")
    reset = client.post("/api/reset", json={"user_id": "spoof"})
    assert history.status_code == 401, history.text
    assert reset.status_code == 401, reset.text


def test_authenticated_history_retrieval_and_empty_state(client: TestClient) -> None:
    auth = _login(client, "rider@amicor.local")
    headers = _headers(auth["access_token"])
    user_id = auth["user_id"]

    reset = client.post("/api/reset", headers=headers, json={"user_id": user_id})
    assert reset.status_code == 200, reset.text

    empty = client.get(f"/api/history/{user_id}", headers=headers)
    assert empty.status_code == 200, empty.text
    empty_body = empty.json()
    assert empty_body.get("user_id") == user_id
    assert empty_body.get("messages") == []
    memory = empty_body.get("memory") or {}
    assert not memory.get("summary")
    assert memory.get("preferences") == {}


def test_authenticated_continuity_uses_existing_store_and_rejects_foreign_user(
    client: TestClient,
) -> None:
    rider = _login(client, "rider@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")
    headers = _headers(rider["access_token"])
    user_id = rider["user_id"]
    foreign_id = dispatcher["user_id"]
    assert user_id != foreign_id

    save_message(user_id, "user", "phase2f continuity probe")
    save_message(user_id, "assistant", "remembered from existing history store")
    save_memory_summary(user_id, "Rider is verifying Nova continuity.")
    save_preference(user_id, "role_note", "dispatcher-adjacent")

    history = client.get(f"/api/history/{user_id}?limit=40", headers=headers)
    assert history.status_code == 200, history.text
    body = history.json()
    assert body.get("user_id") == user_id
    contents = " ".join(str(item.get("content") or "") for item in body.get("messages") or [])
    assert "phase2f continuity probe" in contents
    memory = body.get("memory") or {}
    assert "Rider is verifying Nova continuity." in str(memory.get("summary") or "")
    assert (memory.get("preferences") or {}).get("role_note") == "dispatcher-adjacent"

    foreign = client.get(f"/api/history/{foreign_id}", headers=headers)
    assert foreign.status_code == 403, foreign.text
    foreign_reset = client.post("/api/reset", headers=headers, json={"user_id": foreign_id})
    assert foreign_reset.status_code == 403, foreign_reset.text

    cleanup = client.post("/api/reset", headers=headers, json={"user_id": user_id})
    assert cleanup.status_code == 200, cleanup.text


def test_conversation_voice_files_governance_remain_intact_and_workspace_stays_available() -> None:
    client = TestClient(app)
    for path in ["/app", "/app/ai-assistant", "/workspace"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} -> {response.status_code}"

    assert "function renderNovaConversationPane()" in OPS_JS
    assert "function sendNovaConversationMessage" in OPS_JS
    assert "function renderNovaVoicePane()" in OPS_JS
    assert "function renderNovaFilesPane()" in OPS_JS
    assert "AmiCorUpload.init" in OPS_JS
    chassis = OPS_JS.split("function renderNovaGovernanceChassis()", 1)[1].split(
        "var novaConversationAbort", 1
    )[0]
    for control in ["preview", "inspect", "simulate", "confirm", "cancel"]:
        assert 'data-assistant-intent="' + control + '"' in chassis, control
    assert "renderSafetyIndicators()" in chassis
    assert "NOVA_SHELL_PANES" in OPS_JS
    assert 'data-route="ai-assistant"' in OPS_HTML
    assert "/workspace remains the live conversation source" in OPS_JS
    assert "<iframe" not in chassis.lower()
    for pane_id, kicker in [
        ("conversation", "Live"),
        ("voice", "Live"),
        ("files", "Live"),
        ("memory", "Live"),
    ]:
        definition = OPS_JS.split('id: "' + pane_id + '"', 1)[1][:500]
        assert kicker in definition, pane_id
    health_def = OPS_JS.split('id: "health-isf"', 1)[1][:500]
    assert "Live" in health_def


def test_streaming_conversation_still_works_for_authenticated_user(client: TestClient) -> None:
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
            json={"user_id": user_id, "message": "xyzzy phase2f stream probe"},
        )
    assert response.status_code == 200, response.text
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert '"type": "token"' in body or '"type":"token"' in body
    assert "[DONE]" in body
