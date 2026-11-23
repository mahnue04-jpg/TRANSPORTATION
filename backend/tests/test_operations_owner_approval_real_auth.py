"""Real backend JWT/session smoke tests for the private Operations approval route.

Uses the existing app, auth schema, and signed seed-user tokens. The endpoint
remains disabled; no hosted DB, Stripe credentials, or artifact delivery used.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.db.session import engine
from app.main import app

PATH = "/api/nova/work/operations/subscription-approvals/decision"
SYNTHETIC = {
    "engagement_id": "eng_synthetic",
    "task_id": "task_synthetic",
    "lead_id": "lead_synthetic",
    "task_fingerprint": "a" * 64,
    "decision": "APPROVED",
}


@pytest.fixture(scope="module")
def client():
    ensure_auth_schema()
    seed_default_users()
    ensure_work_revenue_schema(engine)
    return TestClient(app)


def _login(client, email):
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_signed_out_denied_by_real_app_auth(client, monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_SUBSCRIPTION_OWNER_API_STAGING_ENABLED", raising=False)
    response = client.post(PATH, json=SYNTHETIC)
    assert response.status_code == 401, response.text


def test_real_owner_login_cannot_bypass_disabled_feature(client, monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_SUBSCRIPTION_OWNER_API_STAGING_ENABLED", raising=False)
    monkeypatch.setenv("NOVA_V3_OWNER_EMAILS", "dispatcher@amicor.local")
    headers = _login(client, "dispatcher@amicor.local")
    response = client.post(PATH, headers=headers, json=SYNTHETIC)
    assert response.status_code == 503, response.text
    assert "disabled" in response.text.lower()


def test_real_authenticated_nonowner_denied_by_work_router(client, monkeypatch):
    monkeypatch.setenv("NOVA_V3_OWNER_EMAILS", "dispatcher@amicor.local")
    headers = _login(client, "staff@amicor.local")
    response = client.post(PATH, headers=headers, json=SYNTHETIC)
    assert response.status_code == 403, response.text


def test_invalid_session_token_denied(client):
    response = client.post(
        PATH, headers={"Authorization": "Bearer invalid-synthetic-token"},
        json=SYNTHETIC,
    )
    assert response.status_code == 401, response.text
