"""HTTP transport checks of private staging approval route.

Uses synthetic FastAPI auth dependencies and a fake DB. Does not assert the
actual application's authentication implementation; those integration tests
must run in a full backend environment before hosted deployment.
"""
import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def harness(monkeypatch):
    fake_auth = types.ModuleType("app.auth")
    fake_auth.UserContext = type("UserContext", (), {})
    fake_auth.get_current_user_context = lambda: None
    fake_session = types.ModuleType("app.db.session")
    fake_session.get_db = lambda: None
    monkeypatch.setitem(sys.modules, "app.auth", fake_auth)
    monkeypatch.setitem(sys.modules, "app.db.session", fake_session)
    name = "app.core.nova.work_revenue.operations_owner_approval_router"
    sys.modules.pop(name, None)
    api = importlib.import_module(name)

    def require_synthetic_owner(x_synthetic_token: str | None = Header(None)):
        if x_synthetic_token != "synthetic-owner-token":
            raise HTTPException(401, "Authentication required")
        return SimpleNamespace(user_id="owner_synthetic",
                               organization_id="org_synthetic", role="admin")

    app = FastAPI()
    # Simulates the parent Work & Revenue router guards, NOT production JWT.
    app.include_router(api.router, prefix="/api/nova/work",
                       dependencies=[Depends(require_synthetic_owner)])
    app.dependency_overrides[api.get_current_user_context] = require_synthetic_owner
    app.dependency_overrides[api.get_db] = lambda: Mock()
    for key, value in (
        ("APP_ENV", "staging"), ("AMICOR_ENVIRONMENT", "staging"),
        ("NOVA_OPERATIONS_SUBSCRIPTION_OWNER_API_STAGING_ENABLED", "true"),
        ("NOVA_STRIPE_LIVE_ENABLED", "false"),
        ("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false"),
    ):
        monkeypatch.setenv(key, value)
    return api, TestClient(app)


def payload(decision="APPROVED"):
    return {
        "engagement_id": "eng_synthetic", "task_id": "task_synthetic",
        "lead_id": "lead_synthetic", "task_fingerprint": "a"*64,
        "decision": decision,
    }


URL = "/api/nova/work/operations/subscription-approvals/decision"


def test_signed_out_http_request_denied_before_write(harness):
    api, client = harness
    with patch.object(api, "record_staging_owner_scope_decision") as write:
        response = client.post(URL, json=payload())
        assert response.status_code == 401
        write.assert_not_called()


@pytest.mark.parametrize("decision", ["APPROVED", "REJECTED", "REVOKED"])
def test_signed_in_owner_decision_only_no_delivery(harness, decision):
    api, client = harness
    with patch.object(api, "record_staging_owner_scope_decision") as write:
        write.return_value = {
            "event_id": "synthetic_event", "task_id": "task_synthetic",
            "decision": decision, "executed": False,
        }
        response = client.post(URL, headers={"x-synthetic-token": "synthetic-owner-token"},
                               json=payload(decision))
        assert response.status_code == 200
        assert response.json()["decision"] == decision
        assert response.json()["executed"] is False
        assert response.json()["delivered"] is False
        assert write.call_count == 1


def test_disabled_endpoint_returns_503_and_never_writes(harness, monkeypatch):
    api, client = harness
    monkeypatch.delenv("NOVA_OPERATIONS_SUBSCRIPTION_OWNER_API_STAGING_ENABLED", raising=False)
    with patch.object(api, "record_staging_owner_scope_decision") as write:
        response = client.post(URL, headers={"x-synthetic-token": "synthetic-owner-token"},
                               json=payload())
        assert response.status_code == 503
        write.assert_not_called()


@pytest.mark.parametrize("invalid_payload", [
    {**payload(), "decision": "SEND_TO_CUSTOMER"},
    {**payload(), "task_fingerprint": "wrong"},
    {**payload(), "engagement_id": ""},
])
def test_invalid_payload_rejected_before_write(harness, invalid_payload):
    api, client = harness
    with patch.object(api, "record_staging_owner_scope_decision") as write:
        response = client.post(URL, headers={"x-synthetic-token": "synthetic-owner-token"},
                               json=invalid_payload)
        assert response.status_code == 422
        write.assert_not_called()


def test_live_sales_flags_block_requests(harness, monkeypatch):
    api, client = harness
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "true")
    with patch.object(api, "record_staging_owner_scope_decision") as write:
        response = client.post(URL, headers={"x-synthetic-token": "synthetic-owner-token"},
                               json=payload())
        assert response.status_code == 503
        write.assert_not_called()
