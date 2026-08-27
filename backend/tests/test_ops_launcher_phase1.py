from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")


def test_launcher_route_and_existing_app_routes_still_serve() -> None:
    client = TestClient(app)
    for path in [
        "/app",
        "/app/home",
        "/app/dashboard",
        "/app/dispatch",
        "/app/trips",
        "/app/riders",
        "/app/mobile",
        "/app/drivers",
        "/app/providers",
        "/app/vehicles",
        "/app/billing",
        "/app/analytics",
        "/app/alerts",
        "/app/ai-assistant",
        "/app/settings",
        "/app/system-health",
        "/app/operations/supervisor",
        "/app/operations/compliance",
        "/platform-ops/driver-onboarding-admin",
        "/workspace",
    ]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} -> {response.status_code}"

    home = client.get("/app")
    assert "ops-shell.js" in home.text
    assert 'data-route="home"' in home.text
    assert 'href="/app"' in home.text


def test_launcher_reuses_existing_authoritative_routes() -> None:
    assert '"home": { path: APP_BASE_PATH' in OPS_JS
    assert "function renderOperationsHome()" in OPS_JS
    for fragment in [
        'APP_BASE_PATH + "/dashboard"',
        'APP_BASE_PATH + "/riders"',
        'APP_BASE_PATH + "/dispatch"',
        'APP_BASE_PATH + "/trips"',
        'APP_BASE_PATH + "/mobile"',
        'APP_BASE_PATH + "/drivers"',
        'APP_BASE_PATH + "/providers"',
        'APP_BASE_PATH + "/vehicles"',
        'APP_BASE_PATH + "/billing"',
        'APP_BASE_PATH + "/analytics"',
        'APP_BASE_PATH + "/ai-assistant"',
        'APP_BASE_PATH + "/alerts"',
        'APP_BASE_PATH + "/system-health"',
        'APP_BASE_PATH + "/settings"',
        'APP_BASE_PATH + "/operations/supervisor"',
        'APP_BASE_PATH + "/operations/compliance"',
        'APP_BASE_PATH + "/operations/medical-coordinator"',
        'APP_BASE_PATH + "/operations/driver-support"',
        "/platform-ops/driver-onboarding-admin",
        "/workspace#/health-isf/grant",
    ]:
        assert fragment in OPS_JS, fragment

    assert "LAUNCHER_CORE_TILES" in OPS_JS
    assert 'title: "Driver Mobile"' in OPS_JS
    assert 'title: "Drivers / Fleet Desk"' in OPS_JS
    assert 'title: "AI Assistant / Amicor Nova"' in OPS_JS
    assert "getSessionAuthorizedRoles" in OPS_JS
    assert "The role selector is a view lens only" in OPS_JS


def test_launcher_nav_home_control_exists_without_replacing_apps() -> None:
    assert '<a href="/app" data-route="home">Home</a>' in OPS_HTML
    assert 'href="/app/dispatch" data-route="dispatch"' in OPS_HTML
    assert 'href="/app/mobile" data-route="mobile"' in OPS_HTML
    assert 'href="/app/riders" data-route="riders"' in OPS_HTML
    assert 'href="/app/billing" data-route="billing"' in OPS_HTML
    assert 'href="/app/ai-assistant" data-route="ai-assistant"' in OPS_HTML
    assert 'href="/app/providers" data-route="providers"' in OPS_HTML
    assert "nova-backend" not in OPS_HTML
    assert "frontend/src" not in OPS_JS
    assert "function renderDispatch()" in OPS_JS
    assert "function renderBilling()" in OPS_JS
    assert "function renderAssistant()" in OPS_JS
    assert "function renderMobile()" in OPS_JS
    assert "function renderRidersRoute()" in OPS_JS


def test_role_access_does_not_invent_missing_shell_roles() -> None:
    assert 'staff: [' not in OPS_JS.split("var ROLE_ACCESS = {", 1)[1].split("};", 1)[0]
    assert "analytics_readonly" not in OPS_JS.split("var ROLE_ACCESS = {", 1)[1].split("};", 1)[0]
    rider_block = OPS_JS.split('rider: ["home"', 1)[1].split("],", 1)[0]
    assert "settings" not in rider_block
    assert "dispatch" not in rider_block
    driver_block = OPS_JS.split('driver: ["home"', 1)[1].split("],", 1)[0]
    assert "settings" not in driver_block
    assert "dispatch" not in driver_block
    dispatcher_block = OPS_JS.split('dispatcher: ["home"', 1)[1].split("],", 1)[0]
    assert "settings" not in dispatcher_block
