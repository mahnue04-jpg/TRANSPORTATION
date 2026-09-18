"""Growth HTTP and owner lab panes."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.v3.kernel import reset_kernel
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
LAB_HTML = (ROOT / "static" / "nova-v3-lab" / "index.html").read_text(encoding="utf-8")
LAB_JS = (ROOT / "static" / "nova-v3-lab" / "lab.js").read_text(encoding="utf-8")


@pytest.fixture
def client() -> TestClient:
    reset_kernel()
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_growth_and_shield_lab_panes(client: TestClient) -> None:
    assert "GROWTH COMMAND CENTER" in LAB_HTML
    assert "SHIELD COMMAND CENTER" in LAB_HTML
    assert "NEW LEADS" in LAB_HTML
    assert "/api/nova/v3/growth/leads" in LAB_JS
    page = client.get("/nova/v3-lab")
    assert page.status_code == 200
    headers = _headers(client)
    created = client.post(
        "/api/nova/v3/growth/leads",
        headers=headers,
        json={
            "organization_name": "Harbor Bookkeeping",
            "contact_name": "Sam",
            "role_title": "Owner",
            "industry": "professional services",
            "geography": "remote",
            "email_placeholder": "sam@example-smb.test",
            "business_need": "administrative automation",
            "product_fit": "nova",
            "estimated_value": 299,
        },
    )
    assert created.status_code == 200, created.text
    dash = client.get("/api/nova/v3/growth/dashboard", headers=headers)
    assert dash.status_code == 200
    assert dash.json()["LEADS FOUND"] >= 1
    shield = client.get("/api/nova/v3/growth/shield", headers=headers)
    assert shield.status_code == 200
    lab = client.get("/api/nova/v3/lab", headers=headers)
    assert "growth" in lab.json()
    assert "shield" in lab.json()
    flags = client.get("/api/nova/v3/guardrails", headers=headers)
    assert flags.json()["REAL_OUTREACH_SEND"] is False
    assert flags.json()["LIVE_LEAD_DISCOVERY"] is False
