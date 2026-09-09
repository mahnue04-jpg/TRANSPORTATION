"""Nova Core V1 Phase 6: launch hardening, master verification, and freeze gates."""
from __future__ import annotations

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
WS_HTML = (STATIC / "nova-workspace" / "index.html").read_text(encoding="utf-8")
WS_JS = (STATIC / "nova-workspace" / "workspace.js").read_text(encoding="utf-8")
WS_CSS = (STATIC / "nova-workspace" / "workspace.css").read_text(encoding="utf-8")
COMMS_HTML = (STATIC / "nova-communications" / "index.html").read_text(encoding="utf-8")
COMMS_JS = (STATIC / "nova-communications" / "communications.js").read_text(encoding="utf-8")
COMMS_CSS = (STATIC / "nova-communications" / "communications.css").read_text(encoding="utf-8")
GOV_HTML = (STATIC / "nova-government" / "index.html").read_text(encoding="utf-8")
GOV_JS = (STATIC / "nova-government" / "government.js").read_text(encoding="utf-8")
GOV_CSS = (STATIC / "nova-government" / "government.css").read_text(encoding="utf-8")
BIZ_HTML = (STATIC / "nova-business" / "index.html").read_text(encoding="utf-8")
BIZ_JS = (STATIC / "nova-business" / "business.js").read_text(encoding="utf-8")
BIZ_CSS = (STATIC / "nova-business" / "business.css").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
HEALTH_HTML = (STATIC / "index.html").read_text(encoding="utf-8")
FREIGHT_HTML = (STATIC / "nova-freight" / "index.html").read_text(encoding="utf-8")
CORE_HTML = HOME_HTML + WS_HTML + COMMS_HTML + GOV_HTML + BIZ_HTML
CORE_JS = HOME_JS + WS_JS + COMMS_JS + GOV_JS + BIZ_JS
CORE_CSS = HOME_CSS + WS_CSS + COMMS_CSS + GOV_CSS + BIZ_CSS


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


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


