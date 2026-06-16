from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.memory import NovaMemoryStore
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_nova_status_endpoint(client: TestClient):
    auth = _login(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.get("/api/nova/status", headers=headers)
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["status"] == "ok"
    assert "current_platform_phase" in payload
    assert "next_recommended_action" in payload
    assert "memory" in payload


def test_nova_next_step_endpoint(client: TestClient):
    auth = _login(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.post(
        "/api/nova/next-step",
        headers=headers,
        json={
            "mode": "founder_advisor",
            "goal": "Prepare enterprise dispatch launch checklist",
        },
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["mode"] == "founder_advisor"
    assert payload["next_recommended_step"]
    assert isinstance(payload["checklist"], list)


def test_nova_health_isf_context_endpoint(client: TestClient):
    auth = _login(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.get("/api/nova/context", headers=headers)
    assert response.status_code == 200, response.text

    payload = response.json()
    summary = payload["health_isf_summary"]
    assert "rides_total" in summary
    assert "drivers_total" in summary
    assert "providers_total" in summary
    assert "dispatch_health" in summary
    assert "workflow_health" in summary
    assert "enterprise_readiness" in summary


def test_nova_memory_read_write(tmp_path: Path):
    store = NovaMemoryStore(path=str(tmp_path / "nova_memory_test.json"))

    organization_id = "org-memory-test"
    first = store.read(organization_id)
    assert first["current_build_phase"]

    updated = store.write(
        organization_id,
        {
            "current_build_phase": "phase-2",
            "active_module": "nova",
            "next_recommended_step": "Execute founder readiness sprint",
            "founder_priorities": ["tenant safety", "dispatch reliability"],
        },
    )

    assert updated["current_build_phase"] == "phase-2"
    assert updated["active_module"] == "nova"
    assert "dispatch reliability" in updated["founder_priorities"]

    second = store.read(organization_id)
    assert second["next_recommended_step"] == "Execute founder readiness sprint"


def test_nova_review_report_endpoint(client: TestClient):
    auth = _login(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.post(
        "/api/nova/review-report",
        headers=headers,
        json={
            "mode": "engineering_director",
            "report_title": "AI Dispatch Integration Report",
            "report_text": (
                "Validation completed with tenant-safe endpoints, RBAC checks, and resilience replay. "
                "Manual test notes included. TODO: expand integration automation."
            ),
        },
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["report_title"] == "AI Dispatch Integration Report"
    assert isinstance(payload["strengths"], list)
    assert isinstance(payload["risks"], list)
    assert isinstance(payload["recommended_actions"], list)
