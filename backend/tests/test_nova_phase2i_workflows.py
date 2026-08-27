"""Phase 2I: connect existing workflow_runner to /app/ai-assistant Workflows pane.

Reuses WorkflowRunnerTool via POST /api/chat after Governance confirm/cancel.
Does not add a second workflow engine, queue, or schema.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.database import init_db
from app.main import app
from app.tool_actions import WorkflowRunnerTool

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")

WORKFLOW_PROMPT = "Run workflow. Orchestrate the existing assistant 5-step workflow plan."
WORKFLOW_STEPS = [
    "Generate startup checklist",
    "Generate pricing ideas",
    "Generate marketing suggestions",
    "Generate business plan summary",
    "Recommend next steps",
]


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


def test_workflows_pane_renders_existing_workflow_runner_source() -> None:
    pane = OPS_JS.split("function renderNovaWorkflowsPane()", 1)[1].split(
        "function requestNovaWorkflow()", 1
    )[0]
    for fragment in [
        "function renderNovaWorkflowsPane",
        "function requestNovaWorkflow",
        "function confirmNovaWorkflow",
        "function cancelNovaWorkflow",
        "function maybeLaunchNovaWorkflowRunner",
        "function novaWorkflowsState",
        "function bindNovaWorkflowsEvents",
        "handleIntentConfirmation",
        "handleIntentCancel",
        "sendNovaConversationMessage",
        "workflow_runner",
        "POST /api/chat",
        "data-nova-workflow-start",
        "data-nova-workflow-confirm",
        "data-nova-workflow-cancel",
        "data-nova-workflow-refresh",
        'id="nova-workflows-empty"',
        'id="nova-workflows-error"',
        "var NOVA_WORKFLOW_PROMPT",
        "var NOVA_WORKFLOW_STEPS",
    ]:
        assert fragment in OPS_JS, fragment
    assert WORKFLOW_PROMPT in OPS_JS
    for step in WORKFLOW_STEPS:
        assert step in pane or step in OPS_JS
    workflows_block = OPS_JS.split("function renderNovaWorkflowsPane()", 1)[1].split(
        "function renderAssistant()", 1
    )[0]
    assert 'fetch("/api/ops/workspace/action"' not in workflows_block
    assert "<iframe" not in workflows_block.lower()
    assert "CREATE TABLE" not in workflows_block
    assert "/api/health-isf/" not in workflows_block
    assert "execute_workflow" not in workflows_block or "does not call ToolExecutionEngine.execute_workflow" in workflows_block
    workflows_def = OPS_JS.split('id: "workflows"', 1)[1][:700]
    assert "Live" in workflows_def
    assistant = OPS_JS.split("function renderAssistant()", 1)[1][:1400]
    assert 'pane.id === "workflows"' in assistant
    assert "renderNovaWorkflowsPane()" in assistant
    assert 'pane.id === "approvals"' in assistant
    policy = OPS_JS.split("function evaluateGuardrailPolicy", 1)[1].split(
        "function signatureForAuditEvent", 1
    )[0]
    assert "workflow" in policy
    assert "REQUIRES_CONFIRMATION" in policy
    assert "handleIntentConfirmation" in pane or "Confirm / Approve" in pane


def test_workflow_runner_catalog_matches_existing_tool() -> None:
    tool = WorkflowRunnerTool()
    assert tool.tool_id == "workflow_runner"
    assert "workflow" in tool.supported_intents
    assert "orchestrate" in tool.supported_intents
    for step in WORKFLOW_STEPS:
        assert step in OPS_JS, step
    assert 'id: "workflow_runner"' in OPS_JS


def test_unauthenticated_workflow_chat_is_blocked(client: TestClient) -> None:
    chat = client.post("/api/chat", json={"user_id": "spoof", "message": WORKFLOW_PROMPT})
    stream = client.post("/api/chat/stream", json={"user_id": "spoof", "message": WORKFLOW_PROMPT})
    preview = client.post(
        "/api/assistant/preview",
        json={"intent": "preview", "prompt": WORKFLOW_PROMPT, "role": "admin", "session_id": "unauth-wf"},
    )
    assert chat.status_code == 401, chat.text
    assert stream.status_code == 401, stream.text
    assert preview.status_code == 401, preview.text


def test_authenticated_workflow_runner_chat_is_identity_scoped_and_governance_bound(
    client: TestClient,
) -> None:
    admin = _login(client, "admin@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")
    admin_headers = _headers(admin["access_token"])
    dispatcher_headers = _headers(dispatcher["access_token"])
    user_id = admin["user_id"]
    foreign_id = dispatcher["user_id"]
    assert user_id != foreign_id

    preview = client.post(
        "/api/assistant/preview",
        headers=admin_headers,
        json={
            "intent": "preview",
            "prompt": WORKFLOW_PROMPT,
            "role": "admin",
            "scope": "assistant-workspace",
            "session_id": "phase2i-admin-workflow",
            "context": {"source": "phase2i-test"},
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json().get("confirmation", {}).get("signed_token")

    stolen = client.post(
        "/api/assistant/confirm",
        headers=dispatcher_headers,
        json={
            "token": preview.json()["confirmation"]["signed_token"],
            "intent_id": preview.json()["confirmation"]["intent_id"],
            "action_type": preview.json()["confirmation"]["action_type"],
            "session_id": preview.json()["confirmation"]["session_id"],
            "intent_hash": preview.json()["integrity"]["intent_hash"],
            "preview_payload_hash": preview.json()["integrity"]["preview_payload_hash"],
            "dependency_graph_hash": preview.json()["integrity"]["dependency_graph_hash"],
            "safety_classification_hash": preview.json()["integrity"]["safety_classification_hash"],
            "supervision_classification": preview.json()["supervision_classification"],
            "nonce": preview.json()["confirmation"]["nonce"],
            "correlation_id": preview.json()["confirmation"]["correlation_id"],
            "policy_version": preview.json()["confirmation"]["policy_version"],
        },
    )
    assert stolen.status_code in {401, 403, 404}, stolen.text

    with patch("app.main.route_message") as mock_route:
        mock_route.return_value = {
            "response": "phase 2i workflow plan",
            "tool": "business",
            "sources": [],
            "status": "success",
            "capability": {"name": "business", "permission": "business.advice", "live": True},
            "meta": {
                "tool_executed": True,
                "tool_id": "workflow_runner",
                "workflow_steps": WORKFLOW_STEPS,
            },
        }
        chat = client.post(
            "/api/chat",
            headers=admin_headers,
            json={"user_id": user_id, "message": WORKFLOW_PROMPT},
        )
        assert chat.status_code == 200, chat.text
        body = chat.json()
        assert body.get("data", {}).get("meta", {}).get("tool_id") == "workflow_runner"
        assert body.get("data", {}).get("meta", {}).get("workflow_steps") == WORKFLOW_STEPS
        assert mock_route.call_args.kwargs.get("user_id") == user_id

        impersonate = client.post(
            "/api/chat",
            headers=admin_headers,
            json={"user_id": foreign_id, "message": WORKFLOW_PROMPT},
        )
        assert impersonate.status_code == 403, impersonate.text


def test_empty_and_error_states_are_rendered_in_workflows_pane() -> None:
    pane = OPS_JS.split("function renderNovaWorkflowsPane()", 1)[1].split(
        "function requestNovaWorkflow()", 1
    )[0]
    assert 'id="nova-workflows-empty"' in pane
    assert "No workflow has been requested" in pane
    assert "Sign in to request Nova workflows" in pane
    assert 'id="nova-workflows-error"' in pane
    assert "Sign in required to request Nova workflows" in OPS_JS
    assert "No workflow is waiting for Governance confirmation" in OPS_JS
    assert "does not queue, schedule, or mutate Health ISF" in pane or "does not queue" in OPS_JS


def test_conversation_approvals_tools_governance_remain_intact_and_workspace_stays_available() -> None:
    client = TestClient(app)
    for path in ["/app", "/app/ai-assistant", "/workspace"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} -> {response.status_code}"

    assert "function renderNovaConversationPane()" in OPS_JS
    assert "function renderNovaToolsPane()" in OPS_JS
    assert "function renderNovaApprovalsPane()" in OPS_JS
    assert "function handleIntentConfirmation" in OPS_JS
    assert "function handleIntentCancel" in OPS_JS
    chassis = OPS_JS.split("function renderNovaGovernanceChassis()", 1)[1].split(
        "var novaConversationAbort", 1
    )[0]
    for control in ["preview", "inspect", "simulate", "confirm", "cancel"]:
        assert 'data-assistant-intent="' + control + '"' in chassis, control
    assert "renderSafetyIndicators()" in chassis
    assert "/workspace remains the live conversation source" in OPS_JS
    assert 'data-route="ai-assistant"' in OPS_HTML
    assert "<iframe" not in chassis.lower()
    for pane_id, kicker in [
        ("conversation", "Live"),
        ("voice", "Live"),
        ("files", "Live"),
        ("memory", "Live"),
        ("tools", "Live"),
        ("approvals", "Live"),
        ("workflows", "Live"),
    ]:
        definition = OPS_JS.split('id: "' + pane_id + '"', 1)[1][:500]
        assert kicker in definition, pane_id
    health_def = OPS_JS.split('id: "health-isf"', 1)[1][:500]
    assert "Live" in health_def
    assert "workflows live" in OPS_JS
    assert "health-isf live" in OPS_JS


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
            json={"user_id": user_id, "message": "xyzzy phase2i stream probe"},
        )
    assert response.status_code == 200, response.text
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert '"type": "token"' in body or '"type":"token"' in body
    assert "[DONE]" in body