def test_nova_core_v1_routes_and_home_entrance(client: TestClient) -> None:
    for path, needle in (
        ("/nova", "AMICOR NOVA"),
        ("/nova/workspace", "Nova Workspace"),
        ("/nova/communications", "Communications"),
        ("/nova/government", "Government Services"),
        ("/nova/business", "Business OS"),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert needle in response.text
        assert "Mrs. Nova Brain" in response.text
        assert "ops-shell.js" not in response.text
    home = client.get("/nova")
    assert 'href="/nova/workspace"' in home.text
    assert 'href="/nova/communications"' in home.text
    assert 'href="/nova/government"' in home.text
    assert 'href="/nova/business"' in home.text
    health = client.get("/workspace")
    assert health.status_code == 200
    assert "Health ISF Workspace" in health.text
    assert "/nova/business" not in health.text
    freight = client.get("/nova/freight")
    assert freight.status_code == 200
    assert "New Freight Request" in freight.text or "Freight / Logistics" in freight.text
    assert "nova-home" not in FREIGHT_HTML
    assert "nova-business" not in OPS_HTML
    assert "nova-government" not in OPS_JS


def test_nova_core_v1_single_brain_and_trust_labels() -> None:
    assert CORE_HTML.count("Mrs. Nova Brain") >= 5
    assert "Mr. Nova Brain" not in CORE_HTML
    assert "second assistant" not in CORE_JS.lower()
    assert "competing intelligence" not in CORE_JS.lower()
    for html in (HOME_HTML, WS_HTML, COMMS_HTML, GOV_HTML, BIZ_HTML):
        assert "VERIFIED DATA" in html
        assert "USER-SAVED INFORMATION" in html
        assert "AI SUGGESTION" in html
    assert "OFFICIAL SOURCE" in GOV_HTML
    assert "CONFIRMED IN WRITING" in GOV_HTML
    assert "EXPIRED OR SUPERSEDED" in GOV_HTML
    assert "official government ruling" in GOV_HTML
    assert "NOT Accounting" in BIZ_HTML
    assert "/api/nova/ask" in HOME_JS
    assert "/api/nova/workspace/ask" in WS_JS
    assert "/api/nova/communications/ask" in COMMS_JS
    assert "/api/nova/government/ask" in GOV_JS
    assert "/api/nova/business/ask" in BIZ_JS


def test_nova_core_v1_navigation_mesh() -> None:
    assert 'href="/nova/business"' in HOME_HTML
    assert 'href="/nova/government"' in HOME_HTML
    for html in (WS_HTML, COMMS_HTML, GOV_HTML, BIZ_HTML):
        assert 'href="/nova">Nova Home' in html
        assert 'href="/workspace">Health' in html
        assert 'href="/app">Delivery' in html
        assert 'href="/nova/freight">Freight' in html
    assert 'href="/nova/business">Business' in WS_HTML
    assert 'href="/nova/business">Business' in COMMS_HTML
    assert 'href="/nova/business">Business' in GOV_HTML
    assert 'href="/nova/government">Government' in BIZ_HTML
    assert 'href="/nova/communications">Communications' in BIZ_HTML


def test_nova_core_v1_recovery_and_security_ux() -> None:
    for js in (HOME_JS, WS_JS, COMMS_JS, GOV_JS, BIZ_JS):
        assert "Session expired. Sign in again." in js
        assert "Access denied." in js
        assert "Not found / unavailable." in js
        assert "Temporary system error." in js
        assert "Network error. Saved work was not changed." in js
        assert "sk_live" not in js
        assert "pk_live" not in js
        assert "client_secret" not in js
        assert "smtp_password" not in js
        assert "/api/email/send" not in js
        assert "hardware" not in js.lower()
        assert "gpio" not in js.lower()
    assert "/api/nova/communications/send" not in GOV_JS
    assert "/api/nova/communications/send" not in BIZ_JS
    assert "general ledger" not in BIZ_JS.lower()
    assert "chart of accounts" not in BIZ_HTML.lower()
    assert CORE_HTML.count("traceback") == 0


def test_nova_core_v1_responsive_breakpoints() -> None:
    for css in (HOME_CSS, WS_CSS, COMMS_CSS, GOV_CSS, BIZ_CSS):
        assert "@media (max-width: 720px)" in css
        assert "@media (min-width: 1280px)" in css
        assert "@media (min-width: 1600px)" in css
    for html in (HOME_HTML, WS_HTML, COMMS_HTML, GOV_HTML, BIZ_HTML):
        assert 'name="viewport"' in html
        assert "width=device-width" in html


def test_nova_core_v1_auth_isolation_and_safety(client: TestClient) -> None:
    assert client.get("/api/nova/status").status_code == 401
    assert client.get("/api/nova/workspace/dashboard").status_code == 401
    assert client.get("/api/nova/communications/dashboard").status_code == 401
    assert client.get("/api/nova/government/dashboard").status_code == 401
    assert client.get("/api/nova/business/dashboard").status_code == 401
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    created = client.post("/api/nova/business/customers", headers=owner, json={"name": "Freeze isolation customer"})
    assert created.status_code == 200
    hidden = client.get(f"/api/nova/business/customers/{created.json()['customer_id']}", headers=other)
    assert hidden.status_code == 404
    cross = client.get("/api/nova/business/dashboard", headers=owner, params={"organization_id": "org-not-the-caller"})
    assert cross.status_code == 403
    assert client.post("/api/nova/business/ledger", headers=owner).status_code == 403
    assert client.post("/api/nova/business/send", headers=owner).status_code == 403
    gov = client.post("/api/nova/government/items", headers=owner, json={"title": "Freeze isolation filing"})
    assert gov.status_code == 200
    assert client.post(f"/api/nova/government/items/{gov.json()['item_id']}/file", headers=owner).status_code == 403
    comms_send = client.post(
        "/api/nova/communications/send",
        headers=owner,
        json={"confirm_send": True, "to": ["noreply@example.com"], "subject": "nope", "body": "nope"},
    )
    assert comms_send.status_code == 403


def test_nova_core_v1_does_not_mutate_frozen_products(client: TestClient) -> None:
    before = _counts()
    headers = _headers(client)
    for path in ("/nova", "/nova/workspace", "/nova/communications", "/nova/government", "/nova/business", "/workspace", "/nova/freight", "/app"):
        client.get(path)
    client.get("/api/nova/status", headers=headers)
    after = _counts()
    assert before == after
    assert "Driver 001" not in CORE_HTML + CORE_JS
    assert "DRV-001" not in CORE_HTML + CORE_JS
    assert "Health ISF Workspace" in HEALTH_HTML
    assert "/nova/workspace" not in HEALTH_HTML
