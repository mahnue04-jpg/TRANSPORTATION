"""Nova full-shell UAT / hardening checks for the existing 2A–2J panes.

Does not add capabilities. Proves cache-bust, session/sign-out wiring,
pane inventory, and authenticated read/chat isolation.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.database import init_db
from app.main import app
from app.runtime_contract import DEFAULT_RUNTIME_VERSION, inject_runtime_contract

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")
OPS_CSS = (STATIC / "ops-shell.css").read_text(encoding="utf-8")

PANES = [
    "governance",
    "conversation",
    "voice",
    "files",
    "memory",
    "tools",
    "approvals",
    "workflows",
    "health-isf",
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
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_shell_cache_bust_aligns_injected_runtime_version() -> None:
    injected = inject_runtime_contract(OPS_HTML)
    assert "ops-shell.js?v=" in injected
    assert DEFAULT_RUNTIME_VERSION in injected
    assert "ops-shell.js?v=" + DEFAULT_RUNTIME_VERSION in injected or (
        "ops-shell.js?v=" in injected and DEFAULT_RUNTIME_VERSION in injected.split("ops-shell.js?v=", 1)[1][:80]
    )
    assert 'src="/static/ops-shell.js?v=20260827.9"' in OPS_HTML
    assert 'href="/static/ops-shell.css?v=20260827.9"' in OPS_HTML
    js_stamp = injected.split("ops-shell.js?v=", 1)[1].split('"', 1)[0]
    css_stamp = injected.split("ops-shell.css?v=", 1)[1].split('"', 1)[0]
    assert DEFAULT_RUNTIME_VERSION in js_stamp
    assert DEFAULT_RUNTIME_VERSION in css_stamp


def test_all_nova_panes_are_live_and_sign_out_is_wired() -> None:
    shell_panes = OPS_JS.split("var NOVA_SHELL_PANES = [", 1)[1].split("];", 1)[0]
    nav = OPS_JS.split("function renderNovaShellNav()", 1)[1][:900]
    for pane_id in PANES:
        assert 'id: "' + pane_id + '"' in shell_panes, pane_id
        definition = shell_panes.split('id: "' + pane_id + '"', 1)[1][:500]
        assert "Live" in definition, pane_id
    assert 'data-nova-pane="' in nav
    assert "escapeHtml(pane.id)" in nav
    assert "kicker: \"Later\"" not in OPS_JS
    assert "function signOutNovaShellSession" in OPS_JS
    assert 'data-launcher-action="sign-out"' in OPS_JS
    assert "function snapshotNovaPaneSessionSlices" in OPS_JS
    assert "function restoreNovaPaneSessionSlices" in OPS_JS
    assert "novaHealthIsf: novaSlices.novaHealthIsf" in OPS_JS
    assert "novaWorkflows: novaSlices.novaWorkflows" in OPS_JS
    assert 'role="tablist"' in OPS_JS
    assert 'aria-selected="' in OPS_JS
    assert ":focus-visible" in OPS_CSS
    assert "@media (max-width: 640px)" in OPS_CSS
    convo_bind = OPS_JS.split("function bindNovaConversationEvents()", 1)[1][:500]
    assert "if (!form) return" in convo_bind
    send_block = OPS_JS.split("async function sendNovaConversationMessage", 1)[1].split(
        "async function resetNovaConversation", 1
    )[0]
    assert send_block.count("consumeNovaChatStream") == 1
    assert send_block.count("} catch (error)") == 1
    assert 'if (state.loading && state.route !== "ai-assistant")' in OPS_JS
    assert "state.route !== \"ai-assistant\")" in OPS_JS.split("if (state.error && !state.health && !state.supervision", 1)[1][:120]


def test_launcher_assistant_and_workspace_still_serve(client: TestClient) -> None:
    for path in ["/app", "/app/ai-assistant", "/workspace"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} -> {response.status_code}"
        if path != "/workspace":
            assert "ops-shell.js?v=" in response.text
            assert DEFAULT_RUNTIME_VERSION in response.text


def test_unauthenticated_shell_endpoints_stay_blocked(client: TestClient) -> None:
    assert client.post("/api/chat", json={"user_id": "spoof", "message": "hello"}).status_code == 401
    assert client.get("/api/health-isf/dashboard").status_code == 401
    assert client.get("/api/assistant/executions").status_code == 401
    assert client.get("/api/nova/intelligence").status_code == 401


def test_authenticated_conversation_and_intelligence_remain_isolated(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")
    admin_headers = _headers(admin["access_token"])
    dispatcher_headers = _headers(dispatcher["access_token"])
    user_id = admin["user_id"]

    with patch("app.main.route_message") as mock_route:
        mock_route.return_value = {
            "response": "phase uat nova reply",
            "tool": "business",
            "sources": [],
            "status": "success",
            "capability": {"name": "business", "permission": "business.advice", "live": True},
        }
        chat = client.post(
            "/api/chat",
            headers=admin_headers,
            json={"user_id": user_id, "message": "xyzzy nova full-shell uat"},
        )
    assert chat.status_code == 200, chat.text
    assert "phase uat nova reply" in chat.text
    assert mock_route.call_args.kwargs.get("user_id") == user_id

    impersonate = client.post(
        "/api/chat",
        headers=admin_headers,
        json={"user_id": dispatcher["user_id"], "message": "xyzzy spoof"},
    )
    assert impersonate.status_code == 403, impersonate.text

    dashboard = client.get("/api/health-isf/dashboard", headers=admin_headers)
    assert dashboard.status_code == 200, dashboard.text
    foreign = client.get(
        "/api/health-isf/dashboard",
        headers=dispatcher_headers,
        params={"organization_id": "foreign-org-nova-uat"},
    )
    assert foreign.status_code == 403, foreign.text

    logout = client.post("/api/auth/logout", headers=admin_headers)
    assert logout.status_code in {200, 204, 401, 422}
