"""Nova Core Phase 1: Nova Home shell. Does not unfreeze Freight, Delivery, or Health."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
HOME_HTML = (STATIC / "nova-home" / "index.html").read_text(encoding="utf-8")
HOME_JS = (STATIC / "nova-home" / "home.js").read_text(encoding="utf-8")
HOME_CSS = (STATIC / "nova-home" / "home.css").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
FREIGHT_HTML = (STATIC / "nova-freight" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, email)['access_token']}"}


def _counts() -> dict[str, int]:
    from app.core.nova.freight.models import NovaFreightShipment
    from app.modules.health_isf.models import HealthISFRide
    from app.modules.platform_ops.models import PlatformDriverOnboardingApplication

    with SessionLocal() as db:
        return {
            "freight": db.query(NovaFreightShipment).count(),
            "health_rides": db.query(HealthISFRide).count(),
            "driver_apps": db.query(PlatformDriverOnboardingApplication).count(),
            "driver_001": db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.internal_driver_number == "DRV-001")
            .count(),
        }


def test_nova_home_route_loads(client: TestClient) -> None:
    for path in ("/nova", "/nova/", "/nova/home"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "AMICOR NOVA" in response.text
        assert "Mrs. Nova Brain" in response.text
        assert "Search the world, your work, or ask Nova." in response.text
        assert "Let's make today count." in response.text
        assert "ops-shell.js" not in response.text
        assert 'src="/static/nova-home/home.js"' in response.text


def test_nova_home_signed_out_does_not_expose_protected_brain(client: TestClient) -> None:
    page = client.get("/nova")
    assert page.status_code == 200
    assert "Sign in to ask Mrs. Nova Brain." in page.text
    denied = client.post("/api/nova/ask", json={"question": "What should I do next?", "mode": "founder_advisor"})
    assert denied.status_code == 401
    status = client.get("/api/nova/status")
    assert status.status_code == 401


def test_nova_home_authenticated_mrs_nova_brain(client: TestClient) -> None:
    headers = _headers(client)
    status = client.get("/api/nova/status", headers=headers)
    assert status.status_code == 200
    asked = client.post(
        "/api/nova/ask",
        headers=headers,
        json={"question": "Summarize today's operating priorities.", "mode": "founder_advisor"},
    )
    assert asked.status_code == 200, asked.text
    payload = asked.json()
    assert payload["mode"] == "founder_advisor"
    assert payload["answer"]
    assert "/api/nova/ask" in HOME_JS
    assert "Mrs. Nova Brain" in HOME_HTML
    assert "Mr. Nova" not in HOME_HTML
    assert "second assistant" not in HOME_JS.lower()


def test_nova_home_destination_links() -> None:
    assert 'href="/nova/today" data-destination="today"' in HOME_HTML
    assert 'href="/nova/workspace" data-destination="workspace"' in HOME_HTML
    assert 'href="#web-search" data-destination="search"' in HOME_HTML
    assert 'href="/nova/workspace#files" data-destination="files"' in HOME_HTML
    assert 'href="/workspace" data-destination="voice"' in HOME_HTML
    assert 'href="/workspace" data-destination="tools"' in HOME_HTML
    assert 'href="/workspace" data-destination="health"' in HOME_HTML
    assert 'href="/app" data-destination="delivery"' in HOME_HTML
    assert 'href="/nova/freight" data-destination="freight"' in HOME_HTML
    assert 'href="/nova/communications" data-destination="communications"' in HOME_HTML
    assert 'href="/nova/government" data-destination="government"' in HOME_HTML
    assert 'href="/nova/business" data-destination="business"' in HOME_HTML
    assert 'href="/nova/payments/readiness" data-destination="payments-readiness"' in HOME_HTML
    assert 'data-later="true"' not in HOME_HTML
    assert HOME_HTML.count("Coming later") == 0


def test_nova_home_today_tile_is_additive_and_safe() -> None:
    assert 'data-today-tile="true"' in HOME_HTML
    assert "Today / Command Center" in HOME_HTML
    assert "Open Today" in HOME_HTML
    assert "today-attention-count" in HOME_HTML
    assert HOME_HTML.count('data-destination="workspace"') == 1
    assert HOME_HTML.count('href="/app" data-destination="delivery"') == 1
    assert "/api/nova/today/dashboard" in HOME_JS
    assert "refreshTodayCount" in HOME_JS
    count_fn = HOME_JS.split("async function refreshTodayCount")[1].split("async function refreshBrain")[0]
    assert "attention_now" in count_fn
    assert ".title" not in count_fn
    assert "detail" not in count_fn
    assert "nova_v2_command_actions" not in HOME_JS
    assert "min-height: 44px" in HOME_CSS
    assert "@media (max-width: 720px)" in HOME_CSS


def test_nova_home_today_count_auth_fallback_and_isolation(client: TestClient) -> None:
    page = client.get("/nova")
    assert page.status_code == 200
    assert 'href="/nova/today"' in page.text
    assert "Open the Command Center." in page.text
    assert client.get("/api/nova/today/dashboard").status_code == 401

    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    overdue = date.today().isoformat()
    created = client.post(
        "/api/nova/government/items",
        headers=owner,
        json={"title": "Home tile count license", "due_date": overdue, "status": "renewal_due"},
    )
    assert created.status_code == 200, created.text
    owner_dash = client.get("/api/nova/today/dashboard", headers=owner)
    other_dash = client.get("/api/nova/today/dashboard", headers=other)
    assert owner_dash.status_code == 200
    assert other_dash.status_code == 200
    owner_count = len(owner_dash.json().get("attention_now") or [])
    other_ids = {row.get("source_ref_id") for row in other_dash.json().get("attention_now") or []}
    assert created.json()["item_id"] not in other_ids
    assert isinstance(owner_count, int)
    cross = client.get("/api/nova/today/dashboard", headers=owner, params={"organization_id": "org-not-the-caller"})
    assert cross.status_code == 403


def test_nova_home_search_handoff(client: TestClient) -> None:
    assert "/api/search" in HOME_JS
    assert "tavily" not in HOME_JS.lower()
    search = client.get("/api/search", params={"query": "AMICOR Nova", "max_results": 2})
    assert search.status_code == 200, search.text
    body = search.json()
    assert "status" in body
    assert "response" in body or "sources" in body


def test_nova_home_responsive_markup() -> None:
    assert 'name="viewport"' in HOME_HTML
    assert "width=device-width" in HOME_HTML
    assert "@media (max-width: 720px)" in HOME_CSS
    assert "@media (min-width: 1280px)" in HOME_CSS
    assert "@media (min-width: 1600px)" in HOME_CSS
    assert "hardware" not in HOME_JS.lower()
    assert "gpio" not in HOME_JS.lower()


def test_nova_home_product_isolation(client: TestClient) -> None:
    before = _counts()
    home = client.get("/nova")
    freight = client.get("/nova/freight")
    delivery = client.get("/app")
    health = client.get("/workspace")
    after = _counts()

    assert home.status_code == 200
    assert "AMICOR NOVA" in home.text
    assert "New Freight Request" not in home.text
    assert freight.status_code == 200
    assert "Freight / Logistics" in freight.text or "New Freight Request" in freight.text
    assert "Mrs. Nova Brain" not in FREIGHT_HTML or "nova-home" not in FREIGHT_HTML
    assert delivery.status_code == 200
    assert "AMICOR Delivery" in delivery.text
    assert "nova-home/home.js" not in delivery.text
    assert health.status_code == 200
    assert before == after
    assert "AMICOR Delivery" in OPS_HTML
    assert "nova-home" not in OPS_JS
    assert "nova-home" not in OPS_HTML


def test_nova_home_does_not_touch_driver_001() -> None:
    bundle = HOME_HTML + HOME_JS + HOME_CSS
    assert "Driver 001" not in bundle
    assert "DRV-001" not in bundle
    assert "driver-apply" not in bundle


def test_nova_home_stripe_remains_test_only() -> None:
    bundle = HOME_HTML + HOME_JS + HOME_CSS
    assert "sk_live" not in bundle
    assert "pk_live" not in bundle
    assert "rk_live" not in bundle
    assert "stripe.com" not in bundle.lower()
    assert "Stripe LIVE" not in bundle


def test_nova_home_does_not_host_under_delivery() -> None:
    assert "/app/nova" not in HOME_HTML
    assert "ops-shell" not in HOME_HTML
    assert "nova-home" not in OPS_HTML
    assert "nova-home" not in OPS_JS
    assert 'href="/app"' in HOME_HTML
    assert 'href="/workspace"' in HOME_HTML
    assert 'href="/nova/freight"' in HOME_HTML
