"""Offline fail-closed tests for Starter payment binding; no paid tasks executed."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.nova.work_revenue import operations_starter_payment_binding as binding


def test_binding_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_STARTER_BINDING_ENABLED", raising=False)
    with pytest.raises(HTTPException) as error:
        binding._require_ready()
    assert error.value.status_code == 503


def test_paid_lead_requires_matching_verified_session(monkeypatch):
    good = SimpleNamespace(
        lead_type="anonymous_operations", service_plan="starter_49",
        payment_status="paid", consent=True,
        stripe_checkout_session_id="cs_test_exact",
        starter_paid_session_id="cs_test_exact",
        stripe_customer_id="cus_exact",
    )

    class FakeDB:
        def __init__(self, row):
            self.row = row
        def get(self, _model, _key):
            return self.row

    assert binding._paid_lead(FakeDB(good), "test") is good
    for overrides in [
        {"payment_status": "pending"},
        {"starter_paid_session_id": "cs_test_other"},
        {"starter_paid_session_id": None},
        {"stripe_customer_id": None},
        {"consent": False},
        {"service_plan": "launch_99"},
    ]:
        row = SimpleNamespace(**{**vars(good), **overrides})
        with pytest.raises(HTTPException) as error:
            binding._paid_lead(FakeDB(row), "test")
        assert error.value.status_code == 409


def test_payment_binding_has_explicit_unique_constraints():
    assert binding.starter_bindings.c.lead_id.primary_key
    assert binding.starter_bindings.c.stripe_checkout_session_id.unique
    constraints = [c for c in binding.starter_bindings.constraints if c.name == "uq_nova_operations_starter_paid_task"]
    assert len(constraints) == 1
    assert {c.name for c in constraints[0].columns} == {
        "organization_id", "engagement_id", "task_id"
    }
