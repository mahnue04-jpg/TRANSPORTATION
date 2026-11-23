"""Offline fail-closed tests for Starter payment binding; no paid tasks executed."""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
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
        payment_status="paid", starter_entitlement_state="active", consent=True,
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
        {"starter_entitlement_state": None},
        {"starter_entitlement_state": "refunded"},
        {"starter_entitlement_state": "disputed"},
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


def test_payment_binding_idempotent_and_single_task(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    binding.metadata.create_all(engine)
    paid_lead = SimpleNamespace(
        id="lead-one", organization_name="Example Client",
        contact_name="Example Client", stripe_checkout_session_id="cs_test_exact",
    )
    monkeypatch.setenv("NOVA_OPERATIONS_STARTER_BINDING_ENABLED", "true")
    monkeypatch.setattr(binding, "_paid_lead", lambda db, lead_id: paid_lead)

    values = dict(
        lead_id="lead-one", organization_id="owner-org", owner_user_id="owner-user",
        engagement_id="eng-one", task_id="task-one", client_name="Example Client",
    )
    with Session(engine) as db:
        binding.bind_paid_starter(db, **values)
        # Exact retry must succeed without creating a duplicate binding.
        binding.bind_paid_starter(db, **values)
        with pytest.raises(HTTPException) as other_task:
            binding.bind_paid_starter(db, **{**values, "task_id": "task-two"})
        assert other_task.value.status_code == 409
        with pytest.raises(HTTPException) as other_owner:
            binding.bind_paid_starter(db, **{**values, "owner_user_id": "other-owner"})
        assert other_owner.value.status_code == 409
        with pytest.raises(HTTPException) as other_client:
            binding.bind_paid_starter(db, **{**values, "client_name": "Different Client"})
        assert other_client.value.status_code == 409
    engine.dispose()


def test_second_payment_cannot_fund_previously_bound_task(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    binding.metadata.create_all(engine)
    monkeypatch.setenv("NOVA_OPERATIONS_STARTER_BINDING_ENABLED", "true")
    lead_data = {
        "lead-one": SimpleNamespace(
            id="lead-one", organization_name="Example Client",
            contact_name="Example Client", stripe_checkout_session_id="cs_test_one",
        ),
        "lead-two": SimpleNamespace(
            id="lead-two", organization_name="Example Client",
            contact_name="Example Client", stripe_checkout_session_id="cs_test_two",
        ),
    }
    monkeypatch.setattr(binding, "_paid_lead", lambda db, lead_id: lead_data[lead_id])
    common = dict(
        organization_id="owner-org", owner_user_id="owner-user",
        engagement_id="eng-one", task_id="task-one", client_name="Example Client",
    )
    with Session(engine) as db:
        binding.bind_paid_starter(db, lead_id="lead-one", **common)
        with pytest.raises(HTTPException) as duplicate:
            binding.bind_paid_starter(db, lead_id="lead-two", **common)
        assert duplicate.value.status_code == 409
    engine.dispose()
