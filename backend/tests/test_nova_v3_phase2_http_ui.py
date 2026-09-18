"""Owner V3 lab HTTP surfaces for Phase 2."""
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


def test_phase2_lab_panes_and_actions(client: TestClient) -> None:
    for label in (
        "OPPORTUNITIES",
        "CLIENTS",
        "APPLICATIONS",
        "ENGAGEMENTS",
        "TASKS",
        "DELIVERABLES",
        "APPROVALS",
        "COMMUNICATIONS",
        "INVOICES",
        "PAYMENTS",
        "WORKERS",
        "CONNECTORS",
        "ALERTS",
        "AUDIT",
        "approve opportunity",
        "mock submit",
        "record synthetic partial payment",
    ):
        assert label.lower() in LAB_HTML.lower() or label in LAB_HTML
    assert "/api/nova/v3/lab/action" in LAB_JS
    page = client.get("/nova/v3-lab")
    assert page.status_code == 200
    headers = _headers(client)
    ingest = client.post("/api/nova/v3/ingest", headers=headers, json={"provider_id": "synthetic_job_board"})
    assert ingest.status_code == 200, ingest.text
    opportunity_id = ingest.json()["created"][0]["opportunity_id"]
    rejected = client.post(
        "/api/nova/v3/lab/action",
        headers=headers,
        json={"action": "reject_opportunity", "payload": {"opportunity_id": opportunity_id}},
    )
    assert rejected.status_code == 200, rejected.text
    lab = client.get("/api/nova/v3/lab", headers=headers)
    assert lab.status_code == 200
    assert lab.json()["engagements"] == []
    assert "approvals" in lab.json()
    flags = client.get("/api/nova/v3/guardrails", headers=headers)
    assert flags.json()["REAL_CONNECTORS"] is False
    assert flags.json()["REAL_WEBHOOK_PUBLIC_ENDPOINT"] is False
