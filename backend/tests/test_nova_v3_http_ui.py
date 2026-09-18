"""Nova V3 HTTP lab routes and owner UI."""
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


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_v3_lab_page_and_guardrails(client: TestClient) -> None:
    page = client.get("/nova/v3-lab")
    assert page.status_code == 200
    assert "OPPORTUNITIES" in LAB_HTML
    assert "APPLICATIONS" in LAB_HTML
    assert "CLIENTS" in LAB_HTML
    assert "ACTIVE WORK" in LAB_HTML
    assert "DELIVERABLES" in LAB_HTML
    assert "INVOICES" in LAB_HTML
    assert "PAYMENTS" in LAB_HTML
    assert "WORKERS" in LAB_HTML
    assert "CONNECTORS" in LAB_HTML
    assert "ALERTS" in LAB_HTML
    assert "AUDIT" in LAB_HTML
    assert "/api/nova/v3/lab" in LAB_JS
    headers = _headers(client)
    guards = client.get("/api/nova/v3/guardrails", headers=headers)
    assert guards.status_code == 200, guards.text
    assert guards.json()["LIVE_DISCOVERY_ENABLED"] is False
    assert guards.json()["INVOICE_SEND_ENABLED"] is False
    ingest = client.post("/api/nova/v3/ingest", headers=headers, json={"provider_id": "synthetic_job_board"})
    assert ingest.status_code == 200, ingest.text
    assert ingest.json()["created"][0]["classification"] == "NOVA_CAN_PERFORM"
    lab = client.get("/api/nova/v3/lab", headers=headers)
    assert lab.status_code == 200
    assert lab.json()["opportunities"]
    failed = client.post("/api/nova/v3/ingest", headers=headers, json={"provider_id": "failed_connector"})
    assert failed.status_code == 409
    other = _headers(client, "staff@amicor.local")
    hidden = client.get("/api/nova/v3/opportunities", headers=other)
    assert hidden.status_code == 200
    assert hidden.json() == []
