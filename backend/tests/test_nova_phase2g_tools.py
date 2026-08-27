"""Phase 2G: connect existing authenticated Nova business tools to /app/ai-assistant.

Reuses CAPABILITIES in app/router.py, app/business.py, and POST /api/chat.
Does not add a second tool engine or migrate /workspace.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.database import init_db
from app.main import app
from app.router import CAPABILITIES
from app.tool_registry import get_registry

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")

BUSINESS_PLAN_PROMPT = (
    "Help me with a business plan checklist for a small transportation company."
)


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


def test_tools_pane_renders_existing_capability_catalog() -> None:
    pane = OPS_JS.split("function renderNovaToolsPane()", 1)[1].split(
        "async function invokeNovaBusinessTool", 1
    )[0]
    for fragment in [
        "function renderNovaToolsPane",
        "function invokeNovaBusinessTool",
        "function novaToolsState",
        "function novaToolsAuthFetch",
        "function bindNovaToolsEvents",
        "function novaBusinessToolCatalog",
        "sendNovaConversationMessage",
        "novaConversationAuthFetch",
        "POST /api/chat",
        "data-nova-tool-id",
        'id="nova-tools-empty"',
        'id="nova-tools-error"',
        'id="nova-tools-result-empty"',
        "var NOVA_BUSINESS_CAPABILITIES",
        "var NOVA_REGISTERED_BUSINESS_TOOLS",
    ]:
        assert fragment in OPS_JS, fragment
    assert "POST /api/chat" in pane or "/api/chat" in pane
    tools_block = OPS_JS.split("function renderNovaToolsPane()", 1)[1].split(
        "function renderAssistant()", 1
    )[0]
    assert 'fetch("/api/ops/workspace/action"' not in tools_block
    assert "<iframe" not in tools_block.lower()
    assert "CREATE TABLE" not in tools_block
    assert "/api/health-isf/" not in tools_block
    tools_def = OPS_JS.split('id: "tools"', 1)[1][:600]
    assert "Live" in tools_def
    assistant = OPS_JS.split("function renderAssistant()", 1)[1][:900]
    assert 'pane.id === "tools"' in assistant
    assert 'pane.id === "conversation"' in assistant
    assert 'pane.id === "memory"' in assistant
    assert 'pane.id === "voice"' in assistant
    assert 'pane.id === "files"' in assistant


def test_tools_catalog_matches_existing_capabilities_and_registry() -> None:
    capability_block = OPS_JS.split("var NOVA_BUSINESS_CAPABILITIES =", 1)[1].split(
        "var NOVA_REGISTERED_BUSINESS_TOOLS =", 1
    )[0]
    for name in CAPABILITIES:
        assert 'id: "' + name + '"' in capability_block, name
        assert CAPABILITIES[name]["permission"] in capability_block

    registry_block = OPS_JS.split("var NOVA_REGISTERED_BUSINESS_TOOLS =", 1)[1].split(
        "function novaToolsState()", 1
    )[0]
    expected_ids = {
        "business_plan",
        "proposal",
        "invoice",
        "marketing",
        "research_collector",
        "email_draft_builder",
        "browser_open",
        "workflow_runner",
        "memory_lookup",
    }
    registered_ids = {item["tool_id"] for item in get_registry().list_tools()}
    assert expected_ids.issubset(registered_ids)
    for tool_id in expected_ids:
        assert 'id: "' + tool_id + '"' in registry_block, tool_id
    for blocked in ["browser_open", "workflow_runner", "memory_lookup"]:
        assert "invoke: false" in registry_block
        assert 'id: "' + blocked + '"' in registry_block


def test_unauthenticated_tool_chat_access_is_blocked(client: TestClient) -> None:
    chat = client.post("/api/chat", json={"user_id": "spoof", "message": BUSINESS_PLAN_PROMPT})
    stream = client.post(
        "/api/chat/stream",
        json={"user_id": "spoof", "message": BUSINESS_PLAN_PROMPT},
    )
    assert chat.status_code == 401, chat.text
    assert stream.status_code == 401, stream.text


def test_authenticated_business_tool_invocation_uses_existing_chat_and_rejects_foreign_user(
    client: TestClient,
) -> None:
    rider = _login(client, "rider@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")
    headers = _headers(rider["access_token"])
    user_id = rider["user_id"]
    foreign_id = dispatcher["user_id"]
    assert user_id != foreign_id

    with patch("app.main.route_message") as mock_route:
        mock_route.return_value = {
            "response": "phase 2g business tool reply",
            "tool": "business",
            "sources": [],
            "status": "success",
            "capability": {
                "name": "business",
                "permission": "business.advice",
                "live": True,
            },
            "meta": {"tool_executed": True, "tool_id": "business_plan"},
        }
        chat = client.post(
            "/api/chat",
            headers=headers,
            json={"user_id": user_id, "message": BUSINESS_PLAN_PROMPT},
        )
        assert chat.status_code == 200, chat.text
        body = chat.json()
        assert body.get("data", {}).get("reply") == "phase 2g business tool reply"
        assert mock_route.call_args.kwargs.get("user_id") == user_id
        assert BUSINESS_PLAN_PROMPT in str(mock_route.call_args)

        impersonate = client.post(
            "/api/chat",
            headers=headers,
            json={"user_id": foreign_id, "message": BUSINESS_PLAN_PROMPT},
        )
        assert impersonate.status_code == 403, impersonate.text

        stream = client.post(
            "/api/chat/stream",
            headers=headers,
            json={"user_id": user_id, "message": BUSINESS_PLAN_PROMPT},
        )
        assert stream.status_code == 200, stream.text
        assert "text/event-stream" in stream.headers.get("content-type", "")
        assert "phase 2g business tool reply" in stream.text

        stream_impersonate = client.post(
            "/api/chat/stream",
            headers=headers,
            json={"user_id": foreign_id, "message": BUSINESS_PLAN_PROMPT},
        )
        assert stream_impersonate.status_code == 403, stream_impersonate.text


def test_empty_and_error_states_are_rendered_in_tools_pane() -> None:
    pane = OPS_JS.split("function renderNovaToolsPane()", 1)[1].split(
        "async function invokeNovaBusinessTool", 1
    )[0]
    assert 'id="nova-tools-empty"' in pane
    assert "No business-tool result yet" in pane
    assert "Sign in to use Nova business tools" in pane
    assert 'id="nova-tools-error"' in pane
    assert "Sign in required to run Nova business tools" in OPS_JS
    assert "Unknown Nova business tool" in OPS_JS
    assert "This capability is not launched from Business Tools" in OPS_JS or (
        "invoke: false" in OPS_JS and "Not launched from this pane" in OPS_JS
    )


def test_conversation_voice_files_memory_governance_remain_intact_and_workspace_stays_available() -> None:
    client = TestClient(app)
    for path in ["/app", "/app/ai-assistant", "/workspace"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} -> {response.status_code}"

    assert "function renderNovaConversationPane()" in OPS_JS
    assert "function sendNovaConversationMessage" in OPS_JS
    assert "function renderNovaVoicePane()" in OPS_JS
    assert "function renderNovaFilesPane()" in OPS_JS
    assert "function renderNovaMemoryPane()" in OPS_JS
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
        ("tools", "Live"),
    ]:
        definition = OPS_JS.split('id: "' + pane_id + '"', 1)[1][:500]
        assert kicker in definition, pane_id
    health_def = OPS_JS.split('id: "health-isf"', 1)[1][:500]
    assert "Live" in health_def
    assert "tools live" in OPS_JS


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
            json={"user_id": user_id, "message": "xyzzy phase2g stream probe"},
        )
    assert response.status_code == 200, response.text
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert '"type": "token"' in body or '"type":"token"' in body
    assert "[DONE]" in body
