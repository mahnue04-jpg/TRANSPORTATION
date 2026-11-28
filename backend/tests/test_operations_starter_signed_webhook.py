"""Signed Stripe test-event integration: no Stripe API or production database calls."""
import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.marketing import routes
from app.modules.marketing.operations_billing import AGENT_PRODUCT


SECRET = "whsec_starter_synthetic_ci_only"


class FakeDB:
    def __init__(self):
        self.lead = SimpleNamespace(
            id="synthetic-lead", lead_type="anonymous_operations",
            service_plan="starter_49", payment_status="pending", status="new",
            stripe_checkout_session_id="cs_test_starter",
            stripe_customer_id="cus_test_starter",
            starter_paid_session_id=None, starter_entitlement_state=None,
            starter_payment_intent_id=None,
        )
        self.commits = 0

    def get(self, model, lead_id):
        return self.lead if lead_id == self.lead.id else None

    def query(self, model):
        return FakeQuery(self.lead)

    def rollback(self):
        pass

    def commit(self):
        self.commits += 1


class FakeQuery:
    def __init__(self, lead):
        self.lead = lead

    def filter(self, *conditions):
        from sqlalchemy.sql import operators
        for condition in conditions:
            if condition.operator == operators.eq and getattr(self.lead, condition.left.key, None) != condition.right.value:
                self.lead = None
                break
        return self

    def with_for_update(self):
        return self

    def populate_existing(self):
        return self

    def limit(self, count):
        return self

    def all(self):
        return [self.lead] if self.lead else []

    def one_or_none(self):
        return self.lead


class FakeRequest:
    def __init__(self, body):
        self.data = body

    async def body(self):
        return self.data


def event(event_type="checkout.session.completed", **overrides):
    obj = {
        "id": "cs_test_starter", "customer": "cus_test_starter",
        "client_reference_id": "synthetic-lead",
        "metadata": {
            "nova_product": AGENT_PRODUCT, "nova_agent_plan": "starter_49",
            "nova_agent_lead_id": "synthetic-lead",
        },
        "mode": "payment", "currency": "usd", "amount_total": 4900,
        "payment_status": "paid", "payment_intent": "pi_test_starter", "livemode": False,
    }
    obj.update(overrides)
    return {
        "id": "evt_test_starter_synthetic", "object": "event",
        "type": event_type, "livemode": False, "data": {"object": obj},
    }


def signed(payload):
    data = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(SECRET.encode(), timestamp.encode() + b"." + data, hashlib.sha256).hexdigest()
    return data, f"t={timestamp},v1={digest}"


def post(db, payload, *, sig=None):
    data, correct_sig = signed(payload)
    return asyncio.run(routes.nova_agent_stripe_webhook(
        FakeRequest(data), stripe_signature=correct_sig if sig is None else sig, db=db,
    ))


