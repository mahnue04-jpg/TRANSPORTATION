"""Phase 2B: unified Amicor Nova shell inside /app/ai-assistant.

UI/chrome only. Does not migrate /workspace conversation or change Health ISF engines.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")
OPS_CSS = (STATIC / "ops-shell.css").read_text(encoding="utf-8")


def test_ai_assistant_renders_unified_nova_shell() -> None:
    client = TestClient(app)
    response = client.get("/app/ai-assistant", follow_redirects=False)
    assert response.status_code == 200, response.text
    assert "ops-shell.js" in response.text
    assert 'data-route="ai-assistant"' in OPS_HTML

    assert "NOVA_SHELL_PANES" in OPS_JS
    assert "function renderNovaShellChrome()" in OPS_JS
    assert "function renderNovaGovernanceChassis()" in OPS_JS
    assert "function renderAssistant()" in OPS_JS
    assert 'data-nova-shell="true"' in OPS_JS
    assert "nova-shell-nav" in OPS_JS
    assert "nova-shell-nav" in OPS_CSS
    for pane in [
        "governance",
        "conversation",
        "health-isf",
        "memory",
        "files",
        "tools",
        "workflows",
        "voice",
        "approvals",
    ]:
        assert 'id: "' + pane + '"' in OPS_JS, pane


def test_existing_nova_governance_controls_remain_available() -> None:
    chassis = OPS_JS.split("function renderNovaGovernanceChassis()", 1)[1].split(
        "function renderAssistant()", 1
    )[0]
    for fragment in [
        'data-assistant-intent="preview"',
        'data-assistant-intent="inspect"',
        'data-assistant-intent="simulate"',
        'data-assistant-intent="confirm"',
        'data-assistant-intent="cancel"',
        "function renderSafetyIndicators()",
        "function renderExecutionHistory",
        "Live Dispatch Assignment Queue",
        "/api/assistant/preview",
        "/api/assistant/inspect",
        "/api/assistant/simulate",
        "/api/assistant/confirm",
    ]:
        assert fragment in OPS_JS, fragment
    for control in ["preview", "inspect", "simulate", "confirm", "cancel"]:
        assert 'data-assistant-intent="' + control + '"' in chassis, control
    assert "renderSafetyIndicators()" in chassis
    assert "renderExecutionHistory" in chassis
    assert "/api/ops/workspace/action" not in chassis
    assert 'fetch("/api/chat"' not in chassis
    assert 'postJson("/api/chat"' not in chassis


def test_workspace_remains_live_source_and_is_not_migrated() -> None:
    client = TestClient(app)
    workspace = client.get("/workspace", follow_redirects=False)
    assert workspace.status_code == 200, workspace.text
    assert "/workspace remains the live conversation source" in OPS_JS
    assert 'source: "/workspace"' in OPS_JS
    assert "/workspace#/health-isf/grant" in OPS_JS
    prepared = OPS_JS.split("function renderNovaPreparedPane", 1)[1].split(
        "function renderNovaShellChrome", 1
    )[0]
    assert 'fetch("/api/chat"' not in prepared
    assert 'postJson("/api/ops/workspace/action"' not in prepared
    assert "does not duplicate that engine" in prepared


def test_phase2b_does_not_start_conversation_migration_or_workspace_action_backend() -> None:
    nova_helpers = OPS_JS.split("function normalizeNovaPane", 1)[1].split(
        "function renderNovaGovernanceChassis()", 1
    )[0]
    assert 'fetch("/api/chat"' not in nova_helpers
    assert 'postJson("/api/chat"' not in nova_helpers
    assert "/api/chat/stream" not in nova_helpers
    assert 'fetch("/api/ops/workspace/action"' not in nova_helpers
    assert 'postJson("/api/ops/workspace/action"' not in nova_helpers
    assert "iframe" not in nova_helpers.lower()
    assert "function renderOperationsHome()" in OPS_JS
    assert '"home": { path: APP_BASE_PATH' in OPS_JS
    assert "function renderDashboard()" in OPS_JS
    assert "function renderMobile()" in OPS_JS
    assert "function renderRidersRoute()" in OPS_JS


def test_operational_and_dedicated_shells_remain_intact() -> None:
    client = TestClient(app)
    for path in [
        "/app",
        "/app/home",
        "/app/dashboard",
        "/app/dispatch",
        "/app/trips",
        "/app/riders",
        "/app/mobile",
        "/app/ai-assistant",
        "/workspace",
    ]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} -> {response.status_code}"

    assert "function wrapDriverMobilePage" in OPS_JS or "wrapDriverMobilePage" in OPS_JS
    assert "function renderRidersRoute()" in OPS_JS
    assert "function renderDispatch()" in OPS_JS
    assert "function renderBilling()" in OPS_JS
    rider_block = OPS_JS.split('rider: ["home"', 1)[1].split("],", 1)[0]
    assert "dispatch" not in rider_block
    driver_block = OPS_JS.split('driver: ["home"', 1)[1].split("],", 1)[0]
    assert "dispatch" not in driver_block
