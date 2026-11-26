"""Isolated payment-to-task binding checks. No real Stripe, DB migration or files."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.nova.work_revenue import operations_starter_payment_binding as binding


class FakeSession:
    def __init__(self, lead):
        self.lead = lead
        self.inserted = []
        self.commits = 0
        self.existing = None

    def get(self, model, key):
        return self.lead if self.lead and key == self.lead.id else None

    def execute(self, stmt):
        if stmt.is_select:
            return SimpleNamespace(first=lambda: self.existing)
        self.inserted.append(stmt)
        return SimpleNamespace(all=lambda: [])

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


@pytest.fixture
def paid(monkeypatch):
    monkeypatch.setenv("NOVA_OPERATIONS_STARTER_BINDING_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false")
    lead = SimpleNamespace(
        id="lead-1", lead_type="anonymous_operations", service_plan="starter_49",
        payment_status="paid", consent=True, stripe_checkout_session_id="cs_123",
        starter_paid_session_id="cs_123", stripe_customer_id="cus_123",
        starter_payment_intent_id="pi_123", starter_entitlement_state="active",
        organization_name="Sample Company", contact_name="Sample Buyer",
    )
    return lead


def invoke(db, client="Sample Company"):
    return binding.bind_paid_starter(
        db, lead_id="lead-1", organization_id="org-a", owner_user_id="owner-a",
        engagement_id="eng-a", task_id="task-a", client_name=client,
    )


def test_paid_starter_bound_to_exact_client(paid):
    db = FakeSession(paid)
    invoke(db)
    assert db.commits == 1
    assert len(db.inserted) == 1


@pytest.mark.parametrize("change", [
    {"payment_status": "pending"},
    {"service_plan": "launch_99"},
    {"consent": False},
    {"starter_paid_session_id": "cs_other"},
    {"stripe_customer_id": None},
    {"starter_payment_intent_id": None},
    {"starter_payment_intent_id": "cs_wrong"},
    {"starter_entitlement_state": "refunded"},
    {"starter_entitlement_state": None},
])
def test_unverified_starter_rejected_before_database_write(paid, change):
    for k, v in change.items():
        setattr(paid, k, v)
    db = FakeSession(paid)
    with pytest.raises(HTTPException) as exc:
        invoke(db)
    assert exc.value.status_code == 409
    assert db.inserted == []


def test_paid_lead_cannot_fund_unrelated_client_task(paid):
    db = FakeSession(paid)
    with pytest.raises(HTTPException) as exc:
        invoke(db, client="Unrelated Company")
    assert exc.value.status_code == 409
    assert db.inserted == []


def test_binding_disabled_by_default_denies_processing(paid, monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_STARTER_BINDING_ENABLED")
    db = FakeSession(paid)
    with pytest.raises(HTTPException) as exc:
        invoke(db)
    assert exc.value.status_code == 503
    assert db.inserted == []


def test_exact_binding_retry_does_not_write_again(paid):
    db = FakeSession(paid)
    db.existing = SimpleNamespace(
        organization_id="org-a", owner_user_id="owner-a",
        engagement_id="eng-a", task_id="task-a",
        stripe_checkout_session_id="cs_123",
    )
    invoke(db)
    assert db.inserted == []
    assert db.commits == 0


def test_payment_cannot_be_reused_for_different_task(paid):
    db = FakeSession(paid)
    db.existing = SimpleNamespace(
        organization_id="org-a", owner_user_id="owner-a",
        engagement_id="eng-a", task_id="task-other",
        stripe_checkout_session_id="cs_123",
    )
    with pytest.raises(HTTPException) as exc:
        invoke(db)
    assert exc.value.status_code == 409
    assert db.inserted == []


@pytest.mark.parametrize("key,value", [("APP_ENV", "production"), ("AMICOR_ENVIRONMENT", "production"), ("NOVA_STRIPE_LIVE_ENABLED", "true"), ("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")])
def test_binding_denies_non_staging_or_live_mode(paid, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    db = FakeSession(paid)
    with pytest.raises(HTTPException) as exc:
        invoke(db)
    assert exc.value.status_code == 503
    assert db.inserted == []
