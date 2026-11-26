"""Exercise actual hosted recovery and feature routes with fake Stripe JSON; no network."""
import importlib
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

@pytest.fixture
def rehearsal(monkeypatch):
    env = {
        "APP_ENV": "staging", "AMICOR_ENVIRONMENT": "staging",
        "NOVA_STRIPE_LIVE_ENABLED": "false",
        "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED": "false",
        "NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED": "false",
        "NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED": "true",
        "NOVA_BILLING_CHECKOUT_TRIAL_ENABLED": "false",
        "STRIPE_SECRET_KEY": "sk_test_synthetic_only",
        "NOVA_STRIPE_PRICE_STARTER": "price_synthetic",
        "NOVA_STARTER_SELF_SERVICE_TEST_PRICE_ID": "price_synthetic",
        "NOVA_OPERATIONS_SANDBOX_ACCESS_TOKEN": "synthetic-only-token-not-real",
        "DATABASE_URL": "sqlite:////tmp/nova-starter-999-rehearsal.db",
        "RENDER_EXTERNAL_URL": "https://nova-operations-checkout-sandbox.onrender.com",
        "NOVA_STARTER_RECOVERY_CHECKOUT_ID": "cs_test_synthetic",
        "NOVA_STARTER_RECOVERY_CUSTOMER_ID": "cus_synthetic",
        "NOVA_STARTER_RECOVERY_SUBSCRIPTION_ID": "sub_synthetic",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    m = importlib.import_module("operations_starter_subscription_rehearsal")
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    m.ensure_nova_billing_schema(engine)
    sessions = sessionmaker(bind=engine)
    def db():
        with sessions() as session:
            yield session
    monkeypatch.setitem(m.app.dependency_overrides, m.get_db, db)
    start, end = int(time.time()) - 60, int(time.time()) + 86400
    metadata = {"nova_product": "nova_saas", "nova_plan_key": "starter",
                "nova_tenant_id": "starter-999-synthetic-tenant",
                "nova_user_id": "starter-999-synthetic-owner"}
    invoice = {"id":"in_synthetic","livemode":False,"status":"paid","currency":"usd",
        "amount_paid":999,"customer":"cus_synthetic",
        "parent":{"type":"subscription_details","subscription_details":{"subscription":"sub_synthetic"}},
        "lines":{"has_more":False,"data":[{"parent":{"type":"subscription_item_details",
          "subscription_item_details":{"proration":False,"subscription":"sub_synthetic","subscription_item":"si_synthetic"}},
          "pricing":{"type":"price_details","price_details":{"price":"price_synthetic"}},
          "quantity":1,"period":{"start":start,"end":end}}]}}
    objects = {
        "checkout/sessions/cs_test_synthetic":{"id":"cs_test_synthetic","livemode":False,
            "subscription":"sub_synthetic","customer":"cus_synthetic","mode":"subscription",
            "status":"complete","payment_status":"paid","amount_total":999,"currency":"usd","metadata":{}},
        "subscriptions/sub_synthetic":{"id":"sub_synthetic","customer":"cus_synthetic","livemode":False,
            "status":"active","metadata":metadata,"latest_invoice":invoice,
            "items":{"has_more":False,"data":[{"id":"si_synthetic","quantity":1,
            "current_period_start":start,"current_period_end":end,
            "price":{"id":"price_synthetic","livemode":False,"unit_amount":999,"currency":"usd",
            "recurring":{"interval":"month","interval_count":1}}}]}},
        "invoice_payments":{"has_more":False,"data":[{"livemode":False,"invoice":"in_synthetic",
            "status":"paid","currency":"usd","amount_paid":999,
            "payment":{"type":"payment_intent","payment_intent":"pi_synthetic"}}]},
        "payment_intents/pi_synthetic":{"id":"pi_synthetic","livemode":False,"customer":"cus_synthetic",
            "status":"succeeded","currency":"usd","amount_received":999,"latest_charge":"ch_synthetic"},
        "charges/ch_synthetic":{"id":"ch_synthetic","livemode":False,"payment_intent":"pi_synthetic",
            "customer":"cus_synthetic","currency":"usd","amount_captured":999,"status":"succeeded",
            "paid":True,"captured":True,"refunded":False,"amount_refunded":0,"disputed":False},
    }
    calls = []
    def fake_get(url, **kwargs):
        assert url.startswith("https://api.stripe.com/v1/")
        assert kwargs["allow_redirects"] is False
        assert kwargs["headers"]["Authorization"] == "Bearer sk_test_synthetic_only"
        key = url.split("/v1/", 1)[1]
        calls.append(key)
        if key == "subscriptions/sub_synthetic":
            assert ("expand[]", "latest_invoice") in kwargs["params"]
        value = objects[key]
        if isinstance(value, int):
            return SimpleNamespace(status_code=value)
        return SimpleNamespace(status_code=200,json=lambda:value)
    monkeypatch.setattr(m.requests, "get", fake_get)
    h = {"x-amicor-sandbox-token":env["NOVA_OPERATIONS_SANDBOX_ACCESS_TOKEN"]}
    yield TestClient(m.app), h, objects, calls, sessions, m
    engine.dispose()

def test_recover_and_use_workspace(rehearsal):
    c,h,objects,calls,sessions,m = rehearsal
    assert c.get("/api/nova/starter/workspace",headers=h).status_code == 403
    assert c.post("/sandbox/reconcile").status_code == 403
    assert c.post("/sandbox/checkout",headers=h).status_code == 409
    for _ in range(2):
        result = c.post("/sandbox/reconcile",headers=h)
        assert result.status_code == 200, result.text
    with sessions() as db:
        assert db.query(m.NovaTenantSubscription).count() == 1
    for path in ("workspace","templates","assistance"):
        assert c.get("/api/nova/starter/"+path,headers=h).status_code == 200
    assert c.post("/api/nova/starter/plan",headers=h,json={"goal":"Weekly review"}).status_code == 200
    objects["charges/ch_synthetic"]["refunded"] = True
    assert c.get("/api/nova/starter/workspace",headers=h).status_code == 403

@pytest.mark.parametrize("key,field,value,stage", [
    ("checkout/sessions/cs_test_synthetic","livemode",True,"checkout_mode_live"),
    ("checkout/sessions/cs_test_synthetic","customer","cus_other","checkout_customer"),
    ("checkout/sessions/cs_test_synthetic","payment_status","unpaid","checkout_payment_status"),
    ("checkout/sessions/cs_test_synthetic","metadata",{"nova_tenant_id":"other"},"checkout_metadata_conflict"),
    ("checkout/sessions/cs_test_synthetic",None,403,"checkout_read_permission"),
    ("checkout/sessions/cs_test_synthetic",None,404,"checkout_read_not_found"),
    ("subscriptions/sub_synthetic","status","canceled","subscription_and_invoice_evidence"),
    ("charges/ch_synthetic","amount_refunded",1,"invoice_payment_and_reversal_evidence"),
])
def test_recovery_fails_closed(rehearsal,key,field,value,stage):
    c,h,objects,calls,sessions,m = rehearsal
    if field is None:
        objects[key] = value
    else:
        objects[key][field] = value
    r = c.post("/sandbox/reconcile",headers=h)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["stage"] == stage
    with sessions() as db:
        assert db.query(m.NovaTenantSubscription).count() == 0
    assert c.get("/api/nova/starter/workspace",headers=h).status_code == 403
