"""Isolated private approval handler tests; no production app import or DB calls."""
import importlib
import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute


def _import_route(monkeypatch):
    fake_auth = types.ModuleType("app.auth")
    fake_auth.UserContext = type("UserContext", (), {})
    fake_auth.get_current_user_context = lambda: None
    fake_session = types.ModuleType("app.db.session")
    fake_session.get_db = lambda: None
    monkeypatch.setitem(sys.modules, "app.auth", fake_auth)
    monkeypatch.setitem(sys.modules, "app.db.session", fake_session)
    module_name = "app.core.nova.work_revenue.operations_owner_approval_router"
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


@pytest.fixture
def api(monkeypatch):
    module = _import_route(monkeypatch)
    for key, value in (
        ("APP_ENV", "staging"),
        ("AMICOR_ENVIRONMENT", "staging"),
        ("NOVA_OPERATIONS_SUBSCRIPTION_OWNER_API_STAGING_ENABLED", "true"),
        ("NOVA_STRIPE_LIVE_ENABLED", "false"),
        ("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false"),
    ):
        monkeypatch.setenv(key, value)
    return module


def _payload(api):
    return api.OwnerScopeDecision(
        engagement_id="eng_synthetic", task_id="task_synthetic",
        lead_id="lead_synthetic", task_fingerprint="a"*64, decision="APPROVED",
    )


def _owner(org="org_synthetic", role="admin"):
    return SimpleNamespace(organization_id=org, user_id="owner_synthetic", role=role)


def test_explicit_disabled_gate_before_db_write(api, monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_SUBSCRIPTION_OWNER_API_STAGING_ENABLED", raising=False)
    with patch.object(api, "record_staging_owner_scope_decision") as action:
        with pytest.raises(HTTPException) as exc:
            api.record_owner_scope_decision_endpoint(_payload(api), user=_owner(), db=Mock())
        assert exc.value.status_code == 503
        action.assert_not_called()


@pytest.mark.parametrize("role,org", [("staff", "org_synthetic"), ("admin", "")])
def test_non_owner_cannot_approve(api, role, org):
    with patch.object(api, "record_staging_owner_scope_decision") as action:
        with pytest.raises(HTTPException) as exc:
            api.record_owner_scope_decision_endpoint(_payload(api), user=_owner(org, role), db=Mock())
        assert exc.value.status_code == 403
        action.assert_not_called()


def test_only_owner_decision_no_delivery(api):
    with patch.object(api, "record_staging_owner_scope_decision") as action:
        action.return_value = {"decision": "APPROVED", "event_id": "synthetic_event",
                               "task_id": "task_synthetic", "executed": False}
        result = api.record_owner_scope_decision_endpoint(_payload(api), user=_owner(), db=Mock())
        assert result["delivered"] is False and result["executed"] is False
        assert action.call_args.kwargs["authenticated_user"].user_id == "owner_synthetic"


def test_route_only_has_decision_post(api):
    routes = [r for r in api.router.routes if isinstance(r, APIRoute)]
    assert len(routes) == 1
    assert routes[0].path.endswith("/decision") and routes[0].methods == {"POST"}


def test_live_sales_blocks(api, monkeypatch):
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")
    with patch.object(api, "record_staging_owner_scope_decision") as action:
        with pytest.raises(HTTPException) as exc:
            api.record_owner_scope_decision_endpoint(_payload(api), user=_owner(), db=Mock())
        assert exc.value.status_code == 503
        action.assert_not_called()
