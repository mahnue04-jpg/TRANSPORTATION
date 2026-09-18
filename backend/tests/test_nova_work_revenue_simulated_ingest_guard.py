"""Production simulated-ingest guard must match health environment detection."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.work_revenue.flags import engine_guardrails
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.db.session import engine
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_work_revenue_schema(engine)
    return TestClient(app)


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _opportunity_ids(client: TestClient, headers: dict[str, str]) -> set[str]:
    listed = client.get("/api/nova/work/opportunities", headers=headers, params={"limit": 200})
    assert listed.status_code == 200, listed.text
    return {item["opportunity_id"] for item in listed.json()}


def _clear_ingest_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUNTIME_ENVIRONMENT", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("AMICOR_ENVIRONMENT", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)


def test_production_amicor_environment_blocks_and_creates_zero(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    headers = _headers(client)
    before = _opportunity_ids(client, headers)
    _clear_ingest_env(monkeypatch)
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    blocked = client.post("/api/nova/work/ingest/simulated", headers=headers)
    assert blocked.status_code == 403, blocked.text
    after = _opportunity_ids(client, headers)
    assert after == before


def test_production_inferred_from_https_and_postgres_blocks(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    headers = _headers(client)
    before = _opportunity_ids(client, headers)
    _clear_ingest_env(monkeypatch)
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("AMICOR_PUBLIC_URL", "https://amicor-health-isf-py.onrender.com")
    monkeypatch.setenv("DATABASE_URL", "postgresql://amicor:amicor@localhost:5432/amicor")
    blocked = client.post("/api/nova/work/ingest/simulated", headers=headers)
    assert blocked.status_code == 403, blocked.text
    after = _opportunity_ids(client, headers)
    assert after == before


def test_stale_runtime_environment_env_cannot_unblock_production(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    headers = _headers(client)
    before = _opportunity_ids(client, headers)
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("RUNTIME_ENVIRONMENT", "development")
    monkeypatch.setenv("APP_ENV", "development")
    blocked = client.post("/api/nova/work/ingest/simulated", headers=headers)
    assert blocked.status_code == 403, blocked.text
    assert _opportunity_ids(client, headers) == before


def test_non_production_simulated_ingest_still_works(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    headers = _headers(client)
    _clear_ingest_env(monkeypatch)
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")
    monkeypatch.setenv("AMICOR_PUBLIC_URL", "http://127.0.0.1:8010")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    allowed = client.post("/api/nova/work/ingest/simulated", headers=headers)
    assert allowed.status_code == 200, allowed.text
    rows = allowed.json()
    assert isinstance(rows, list)
    listed = client.get("/api/nova/work/opportunities", headers=headers, params={"limit": 200})
    assert listed.status_code == 200
    simulated = [item for item in listed.json() if (item.get("source_type") or item.get("source")) == "simulated"]
    assert len(rows) >= 1 or len(simulated) >= 1


def test_tenant_isolation_and_live_flags_unchanged(client: TestClient) -> None:
    owner = _headers(client)
    other = _headers(client, "staff@amicor.local")
    created = client.post(
        "/api/nova/work/opportunities",
        headers=owner,
        json={
            "company_name": "Guard Isolation Co",
            "opportunity_title": "Remote isolation check",
            "description": "Remote bookkeeping",
        },
    )
    assert created.status_code == 200, created.text
    hidden = client.get("/api/nova/work/opportunities", headers=other)
    assert hidden.status_code == 200
    assert all(item.get("opportunity_id") != created.json()["opportunity_id"] for item in hidden.json())
    foreign = client.get(
        "/api/nova/work/opportunities",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert foreign.status_code == 403
    guards = engine_guardrails()
    assert guards["LIVE_DISCOVERY_ENABLED"] is False
    assert guards["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guards["FINANCIAL_ACTIONS_ENABLED"] is False
    assert guards["AUTONOMOUS_CLIENT_CONTACT_ENABLED"] is False
    assert guards["REPORT_SEND_ENABLED"] is False
    assert guards["INVOICE_SEND_ENABLED"] is False
    submit = client.post("/api/nova/work/applications/NWAPP-GUARD/submit", headers=owner)
    assert submit.status_code == 409
    send_report = client.post("/api/nova/work/reports/NWR-GUARD/send", headers=owner)
    assert send_report.status_code == 409
    send_invoice = client.post("/api/nova/work/invoice-support/NWIS-GUARD/send", headers=owner)
    assert send_invoice.status_code == 409
