"""Synthetic-only tests of the approved $9.99 access policy."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.nova.billing.starter_self_service import (
    FEATURES, MANAGED_TASKS_INCLUDED, allows_starter_feature,
)
from app.core.nova.work_revenue.operations_package_allowances import (
    VerifiedEntitlement, can_accept_task,
)

NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)
FLAGS = {
    "APP_ENV": "staging",
    "AMICOR_ENVIRONMENT": "staging",
    "NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED": "true",
    "NOVA_STRIPE_LIVE_ENABLED": "false",
    "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED": "false",
    "NOVA_STARTER_SELF_SERVICE_TEST_PRICE_ID": "price_synthetic_starter",
}
BASE = dict(feature="basic_workspace", tenant_id="synthetic-tenant",
    verified_tenant_id="synthetic-tenant", recorded_plan="starter",
    status="active", recorded_price="price_synthetic_starter",
    verified_subscription=True, verified_paid_invoice=True,
    stripe_livemode=False, current_period_end=NOW+timedelta(days=30), now=NOW)


@pytest.fixture(autouse=True)
def staging(monkeypatch):
    for name, value in FLAGS.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_approved_self_service_features(feature):
    assert allows_starter_feature(**{**BASE, "feature": feature})


@pytest.mark.parametrize("field,value", [
    ("feature", "managed_task"), ("feature", "private_delivery"),
    ("feature", "premium_tools"), ("feature", "unknown"),
    ("tenant_id", ""), ("verified_tenant_id", "other-tenant"),
    ("recorded_plan", "professional"), ("recorded_plan", "starter_49"),
    ("status", "trialing"), ("status", "past_due"), ("status", "canceled"),
    ("status", "unpaid"), ("recorded_price", "price_wrong"),
    ("verified_subscription", False), ("verified_paid_invoice", False),
    ("stripe_livemode", True), ("stripe_livemode", None),
    ("current_period_end", NOW), ("current_period_end", NOW-timedelta(seconds=1)),
    ("current_period_end", NOW.replace(tzinfo=None)),
])
def test_invalid_evidence_denied(field, value):
    assert not allows_starter_feature(**{**BASE, field: value})


@pytest.mark.parametrize("flag,value", [
    ("APP_ENV", "production"), ("AMICOR_ENVIRONMENT", "production"),
    ("NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED", "false"),
    ("NOVA_STRIPE_LIVE_ENABLED", "true"),
    ("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true"),
    ("NOVA_STARTER_SELF_SERVICE_TEST_PRICE_ID", ""),
])
def test_fail_closed_configuration(monkeypatch, flag, value):
    monkeypatch.setenv(flag, value)
    assert not allows_starter_feature(**BASE)
    monkeypatch.delenv(flag)
    assert not allows_starter_feature(**BASE)


@pytest.mark.parametrize("plan", ["starter", "starter_999"])
def test_starter_has_no_managed_task_allowance(plan):
    assert MANAGED_TASKS_INCLUDED == 0
    entitlement = VerifiedEntitlement(plan=plan, customer_id="cus_synthetic",
        paid=True, status="active", subscription_id="sub_synthetic",
        period_start=NOW-timedelta(days=1), period_end=NOW+timedelta(days=29))
    allowed, _ = can_accept_task(entitlement, customer_id="cus_synthetic",
        now=NOW, accepted_unique_tasks=frozenset(), request_key="synthetic")
    assert not allowed


from types import SimpleNamespace
from app.core.nova.billing.starter_subscription_evidence import verify_starter_feature


def evidence():
    start = int((NOW-timedelta(days=1)).timestamp())
    end = int((NOW+timedelta(days=29)).timestamp())
    row = SimpleNamespace(tenant_id="synthetic-tenant", plan_key="starter",
        subscription_status="active", stripe_customer_id="cus_synthetic",
        stripe_subscription_id="sub_synthetic", stripe_price_id="price_synthetic_starter")
    sub = dict(id="sub_synthetic", customer="cus_synthetic", livemode=False,
        status="active", metadata=dict(nova_product="nova_saas",
            nova_tenant_id=row.tenant_id, nova_plan_key="starter"),
        items=dict(has_more=False, data=[dict(id="si_synthetic", quantity=1,
            current_period_start=start, current_period_end=end,
            price=dict(id=row.stripe_price_id, livemode=False, unit_amount=999,
                currency="usd", recurring=dict(interval="month", interval_count=1)))]),
        latest_invoice=dict(livemode=False, status="paid", currency="usd",
            amount_paid=999, customer=row.stripe_customer_id,
            parent=dict(type="subscription_details", subscription_details=dict(
                subscription=row.stripe_subscription_id)),
            lines=dict(has_more=False, data=[dict(
                parent=dict(type="subscription_item_details",
                    subscription_item_details=dict(proration=False, subscription=row.stripe_subscription_id,
                        subscription_item="si_synthetic")),
                quantity=1, pricing=dict(type="price_details", price_details=dict(price=row.stripe_price_id)),
                period=dict(start=start, end=end))])))
    return row, sub


def check(row, sub, feature="basic_workspace"):
    return verify_starter_feature(feature=feature, tenant_id="synthetic-tenant",
        row=row, subscription=sub, now=NOW)


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_exact_subscription_evidence(feature):
    row, sub = evidence()
    assert check(row, sub, feature)


@pytest.mark.parametrize("path,value", [
    (("id",), "sub_wrong"), (("customer",), "cus_wrong"),
    (("livemode",), True), (("status",), "canceled"),
    (("metadata", "nova_tenant_id"), "other-tenant"),
    (("metadata", "nova_product"), "other-product"),
    (("metadata", "nova_plan_key"), "business"),
    (("items", "has_more"), True),
    (("items", "data", 0, "quantity"), 2),
    (("items", "data", 0, "price", "id"), "price_wrong"),
    (("items", "data", 0, "price", "unit_amount"), 9900),
    (("items", "data", 0, "price", "currency"), "eur"),
    (("items", "data", 0, "price", "livemode"), True),
    (("items", "data", 0, "price", "recurring", "interval"), "year"),
    (("items", "data", 0, "current_period_end"), int(NOW.timestamp())),
    (("latest_invoice", "status"), "open"),
    (("latest_invoice", "amount_paid"), 0),
    (("latest_invoice", "livemode"), True),
    (("latest_invoice", "customer"), "cus_wrong"),
    (("latest_invoice", "parent", "subscription_details", "subscription"), "sub_wrong"),
    (("latest_invoice", "lines", "has_more"), True),
    (("items", "data", 0, "id"), "si_other"),
    (("latest_invoice", "lines", "data", 0, "pricing", "price_details", "price"), "price_other"),
    (("latest_invoice", "lines", "data", 0, "parent", "subscription_item_details", "subscription_item"), "si_other"),
    (("latest_invoice", "lines", "data", 0, "quantity"), 2),
    (("latest_invoice", "lines", "data", 0, "period", "end"), 0),
    (("latest_invoice", "lines", "data", 0, "parent", "subscription_item_details", "proration"), True),
])
def test_subscription_evidence_mismatch(path, value):
    row, sub = evidence()
    target = sub
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert not check(row, sub)


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "other-tenant"), ("subscription_status", "past_due"),
    ("plan_key", "business"), ("stripe_customer_id", None),
    ("stripe_subscription_id", None), ("stripe_price_id", "price_wrong"),
])
def test_record_binding_mismatch(field, value):
    row, sub = evidence()
    setattr(row, field, value)
    assert not check(row, sub)


def test_missing_invoice_fails_closed():
    row, sub = evidence()
    del sub["latest_invoice"]
    assert not check(row, sub)
    row, sub = evidence()
    assert not check(row, sub, "managed_task")


import sys
from types import ModuleType
from app.core.nova.billing.starter_authenticated_access import authenticated_starter_access
from app.core.nova.billing import starter_authenticated_access as adapter


@pytest.fixture
def adapter_fixture(monkeypatch):
    row, sub = evidence()
    user = SimpleNamespace(organization_id=row.tenant_id,
        user_id="synthetic-user", email="starter@example.invalid")
    from test_subscription_reversal_evidence import fixture as reversal_fixture
    payment = reversal_fixture("starter")
    sub["latest_invoice"]["id"] = payment["invoice_id"]
    state = SimpleNamespace(row=row, subscription=sub, key="sk_test_fixture",
        queries=0, reads=0, fail=False, payment=payment, charge_reads=0)
    from sqlalchemy import String
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    class SyntheticBase(DeclarativeBase):
        pass

    class SyntheticSubscription(SyntheticBase):
        __tablename__ = "synthetic_subscription"
        tenant_id: Mapped[str] = mapped_column(String, primary_key=True)

    models = ModuleType("app.core.nova.billing.models")
    models.NovaTenantSubscription = SyntheticSubscription
    signup_client = ModuleType("app.core.nova.signup.stripe_client")
    signup_client.stripe_secret_key = lambda: state.key
    billing_client = ModuleType("app.core.nova.billing.stripe_client")

    def retrieve(sub_id, params):
        state.reads += 1
        assert sub_id == row.stripe_subscription_id
        assert params == {"expand": ["latest_invoice"]}
        if state.fail:
            raise RuntimeError("synthetic provider failure")
        return state.subscription

    def list_payments(params):
        assert params == {"invoice": state.payment["invoice_id"], "limit": 2}
        return state.payment["invoice_payments"]

    def retrieve_intent(intent_id):
        assert intent_id == state.payment["payment_intent"]["id"]
        return state.payment["payment_intent"]

    def retrieve_charge(charge_id):
        assert charge_id == state.payment["charge"]["id"]
        state.charge_reads += 1
        return state.payment["charge"]

    billing_client.LiveNovaBillingStripeClient = lambda api_key: SimpleNamespace(
        _build_client=lambda: SimpleNamespace(v1=SimpleNamespace(
            subscriptions=SimpleNamespace(retrieve=retrieve),
            invoice_payments=SimpleNamespace(list=list_payments),
            payment_intents=SimpleNamespace(retrieve=retrieve_intent),
            charges=SimpleNamespace(retrieve=retrieve_charge))))
    for module in (models, signup_client, billing_client):
        monkeypatch.setitem(sys.modules, module.__name__, module)

    def execute(statement):
        state.queries += 1
        assert statement.compile().params == {"tenant_id_1": user.organization_id}
        return SimpleNamespace(scalar_one_or_none=lambda: state.row)

    db = SimpleNamespace(execute=execute)
    monkeypatch.setattr(adapter, "datetime", SimpleNamespace(now=lambda tz: NOW))
    return db, user, state


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_authenticated_adapter_valid(adapter_fixture, feature):
    db, user, state = adapter_fixture
    assert authenticated_starter_access(db, authenticated_user=user, feature=feature)
    assert state.queries == 1 and state.reads == 1


@pytest.mark.parametrize("field,value", [
    ("organization_id", ""), ("user_id", ""), ("email", "customer@example.com"),
])
def test_authenticated_adapter_invalid_identity(adapter_fixture, field, value):
    db, user, state = adapter_fixture
    setattr(user, field, value)
    assert not authenticated_starter_access(db, authenticated_user=user, feature="basic_workspace")
    assert state.queries == 0 and state.reads == 0


@pytest.mark.parametrize("failure", ["missing_row", "wrong_tenant", "wrong_plan",
    "live_key", "missing_key", "provider_failure", "canceled", "unpaid",
    "managed_task", "disabled"])
def test_authenticated_adapter_failures(adapter_fixture, monkeypatch, failure):
    db, user, state = adapter_fixture
    feature = "basic_workspace"
    if failure == "missing_row":
        state.row = None
    elif failure == "wrong_tenant":
        state.row.tenant_id = "other-tenant"
    elif failure == "wrong_plan":
        state.row.plan_key = "business"
    elif failure == "live_key":
        state.key = "sk_live_fixture"
    elif failure == "missing_key":
        state.key = ""
    elif failure == "provider_failure":
        state.fail = True
    elif failure == "canceled":
        state.subscription["status"] = "canceled"
    elif failure == "unpaid":
        state.subscription["latest_invoice"]["status"] = "open"
    elif failure == "managed_task":
        feature = "managed_task"
    elif failure == "disabled":
        monkeypatch.setenv("NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED", "false")
    assert not authenticated_starter_access(db, authenticated_user=user, feature=feature)
    if failure in {"missing_row", "wrong_plan", "live_key", "missing_key",
                   "managed_task", "disabled"}:
        assert state.reads == 0
    else:
        assert state.queries == 1 and state.reads == 1


@pytest.fixture
def starter_http(monkeypatch, adapter_fixture):
    import importlib
    from fastapi import FastAPI, HTTPException, Header
    from fastapi.testclient import TestClient

    db, user, state = adapter_fixture
    auth = ModuleType("app.auth")
    auth.UserContext = SimpleNamespace

    def authenticate(authorization: str = Header(default="")):
        if authorization != "Bearer synthetic-test":
            raise HTTPException(401, "Authentication required")
        return user

    auth.get_current_user_context = authenticate
    session = ModuleType("app.db.session")
    session.get_db = lambda: db
    monkeypatch.setitem(sys.modules, "app.auth", auth)
    monkeypatch.setitem(sys.modules, "app.db.session", session)
    module_name = "app.core.nova.billing.starter_feature_routes"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    routes = importlib.import_module(module_name)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        yield client, state
    sys.modules.pop(module_name, None)


ROUTES = [
    ("GET", "/workspace", None),
    ("POST", "/plan", {"goal": "Synthetic weekly review"}),
    ("GET", "/templates", None),
    ("GET", "/assistance", None),
]
AUTH = {"Authorization": "Bearer synthetic-test"}


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_starter_http_requires_authentication(starter_http, method, path, body):
    client, state = starter_http
    response = client.request(method, "/api/nova/starter"+path, json=body)
    assert response.status_code == 401
    assert state.reads == 0


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_starter_http_valid_subscription(starter_http, method, path, body):
    client, state = starter_http
    response = client.request(method, "/api/nova/starter"+path, json=body, headers=AUTH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert state.reads == 1
    result = response.json()
    if path == "/workspace":
        assert result["managed_tasks"] == 0 and result["monthly_usd_cents"] == 999
    elif path == "/plan":
        assert result["goal"] == body["goal"] and result["saved"] is False
        assert result["execution"] == "customer_self_service"
    elif path == "/templates":
        assert len(result["templates"]) == 3
    else:
        assert result["external_ai"] is False and result["managed_execution"] is False


@pytest.mark.parametrize("method,path,body", ROUTES)
@pytest.mark.parametrize("failure", ["canceled", "unpaid", "live", "disabled"])
def test_starter_http_denies_invalid_subscription(starter_http, monkeypatch, method, path, body, failure):
    client, state = starter_http
    if failure == "canceled":
        state.subscription["status"] = "canceled"
    elif failure == "unpaid":
        state.subscription["latest_invoice"]["status"] = "open"
    elif failure == "live":
        state.key = "sk_live_fixture"
    else:
        monkeypatch.setenv("NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED", "false")
    response = client.request(method, "/api/nova/starter"+path, json=body, headers=AUTH)
    assert response.status_code == 403
    assert "synthetic" not in response.text


def test_starter_http_no_execution_route(starter_http):
    client, state = starter_http
    assert client.post("/api/nova/starter/execute", headers=AUTH).status_code == 404
    assert state.reads == 0


@pytest.mark.parametrize("goal", ["", "x"*501])
def test_starter_http_invalid_plan(starter_http, goal):
    client, state = starter_http
    assert client.post("/api/nova/starter/plan", headers=AUTH, json={"goal": goal}).status_code == 422
    assert state.reads == 0


def test_starter_interface_private(starter_http):
    client, state = starter_http
    url = "/api/nova/starter/interface"
    assert client.get(url).status_code == 401
    assert state.reads == 0
    response = client.get(url, headers=AUTH)
    assert response.status_code == 200
    assert "Starter workspace" in response.text
    assert "text/html" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert "connect-src 'self'" in response.headers["content-security-policy"]
    assert state.reads == 1
    state.subscription["status"] = "canceled"
    assert client.get(url, headers=AUTH).status_code == 403


@pytest.mark.parametrize("flag", [
    "APP_ENV", "AMICOR_ENVIRONMENT", "NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED",
    "NOVA_STRIPE_LIVE_ENABLED", "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED",
])
def test_starter_registration_requires_explicit_staging(starter_http, monkeypatch, flag):
    from app.core.nova.billing.starter_feature_routes import starter_routes_enabled
    assert starter_routes_enabled()
    monkeypatch.delenv(flag)
    assert not starter_routes_enabled()


def test_starter_renewal_requires_current_paid_invoice():
    row, sub = evidence()
    item = sub["items"]["data"][0]
    boundary = datetime.fromtimestamp(item["current_period_end"], timezone.utc)
    def at(moment):
        return verify_starter_feature(feature="basic_workspace",
            tenant_id=row.tenant_id, row=row, subscription=sub, now=moment)
    sub["cancel_at_period_end"] = True
    assert at(boundary-timedelta(seconds=1))
    assert not at(boundary)
    start = int(boundary.timestamp())
    end = int((boundary+timedelta(days=30)).timestamp())
    item.update(current_period_start=start, current_period_end=end)
    sub["cancel_at_period_end"] = False
    assert not at(boundary)
    invoice = sub["latest_invoice"]
    invoice["lines"]["data"][0]["period"] = {"start": start, "end": end}
    invoice["status"] = "open"
    assert not at(boundary)
    invoice["status"] = "paid"
    assert at(boundary)
    sub["status"] = "canceled"
    assert not at(boundary)


@pytest.mark.parametrize("method,path,body", ROUTES)
@pytest.mark.parametrize("field,value", [("amount_refunded", 1), ("refunded", True), ("disputed", True)])
def test_starter_http_reversal_denies_access(starter_http, method, path, body, field, value):
    client, state = starter_http
    state.payment["charge"][field] = value
    response = client.request(method, "/api/nova/starter"+path, json=body, headers=AUTH)
    assert response.status_code == 403
    assert state.charge_reads == 1


def test_starter_reversal_missing_invoice_payment_denied(adapter_fixture):
    db, user, state = adapter_fixture
    state.payment["invoice_payments"]["data"].clear()
    assert not authenticated_starter_access(db, authenticated_user=user, feature="basic_workspace")
    assert state.charge_reads == 0


@pytest.mark.parametrize("checkout_price,allowed", [
    ("price_synthetic_starter", True), ("price_other", False),
])
def test_checkout_and_entitlement_prices_must_agree(monkeypatch, checkout_price, allowed):
    monkeypatch.setenv("NOVA_STRIPE_PRICE_STARTER", checkout_price)
    assert allows_starter_feature(**BASE) is allowed


from app.core.nova.billing.starter_self_service import (
    LIVE_STARTER_PRICE, allows_live_starter_feature,
)

LIVE_FLAGS = {
    "APP_ENV": "production",
    "AMICOR_ENVIRONMENT": "production",
    "NOVA_STARTER_SELF_SERVICE_PRODUCTION_ENABLED": "true",
    "NOVA_STRIPE_LIVE_ENABLED": "true",
    "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED": "true",
    "NOVA_STRIPE_PRICE_STARTER": LIVE_STARTER_PRICE,
    "NOVA_BILLING_CHECKOUT_TRIAL_ENABLED": "false",
}
LIVE_BASE = {**BASE, "recorded_price": LIVE_STARTER_PRICE, "stripe_livemode": True}


@pytest.fixture
def live_policy(monkeypatch):
    for name, value in LIVE_FLAGS.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_live_starter_policy_approved_features(live_policy, feature):
    assert allows_live_starter_feature(**{**LIVE_BASE, "feature": feature})
    assert not allows_starter_feature(**{**LIVE_BASE, "feature": feature})


@pytest.mark.parametrize("flag", sorted(LIVE_FLAGS))
def test_live_starter_policy_requires_every_flag(live_policy, monkeypatch, flag):
    monkeypatch.delenv(flag)
    assert not allows_live_starter_feature(**LIVE_BASE)
    monkeypatch.setenv(flag, "incorrect")
    assert not allows_live_starter_feature(**LIVE_BASE)


@pytest.mark.parametrize("field,value", [
    ("feature", "managed_task"), ("feature", "private_delivery"),
    ("tenant_id", ""), ("verified_tenant_id", "other-tenant"),
    ("recorded_plan", "professional"), ("recorded_price", "price_other"),
    ("status", "trialing"), ("status", "past_due"), ("status", "canceled"),
    ("verified_subscription", False), ("verified_paid_invoice", False),
    ("stripe_livemode", False), ("stripe_livemode", None),
    ("current_period_end", NOW),
])
def test_live_starter_policy_rejects_invalid_evidence(live_policy, field, value):
    assert not allows_live_starter_feature(**{**LIVE_BASE, field: value})


@pytest.fixture
def live_adapter(live_policy, adapter_fixture):
    db, user, state = adapter_fixture
    user.email = "customer@example.com"
    state.key = "sk_live_fixture"
    state.row.stripe_price_id = LIVE_STARTER_PRICE
    sub = state.subscription
    sub["livemode"] = True
    sub["items"]["data"][0]["price"].update(id=LIVE_STARTER_PRICE, livemode=True)
    invoice = sub["latest_invoice"]
    invoice["livemode"] = True
    invoice["lines"]["data"][0]["pricing"]["price_details"]["price"] = LIVE_STARTER_PRICE
    for record in (state.payment["invoice_payments"]["data"][0],
                   state.payment["payment_intent"], state.payment["charge"]):
        record["livemode"] = True
    return db, user, state


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_live_authenticated_adapter(live_adapter, feature):
    db, user, state = live_adapter
    assert authenticated_starter_access(db, authenticated_user=user, feature=feature)
    assert state.reads == 1 and state.charge_reads == 1


@pytest.mark.parametrize("failure", ["test_key", "test_subscription", "test_invoice",
    "test_charge", "refund", "dispute", "wrong_customer", "wrong_tenant", "disabled"])
def test_live_authenticated_adapter_denies_invalid_evidence(live_adapter, monkeypatch, failure):
    db, user, state = live_adapter
    if failure == "test_key":
        state.key = "sk_test_fixture"
    elif failure == "test_subscription":
        state.subscription["livemode"] = False
    elif failure == "test_invoice":
        state.subscription["latest_invoice"]["livemode"] = False
    elif failure == "test_charge":
        state.payment["charge"]["livemode"] = False
    elif failure == "refund":
        state.payment["charge"]["amount_refunded"] = 1
    elif failure == "dispute":
        state.payment["charge"]["disputed"] = True
    elif failure == "wrong_customer":
        state.subscription["customer"] = "cus_other"
    elif failure == "wrong_tenant":
        state.row.tenant_id = "other-tenant"
    else:
        monkeypatch.delenv("NOVA_STARTER_SELF_SERVICE_PRODUCTION_ENABLED")
    assert not authenticated_starter_access(db, authenticated_user=user, feature="basic_workspace")
