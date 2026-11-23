"""Isolated route transport checks; mocked owner, no Stripe or customer data."""
import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import Depends, FastAPI, Header, HTTPException
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
    module = importlib.import_module(name)

    def owner_dependency(x_synthetic_token: str | None = Header(None)):
        if x_synthetic_token != "owner-only-test":
            raise HTTPException(401, "Authentication required")
        return SimpleNamespace(user_id="synthetic_owner",
                               organization_id="synthetic_org", role="admin")

    app = FastAPI()
    app.include_router(module.router, prefix="/api/nova/work",
                       dependencies=[Depends(owner_dependency)])
    app.dependency_overrides[module.get_current_user_context] = owner_dependency
    app.dependency_overrides[module.get_db] = lambda: Mock()
    for key, value in (
        ("APP_ENV", "staging"), ("AMICOR_ENVIRONMENT", "staging"),
        ("NOVA_OPERATIONS_SUBSCRIPTION_RESERVATION_API_STAGING_ENABLED", "true"),
        ("NOVA_STRIPE_LIVE_ENABLED", "false"),
        ("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false"),
    ):
        monkeypatch.setenv(key, value)
    return module, TestClient(app)


URL = "/api/nova/work/operations/subscription-approvals/reserve"
BODY = dict(engagement_id="eng_synthetic", task_id="task_synthetic",
            lead_id="lead_synthetic", request_key="req-1", task_fingerprint="a"*64)
HEADER = {"x-synthetic-token": "owner-only-test"}


def test_signed_out_blocked_before_reservation(harness):
    module, client = harness
    with patch("app.core.nova.work_revenue.operations_authenticated_subscription_adapter.reserve_owner_approved_test_subscription_task") as write:
        assert client.post(URL, json=BODY).status_code == 401
        write.assert_not_called()


def test_disabled_api_blocks_owner(harness, monkeypatch):
    module, client = harness
    monkeypatch.delenv("NOVA_OPERATIONS_SUBSCRIPTION_RESERVATION_API_STAGING_ENABLED", raising=False)
    with patch("app.core.nova.work_revenue.operations_authenticated_subscription_adapter.reserve_owner_approved_test_subscription_task") as write:
        assert client.post(URL, headers=HEADER, json=BODY).status_code == 503
        write.assert_not_called()


def test_owner_reservation_never_delivers(harness):
    module, client = harness
    with patch("app.core.nova.work_revenue.operations_authenticated_subscription_adapter.reserve_owner_approved_test_subscription_task") as write:
        write.return_value = dict(reservation_id="synthetic", replayed=False, consumed=True)
        r = client.post(URL, headers=HEADER, json=BODY)
        assert r.status_code == 200, r.text
        assert r.json() == dict(reservation_id="synthetic", replayed=False, consumed=True, executed=False, delivered=False)
        assert write.call_args.kwargs["authenticated_user"].user_id == "synthetic_owner"


@pytest.mark.parametrize("changed", [
    {"task_fingerprint": "bad"},
    {"request_key": ""},
    {"request_key": "x"*129},
    {"request_key": "hello world"},
])
def test_invalid_input_denied_without_reserving(harness, changed):
    module, client = harness
    with patch("app.core.nova.work_revenue.operations_authenticated_subscription_adapter.reserve_owner_approved_test_subscription_task") as write:
        assert client.post(URL, headers=HEADER, json={**BODY, **changed}).status_code == 422
        write.assert_not_called()


def test_live_sales_flag_blocks(harness, monkeypatch):
    module, client = harness
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")
    with patch("app.core.nova.work_revenue.operations_authenticated_subscription_adapter.reserve_owner_approved_test_subscription_task") as write:
        assert client.post(URL, headers=HEADER, json=BODY).status_code == 503
        write.assert_not_called()
