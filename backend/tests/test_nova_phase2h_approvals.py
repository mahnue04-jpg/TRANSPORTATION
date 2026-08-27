"""Phase 2H: connect existing Governance approvals to /app/ai-assistant Approval Center.

Reuses pendingIntent, handleIntentConfirmation, handleIntentCancel, and
GET /api/assistant/executions. Does not add a second approval engine.
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


def _preview(client: TestClient, headers: dict[str, str], *, session_id: str, prompt: str) -> dict:
    response = client.post(
        "/api/assistant/preview",
        headers=headers,
        json={
            "intent": "preview",
            "prompt": prompt,
            "role": "admin",
            "scope": "assistant-workspace",
            "session_id": session_id,
            "context": {"source": "phase2h-test"},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _confirm(client: TestClient, headers: dict[str, str], preview: dict) -> dict:
    confirmation = preview["confirmation"]
    integrity = preview["integrity"]
    response = client.post(
        "/api/assistant/confirm",
        headers=headers,
        json={
            "token": confirmation["signed_token"],
            "intent_id": confirmation["intent_id"],
            "action_type": confirmation["action_type"],
            "session_id": confirmation["session_id"],
            "intent_hash": integrity["intent_hash"],
            "preview_payload_hash": integrity["preview_payload_hash"],
            "dependency_graph_hash": integrity["dependency_graph_hash"],
            "safety_classification_hash": integrity["safety_classification_hash"],
            "supervision_classification": preview["supervision_classification"],
            "nonce": confirmation["nonce"],
            "correlation_id": confirmation["correlation_id"],
            "policy_version": confirmation["policy_version"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_approvals_pane_renders_existing_governance_source() -> None:
    pane = OPS_JS.split("function renderNovaApprovalsPane()", 1)[1].split(
        "async function refreshNovaApprovals", 1
    )[0]
    for fragment in [
        "function renderNovaApprovalsPane",
        "function refreshNovaApprovals",
        "function inspectNovaApproval",
        "function confirmNovaApproval",
        "function cancelNovaApproval",
        "function inspectNovaExecution",
        "function novaApprovalsState",
        "function novaApprovalsAuthFetch",
        "function bindNovaApprovalsEvents",
        "function ensureNovaApprovalsHydrated",
        "handleIntentConfirmation",
        "handleIntentCancel",
        "refreshAssistantPersistence",
        "/api/assistant/executions",
        "/api/assistant/confirm",
        "/api/assistant/inspect",
        "data-nova-approval-inspect",
        "data-nova-approval-confirm",
        "data-nova-approval-cancel",
        "data-nova-approval-refresh",
        'id="nova-approvals-empty"',
        'id="nova-approvals-error"',
        'id="nova-approvals-pending-empty"',
        'id="nova-approvals-history-empty"',
    ]:
        assert fragment in OPS_JS, fragment
    assert "GET /api/assistant/executions" in pane
    assert "handleIntentConfirmation" in pane or "POST /api/assistant/confirm" in pane
    approvals_block = OPS_JS.split("function renderNovaApprovalsPane()", 1)[1].split(
        "var NOVA_WORKFLOW_PROMPT", 1
    )[0]
    assert 'fetch("/api/ops/workspace/action"' not in approvals_block
    assert "<iframe" not in approvals_block.lower()
    assert "CREATE TABLE" not in approvals_block
    assert "/api/health-isf/" not in approvals_block
    assert "workflow_runner" not in approvals_block
    approvals_def = OPS_JS.split('id: "approvals"', 1)[1][:700]
    assert "Live" in approvals_def
    assistant = OPS_JS.split("function renderAssistant()", 1)[1][:1100]
    assert 'pane.id === "approvals"' in assistant
    assert 'pane.id === "tools"' in assistant
    assert 'pane.id === "conversation"' in assistant
    assert 'pane.id === "memory"' in assistant


def test_unauthenticated_approval_endpoints_are_blocked(client: TestClient) -> None:
    executions = client.get("/api/assistant/executions")
    preview = client.post(
        "/api/assistant/preview",
        json={"intent": "preview", "prompt": "phase2h unauth", "role": "admin", "session_id": "unauth"},
    )
    inspect = client.post(
        "/api/assistant/inspect",
        json={"intent": "inspect", "prompt": "phase2h unauth", "role": "admin", "session_id": "unauth"},
    )
    confirm = client.post("/api/assistant/confirm", json={"token": "spoof"})
    detail = client.get("/api/assistant/executions/exec-spoof")
    assert executions.status_code == 401, executions.text
    assert preview.status_code == 401, preview.text
    assert inspect.status_code == 401, inspect.text
    assert confirm.status_code == 401, confirm.text
    assert detail.status_code == 401, detail.text


def test_authenticated_approval_history_is_identity_scoped(client: TestClient) -> None:
    rider = _login(client, "rider@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")
    admin = _login(client, "admin@amicor.local")
    admin_headers = _headers(admin["access_token"])
    dispatcher_headers = _headers(dispatcher["access_token"])
    rider_headers = _headers(rider["access_token"])
    assert admin["user_id"] != dispatcher["user_id"]
    assert admin["user_id"] != rider["user_id"]

    preview = _preview(
        client,
        admin_headers,
        session_id="phase2h-admin-session",
        prompt="phase2h admin approval preview",
    )
    stolen_confirm = client.post(
        "/api/assistant/confirm",
        headers=dispatcher_headers,
        json={
            "token": preview["confirmation"]["signed_token"],
            "intent_id": preview["confirmation"]["intent_id"],
            "action_type": preview["confirmation"]["action_type"],
            "session_id": preview["confirmation"]["session_id"],
            "intent_hash": preview["integrity"]["intent_hash"],
            "preview_payload_hash": preview["integrity"]["preview_payload_hash"],
            "dependency_graph_hash": preview["integrity"]["dependency_graph_hash"],
            "safety_classification_hash": preview["integrity"]["safety_classification_hash"],
            "supervision_classification": preview["supervision_classification"],
            "nonce": preview["confirmation"]["nonce"],
            "correlation_id": preview["confirmation"]["correlation_id"],
            "policy_version": preview["confirmation"]["policy_version"],
        },
    )
    assert stolen_confirm.status_code in {401, 403, 404}, stolen_confirm.text

    confirmed = _confirm(client, admin_headers, preview)
    execution_id = confirmed.get("workflow_execution", {}).get("execution_id")
    assert execution_id
    assert confirmed.get("confirmation_verification", {}).get("status") == "VERIFIED_PREVIEW"
    assert confirmed.get("workflow_execution", {}).get("status") == "completed"

    admin_list = client.get("/api/assistant/executions", params={"limit": 50}, headers=admin_headers)
    assert admin_list.status_code == 200, admin_list.text
    admin_ids = {item.get("execution_id") for item in admin_list.json().get("items") or []}
    assert execution_id in admin_ids
    admin_item = next(item for item in admin_list.json()["items"] if item.get("execution_id") == execution_id)
    assert admin_item.get("status") in {"completed", "pending", "failed"}
    assert admin_item.get("action_type")
    assert "result" in admin_item

    admin_detail = client.get(f"/api/assistant/executions/{execution_id}", headers=admin_headers)
    assert admin_detail.status_code == 200, admin_detail.text
    assert admin_detail.json().get("execution_id") == execution_id

    dispatcher_list = client.get("/api/assistant/executions", params={"limit": 50}, headers=dispatcher_headers)
    assert dispatcher_list.status_code == 200, dispatcher_list.text
    dispatcher_ids = {item.get("execution_id") for item in dispatcher_list.json().get("items") or []}
    assert execution_id not in dispatcher_ids

    rider_list = client.get("/api/assistant/executions", params={"limit": 50}, headers=rider_headers)
    assert rider_list.status_code == 200, rider_list.text
    rider_ids = {item.get("execution_id") for item in rider_list.json().get("items") or []}
    assert execution_id not in rider_ids

    foreign_detail = client.get(f"/api/assistant/executions/{execution_id}", headers=dispatcher_headers)
    assert foreign_detail.status_code == 404, foreign_detail.text


def test_empty_and_error_states_are_rendered_in_approvals_pane() -> None:
    pane = OPS_JS.split("function renderNovaApprovalsPane()", 1)[1].split(
        "async function refreshNovaApprovals", 1
    )[0]
    assert 'id="nova-approvals-empty"' in pane
    assert "No pending approvals or execution history" in pane
    assert "Sign in to review Nova approvals" in pane
    assert 'id="nova-approvals-error"' in pane
    assert "No pending action requires approval" in OPS_JS
    assert "No pending action to cancel" in OPS_JS
    assert "No requested action details to inspect" in OPS_JS
    assert "Sign in required to load Nova approvals" in OPS_JS


def test_conversation_voice_files_memory_tools_governance_remain_intact_and_workspace_stays_available() -> None:
    client = TestClient(app)
    for path in ["/app", "/app/ai-assistant", "/workspace"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} -> {response.status_code}"

    assert "function renderNovaConversationPane()" in OPS_JS
    assert "function sendNovaConversationMessage" in OPS_JS
    assert "function renderNovaVoicePane()" in OPS_JS
    assert "function renderNovaFilesPane()" in OPS_JS
    assert "function renderNovaMemoryPane()" in OPS_JS
    assert "function renderNovaToolsPane()" in OPS_JS
    assert "AmiCorUpload.init" in OPS_JS
    chassis = OPS_JS.split("function renderNovaGovernanceChassis()", 1)[1].split(
        "var novaConversationAbort", 1
    )[0]
    for control in ["preview", "inspect", "simulate", "confirm", "cancel"]:
        assert 'data-assistant-intent="' + control + '"' in chassis, control
    assert "renderSafetyIndicators()" in chassis
    assert 'data-confirm-intent="true"' in OPS_JS
    assert 'data-cancel-intent="true"' in OPS_JS
    assert "function renderPendingIntentCard" in OPS_JS
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
        ("approvals", "Live"),
    ]:
        definition = OPS_JS.split('id: "' + pane_id + '"', 1)[1][:500]
        assert kicker in definition, pane_id
    health_def = OPS_JS.split('id: "health-isf"', 1)[1][:500]
    assert "Live" in health_def
    assert "approvals live" in OPS_JS


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
            json={"user_id": user_id, "message": "xyzzy phase2h stream probe"},
        )
    assert response.status_code == 200, response.text
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert '"type": "token"' in body or '"type":"token"' in body
    assert "[DONE]" in body