@pytest.fixture(autouse=True)
def synthetic_webhook_only(monkeypatch):
    monkeypatch.setenv("STRIPE_NOVA_AGENT_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "false")
    monkeypatch.setenv("HEALTH_ISF_STRIPE_ENABLED", "false")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("NOVA_OPERATIONS_STARTER_BINDING_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false")
    monkeypatch.setattr(routes, "agent_checkout_mode", lambda: "test")
    monkeypatch.setattr(routes, "ensure_marketing_schema", lambda: None)


def test_valid_signed_starter_paid_session_and_retry():
    db = FakeDB()
    assert post(db, event())["result"] == "paid"
    assert db.lead.payment_status == "paid"
    assert db.lead.starter_paid_session_id == "cs_test_starter"
    assert db.lead.status == "qualified"
    assert post(db, event())["result"] == "paid"
    assert db.lead.starter_paid_session_id == "cs_test_starter"


def test_reject_missing_or_invalid_webhook_signature():
    db = FakeDB()
    with pytest.raises(HTTPException) as bad:
        post(db, event(), sig="t=1,v1=invalid")
    assert bad.value.status_code == 400
    assert db.lead.starter_paid_session_id is None
    assert db.commits == 0


@pytest.mark.parametrize("override,expected", [
    ({"id": "cs_test_other"}, "checkout_identity_mismatch"),
    ({"customer": "cus_test_other"}, "checkout_identity_mismatch"),
    ({"amount_total": 0}, "starter_payment_amount_mismatch"),
    ({"amount_total": 4800}, "starter_payment_amount_mismatch"),
    ({"currency": "eur"}, "starter_payment_amount_mismatch"),
    ({"mode": "subscription"}, "starter_payment_amount_mismatch"),
    ({"payment_status": "no_payment_required"}, "pending"),
])
def test_signed_but_wrong_checkout_cannot_fund_task(override, expected):
    db = FakeDB()
    response = post(db, event(**override))
    assert response["result"] == expected
    assert db.lead.starter_paid_session_id is None
    assert db.lead.payment_status != "paid"


def test_missing_or_conflicting_payment_intent_fails_closed():
    for intent in (None, "pi_test_other"):
        db = FakeDB()
        obj = event()
        obj["data"]["object"]["payment_intent"] = intent
        if intent == "pi_test_other":
            db.lead.starter_payment_intent_id = "pi_test_starter"
        result = post(db, obj)
        assert result["handled"] is False
        assert result["result"] == "starter_payment_intent_unverified"
        assert db.lead.payment_status != "paid"
        assert db.lead.starter_paid_session_id is None


def test_missing_signature_is_rejected():
    db = FakeDB()
    data, _ = signed(event())
    with pytest.raises(HTTPException) as missing:
        asyncio.run(routes.nova_agent_stripe_webhook(
            FakeRequest(data), stripe_signature=None, db=db,
        ))
    assert missing.value.status_code == 400
    assert db.lead.starter_paid_session_id is None
    assert db.commits == 0


def test_signed_wrong_plan_cannot_mark_starter_paid():
    db = FakeDB()
    payload = event()
    payload["data"]["object"]["metadata"]["nova_agent_plan"] = "launch_99"
    response = post(db, payload)
    assert response["result"] == "checkout_identity_mismatch"
    assert db.lead.starter_paid_session_id is None
    assert db.commits == 0


def test_async_payment_succeeded_must_have_paid_status():
    db = FakeDB()
    assert post(db, event("checkout.session.async_payment_succeeded", payment_status="unpaid"))["result"] == "pending"
    assert db.lead.starter_paid_session_id is None
    assert post(db, event("checkout.session.async_payment_succeeded"))["result"] == "paid"
    assert db.lead.starter_paid_session_id == "cs_test_starter"


def test_signed_paid_webhook_does_not_restore_refund_or_dispute():
    for blocked in ("refund_pending", "refunded", "disputed", "chargeback"):
        db = FakeDB()
        db.lead.starter_entitlement_state = blocked
        assert post(db, event())["result"] == "paid"
        assert db.lead.starter_entitlement_state == blocked
        assert db.lead.status == "new"
        assert db.lead.starter_paid_session_id == "cs_test_starter"


def test_delayed_failure_and_invoice_cannot_override_starter():
    db = FakeDB()
    post(db, event())
    for kind in ("checkout.session.async_payment_failed", "checkout.session.expired", "invoice.paid"):
        response = post(db, event(kind))
        assert response["handled"] is False
        assert db.lead.payment_status == "paid"
        assert db.lead.starter_paid_session_id == "cs_test_starter"


@pytest.mark.parametrize("kind,state", [("charge.refunded", "refunded"), ("charge.dispute.created", "disputed")])
def test_signed_reversal_blocks_exact_paid_order_and_replay(kind, state):
    db = FakeDB()
    post(db, event())
    payload = event(kind, amount_refunded=100, metadata={})
    assert post(db, payload)["result"] == "starter_entitlement_blocked"
    assert db.lead.starter_entitlement_state == state
    post(db, payload)
    post(db, event())
    assert db.lead.starter_entitlement_state == state


def test_unmatched_reversal_retries_without_mutation():
    db = FakeDB()
    post(db, event())
    with pytest.raises(HTTPException) as exc:
        post(db, event("charge.refunded", payment_intent="pi_unrelated", amount_refunded=100))
    assert exc.value.status_code == 503
    assert db.lead.starter_entitlement_state == "active"


def test_live_event_rejected():
    db = FakeDB()
    payload = event()
    payload["livemode"] = True
    assert post(db, payload)["result"] == "starter_confirmation_gated"
    assert db.commits == 0
