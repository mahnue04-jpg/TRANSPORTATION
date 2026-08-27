"""Phase 2J: read-only Health ISF intelligence pane in /app/ai-assistant.

Reuses existing Health ISF GET APIs, command-center snapshots, and GET /api/nova/intelligence.
Does not add a second operational engine and does not mutate Health ISF.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.database import init_db
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")

READ_SOURCES = OPS_JS.split("var NOVA_HEALTH_ISF_READ_SOURCES = [", 1)[1].split("];", 1)[0]
PANE = OPS_JS.split("function renderNovaHealthIsfIntelligencePane()", 1)[1].split(
    "async function refreshNovaHealthIsfIntelligence()", 1
)[0]
INTELLIGENCE_BLOCK = OPS_JS.split("var NOVA_HEALTH_ISF_READ_SOURCES = [", 1)[1].split(
    "function renderSystemHealth()", 1
)[0]

READ_PATHS = [
    "/api/health-isf/dashboard",
    "/api/health-isf/dispatch/queue?limit=80&read_only=true",
    "/api/health-isf/rides?limit=80&active_only=true&exclude_test=true",
    "/api/health-isf/rides?limit=40&history_only=true&exclude_test=true",
    "/api/health-isf/operations/command-center",
    "/api/health-isf/operations/alerts",
    "/api/health-isf/operations/billing-handoffs?limit=40",
    "/api/health-isf/recurring/schedules?active_only=true&limit=40",
    "/api/health-isf/operations/map-preview",
    "/api/health-isf/intelligence/summary",
    "/api/nova/intelligence",
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


def test_health_isf_intelligence_pane_renders_existing_read_sources() -> None:
    for fragment in [
        "function renderNovaHealthIsfIntelligencePane",
        "function refreshNovaHealthIsfIntelligence",
        "function novaHealthIsfState",
        "function novaHealthIsfAuthFetch",
        "function bindNovaHealthIsfEvents",
        "function ensureNovaHealthIsfHydrated",
        "data-nova-health-isf-refresh",
        'id="nova-health-isf-empty"',
        'id="nova-health-isf-error"',
        'id="nova-health-isf-unavailable"',
        "var NOVA_HEALTH_ISF_READ_SOURCES",
        "var NOVA_HEALTH_ISF_UNSUPPORTED",
        "read_only=true",
        "GET /api/nova/intelligence",
    ]:
        assert fragment in OPS_JS, fragment
    for path in READ_PATHS:
        assert path in READ_SOURCES, path
    assert "/api/health-isf/dispatch/active-assignments" not in READ_SOURCES
    assert "/api/health-isf/drivers?" not in READ_SOURCES
    assert "/api/health-isf/dispatch/workspace" not in READ_SOURCES
    assert "opts.method = \"GET\"" in INTELLIGENCE_BLOCK
    assert "method: \"GET\"" in INTELLIGENCE_BLOCK
    assert 'fetch("/api/ops/workspace/action"' not in INTELLIGENCE_BLOCK
    assert "<iframe" not in INTELLIGENCE_BLOCK.lower()
    assert "CREATE TABLE" not in INTELLIGENCE_BLOCK
    health_def = OPS_JS.split('id: "health-isf"', 1)[1][:700]
    assert "Live" in health_def
    assistant = OPS_JS.split("function renderAssistant()", 1)[1][:1400]
    assert 'pane.id === "health-isf"' in assistant
    assert "renderNovaHealthIsfIntelligencePane()" in assistant
    assert 'pane.id === "workflows"' in assistant
    assert 'pane.id === "approvals"' in assistant
    assert 'pane.id === "conversation"' in assistant


def test_health_isf_intelligence_pane_cannot_mutate_operational_state() -> None:
    for forbidden in [
        "assign-driver",
        "reassign-driver",
        "accept-ride",
        "dropoff-complete",
        "arrived-pickup",
        "pickup-complete",
        "lifecycle-action",
        "force-expire-assignment",
        "/operations/dispatch-recovery",
        "/customer-requests",
        "method: \"POST\"",
        "method: \"PUT\"",
        "method: \"PATCH\"",
        "method: \"DELETE\"",
    ]:
        assert forbidden not in INTELLIGENCE_BLOCK, forbidden
    assert "does not create or modify rides" in PANE
    assert "read-only GET" in PANE or "read-only" in PANE
    assert "data-nova-health-isf-refresh" in PANE
    assert "data-nova-health-isf-assign" not in OPS_JS
    assert "user_id=" not in READ_SOURCES


def test_unauthenticated_health_isf_intelligence_reads_are_blocked(client: TestClient) -> None:
    dashboard = client.get("/api/health-isf/dashboard")
    queue = client.get("/api/health-isf/dispatch/queue", params={"limit": 80, "read_only": True})
    rides = client.get("/api/health-isf/rides", params={"limit": 80, "active_only": True})
    command_center = client.get("/api/health-isf/operations/command-center")
    nova_intel = client.get("/api/nova/intelligence")
    summary = client.get("/api/health-isf/intelligence/summary")
    assert dashboard.status_code == 401, dashboard.text
    assert queue.status_code == 401, queue.text
    assert rides.status_code == 401, rides.text
    assert command_center.status_code == 401, command_center.text
    assert nova_intel.status_code == 401, nova_intel.text
    assert summary.status_code == 401, summary.text


def test_authenticated_health_isf_reads_are_identity_scoped_and_do_not_mutate(
    client: TestClient,
) -> None:
    admin = _login(client, "admin@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")
    rider = _login(client, "rider@amicor.local")
    admin_headers = _headers(admin["access_token"])
    dispatcher_headers = _headers(dispatcher["access_token"])
    rider_headers = _headers(rider["access_token"])
    assert admin["user_id"] != dispatcher["user_id"]
    assert admin["user_id"] != rider["user_id"]

    before = client.get("/api/health-isf/dashboard", headers=admin_headers)
    assert before.status_code == 200, before.text
    before_metrics = before.json()

    dashboard = client.get("/api/health-isf/dashboard", headers=admin_headers)
    queue = client.get(
        "/api/health-isf/dispatch/queue",
        headers=admin_headers,
        params={"limit": 80, "read_only": True},
    )
    active_rides = client.get(
        "/api/health-isf/rides",
        headers=admin_headers,
        params={"limit": 80, "active_only": True, "exclude_test": True},
    )
    completed = client.get(
        "/api/health-isf/rides",
        headers=admin_headers,
        params={"limit": 40, "history_only": True, "exclude_test": True},
    )
    command_center = client.get("/api/health-isf/operations/command-center", headers=admin_headers)
    alerts = client.get("/api/health-isf/operations/alerts", headers=admin_headers)
    billing = client.get(
        "/api/health-isf/operations/billing-handoffs",
        headers=admin_headers,
        params={"limit": 40},
    )
    schedules = client.get(
        "/api/health-isf/recurring/schedules",
        headers=admin_headers,
        params={"active_only": True, "limit": 40},
    )
    map_preview = client.get("/api/health-isf/operations/map-preview", headers=admin_headers)
    summary = client.get("/api/health-isf/intelligence/summary", headers=admin_headers)
    nova_intel = client.get("/api/nova/intelligence", headers=admin_headers)

    assert dashboard.status_code == 200, dashboard.text
    assert queue.status_code == 200, queue.text
    assert active_rides.status_code == 200, active_rides.text
    assert completed.status_code == 200, completed.text
    assert command_center.status_code == 200, command_center.text
    assert alerts.status_code == 200, alerts.text
    assert billing.status_code == 200, billing.text
    assert schedules.status_code == 200, schedules.text
    assert map_preview.status_code == 200, map_preview.text
    assert summary.status_code == 200, summary.text
    assert nova_intel.status_code == 200, nova_intel.text
    assert "pending_rides" in dashboard.json()
    assert "available_drivers" in dashboard.json()
    assert isinstance(queue.json(), list)
    assert command_center.json().get("safety", {}).get("execution_disabled") is True
    assert map_preview.json().get("safety", {}).get("preview_only") is True
    assert "summary" in nova_intel.json() or "composite_score" in nova_intel.json()

    after = client.get("/api/health-isf/dashboard", headers=admin_headers)
    assert after.status_code == 200, after.text
    after_metrics = after.json()
    assert after_metrics.get("pending_rides") == before_metrics.get("pending_rides")
    assert after_metrics.get("assigned_rides") == before_metrics.get("assigned_rides")
    assert after_metrics.get("active_rides") == before_metrics.get("active_rides")
    assert after_metrics.get("completed_rides") == before_metrics.get("completed_rides")

    foreign = client.get(
        "/api/health-isf/dashboard",
        headers=dispatcher_headers,
        params={"organization_id": "foreign-org-phase2j"},
    )
    assert foreign.status_code == 403, foreign.text

    rider_nova = client.get("/api/nova/intelligence", headers=rider_headers)
    assert rider_nova.status_code == 403, rider_nova.text

    spoof_create = client.post(
        "/api/health-isf/rides",
        headers=rider_headers,
        json={
            "user_id": admin["user_id"],
            "passenger_name": "Phase 2J spoof",
            "passenger_phone": "555-0100",
            "pickup_address": "1 Test St",
            "dropoff_address": "2 Test St",
            "service_type": "ambulatory",
        },
    )
    assert spoof_create.status_code in {401, 403, 404, 422}, spoof_create.text

    assign = client.post(
        "/api/health-isf/dispatcher/customer-requests/not-a-real-request/assign-driver",
        headers=admin_headers,
        json={"driver_id": "spoof"},
    )
    assert assign.status_code in {400, 403, 404, 422}, assign.text


def test_empty_and_error_states_are_rendered_in_health_isf_intelligence_pane() -> None:
    assert 'id="nova-health-isf-empty"' in PANE
    assert "No authorized Health ISF operational intelligence is available" in PANE
    assert "Sign in to view Health ISF intelligence" in PANE
    assert 'id="nova-health-isf-error"' in PANE
    assert "Sign in required to load Health ISF intelligence" in OPS_JS
    assert "Unsupported / not invented" in PANE
    assert "does not create or modify rides" in PANE


def test_previous_nova_panes_remain_intact_and_workspace_stays_available() -> None:
    client = TestClient(app)
    for path in ["/app", "/app/ai-assistant", "/workspace"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} -> {response.status_code}"

    assert "function renderNovaConversationPane()" in OPS_JS
    assert "function renderNovaVoicePane()" in OPS_JS
    assert "function renderNovaFilesPane()" in OPS_JS
    assert "function renderNovaMemoryPane()" in OPS_JS
    assert "function renderNovaToolsPane()" in OPS_JS
    assert "function renderNovaApprovalsPane()" in OPS_JS
    assert "function renderNovaWorkflowsPane()" in OPS_JS
    assert "function handleIntentConfirmation" in OPS_JS
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
        ("health-isf", "Live"),
    ]:
        definition = OPS_JS.split('id: "' + pane_id + '"', 1)[1][:500]
        assert kicker in definition, pane_id
    assert "kicker: \"Later\"" not in OPS_JS
    assert "health-isf live" in OPS_JS
