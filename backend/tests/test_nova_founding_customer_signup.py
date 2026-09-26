"""AMICOR Nova founding-customer signup path. Stripe TEST doubles only. No live charges."""
from __future__ import annotations

import secrets
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, hash_password, seed_default_users
from app.core.nova.autonomy.ledger import ensure_autonomy_schema
from app.core.nova.signup.models import (
    STATUS_FREE,
    STATUS_TRIALING,
    NovaCustomerTenant,
    NovaSignupAccount,
    NovaSignupWebhookEvent,
)
from app.core.nova.signup.offer import (
    FOUNDING_CAP,
    FOUNDING_COPY,
    FOUNDING_PAID_MONTHS,
    FOUNDING_PRICE_LOOKUP,
    FOUNDING_UNIT_AMOUNT,
    INTRO_DAYS,
    STANDARD_PRICE_LOOKUP,
    STANDARD_UNIT_AMOUNT,
    assert_no_rejected_prices,
    billing_plan,
    expected_unit_amount,
    intro_end_at,
    public_offer,
)
from app.core.nova.signup.schema_ensure import ensure_nova_signup_schema
from app.core.nova.signup.stripe_client import (
    FakeNovaSaasStripeClient,
    build_stripe_schedule_phases,
    set_nova_saas_stripe_override,
)
from app.db.models import User as UserModel
from app.core.nova.today.schema_ensure import ensure_nova_today_schema
from app.db.session import SessionLocal, engine, init_platform_db
from app.helpers import now, uuid4
from app.main import app
from app.modules.health_isf.models import ensure_health_isf_schema

ROOT = Path(__file__).resolve().parents[1]
SIGNUP_PAGE = ROOT / "static" / "nova-signup" / "index.html"


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    init_platform_db()
    ensure_health_isf_schema()
    ensure_nova_today_schema(engine)
    ensure_autonomy_schema(engine)
    ensure_nova_signup_schema(engine)
    return TestClient(app)


def _password() -> str:
    return "Nv-" + secrets.token_urlsafe(12)


def _signup_payload(**extra) -> dict:
    suffix = uuid4()[:8]
    body = {
        "business_name": extra.pop("business_name", f"American Courier {suffix}"),
        "contact_name": extra.pop("contact_name", "Mary Test"),
        "email": extra.pop("email", f"mary.{suffix}@example.com"),
        "phone": extra.pop("phone", "612-555-0100"),
        "industry": extra.pop("industry", "courier"),
        "password": extra.pop("password", _password()),
        "terms_accepted": extra.pop("terms_accepted", True),
    }
    body.update(extra)
    return body


def _activate(client: TestClient, fake: FakeNovaSaasStripeClient, *, payload: dict | None = None) -> dict:
    payload = payload or _signup_payload()
    password = payload["password"]
    created = client.post("/api/nova/signup", json=payload)
    assert created.status_code == 200, created.text
    body = created.json()
    assert "password" not in created.text.lower() or password not in created.text
    session_id = body["checkout_session_id"]
    session = fake.complete_session(session_id, payment_status="no_payment_required")
    webhook = client.post(
        "/api/nova/signup/stripe/webhook",
        json={
            "id": f"evt_act_{uuid4()[:12]}",
            "type": "checkout.session.completed",
            "data": {"object": session},
        },
    )
    assert webhook.status_code == 200, webhook.text
    assert webhook.json()["activated"] is True
    status = client.get(f"/api/nova/signup/{body['signup_id']}")
    assert status.status_code == 200, status.text
    return {
        "password": password,
        "email": payload["email"],
        "signup": created.json(),
        "status": status.json(),
        "webhook": webhook.json(),
    }


def test_offer_and_billing_plan_match_approved_founding_rule() -> None:
    offer = public_offer(occupied=0)
    assert offer["intro_days"] == 7
    assert offer["founding_cap"] == 10
    assert offer["founding_amount_usd"] == 59
    assert offer["founding_paid_months"] == 3
    assert offer["standard_amount_usd"] == 99
    assert 29 in offer["rejected_prices_usd"]
    assert offer["copy"] == FOUNDING_COPY
    founding = billing_plan(founding_eligible=True)
    standard = billing_plan(founding_eligible=False)
    assert_no_rejected_prices(founding)
    assert_no_rejected_prices(standard)
    assert founding["trial_period_days"] == INTRO_DAYS
    assert founding["phases"][0]["unit_amount"] == FOUNDING_UNIT_AMOUNT
    assert founding["phases"][0]["iterations"] == FOUNDING_PAID_MONTHS
    assert founding["phases"][0]["duration"] == {"interval": "month", "interval_count": FOUNDING_PAID_MONTHS}
    assert founding["phases"][1]["unit_amount"] == STANDARD_UNIT_AMOUNT
    assert standard["phases"][0]["unit_amount"] == STANDARD_UNIT_AMOUNT
    assert expected_unit_amount(founding=True, paid_month_index=0) == 0
    assert expected_unit_amount(founding=True, paid_month_index=1) == 5900
    assert expected_unit_amount(founding=True, paid_month_index=3) == 5900
    assert expected_unit_amount(founding=True, paid_month_index=4) == 9900
    assert expected_unit_amount(founding=False, paid_month_index=1) == 9900
    stamp = now()
    assert intro_end_at(stamp) - stamp == timedelta(days=7)


def test_public_signup_page_has_approved_offer_not_29() -> None:
    client = _client()
    page = client.get("/nova/signup")
    early = client.get("/nova/early-access")
    assert page.status_code == 200
    assert early.status_code == 200
    text = page.text
    assert "AMICOR Nova" in text
    assert FOUNDING_COPY in text or "$59/month for the first 3 paid months" in text
    assert "$29" not in text
    assert "$59/month for the first 3 paid months" in text
    assert SIGNUP_PAGE.read_text(encoding="utf-8").count("$29") == 0
    offer = client.get("/api/nova/signup/offer")
    assert offer.status_code == 200
    body = offer.json()
    assert body["copy"] == FOUNDING_COPY
    assert "$29" not in str(body["copy"])


def test_free_signup_has_limited_access_and_daily_ask_cap() -> None:
    client = _client()
    payload = _signup_payload()
    created = client.post("/api/nova/signup/free", json=payload)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == STATUS_FREE
    assert body["login_ready"] is True
    assert body["plan"]["tier"] == "free"
    assert body["plan"]["daily_ask_limit"] == 5
    assert not body.get("checkout_url")

    login = client.post(
        "/api/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    access = client.get("/api/nova/signup/me/access", headers=headers)
    assert access.status_code == 200, access.text
    access_body = access.json()
    assert access_body["tier"] == "free"
    assert access_body["free_daily_ask_limit"] == 5
    assert "nova_today" in access_body["allowed_surfaces"]
    assert "nova_business" not in access_body["allowed_surfaces"]

    assert client.get("/api/nova/government/dashboard", headers=headers).status_code == 403
    assert client.get("/api/nova/communications/dashboard", headers=headers).status_code == 403
    assert client.get("/api/nova/business/dashboard", headers=headers).status_code == 403
    assert client.get("/api/nova/accounting/summary", headers=headers).status_code == 403
    assert client.get("/api/nova/work/opportunities", headers=headers).status_code == 403
    assert client.get("/api/nova/payments/readiness", headers=headers).status_code == 403

    for _ in range(5):
        asked = client.post(
            "/api/nova/today/ask",
            headers=headers,
            json={"question": "What is my name?"},
        )
        assert asked.status_code == 200, asked.text
    limited = client.post(
        "/api/nova/today/ask",
        headers=headers,
        json={"question": "What is my name?"},
    )
    assert limited.status_code == 429
    assert "5 Ask Nova requests per day" in limited.text


def test_signup_checkout_webhook_intro_and_tenant_isolation() -> None:
    fake = FakeNovaSaasStripeClient()
    set_nova_saas_stripe_override(fake)
    try:
        client = _client()
        payload = _signup_payload()
        activated = _activate(client, fake, payload=payload)
        status = activated["status"]
        assert status["status"] == "trialing"
        assert status["login_ready"] is True
        assert status["founding_eligible"] is True
        assert status["plan"]["phases"][0]["unit_amount"] == 5900
        assert status["plan"]["phases"][0]["iterations"] == 3
        assert status["plan"]["phases"][1]["unit_amount"] == 9900
        assert fake.schedules
        assert fake.schedules[0]["phases"][0]["unit_amount"] == 5900
        assert len(fake.last_stripe_phases) == 3
        assert "duration" not in fake.last_stripe_phases[0]
        assert fake.last_stripe_phases[1]["duration"] == {"interval": "month", "interval_count": 3}
        assert "iterations" not in fake.last_stripe_phases[0]
        assert "iterations" not in fake.last_stripe_phases[1]
        assert "iterations" not in fake.last_stripe_phases[2]

        login = client.post(
            "/api/auth/login",
            json={"email": payload["email"], "password": payload["password"]},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        today = client.get("/api/nova/today/dashboard", headers=headers)
        assert today.status_code == 200, today.text
        dash = today.json()
        assert dash.get("product_counts") == []
        product_titles = [card.get("title") for card in dash.get("product_links") or []]
        assert "AMICOR Health" not in product_titles
        assert "AMICOR Delivery" not in product_titles
        assert "AMICOR Nova Freight" not in product_titles

        access = client.get("/api/nova/signup/me/access", headers=headers)
        assert access.status_code == 200
        assert access.json()["nova_saas_customer"] is True
        assert "health" in access.json()["blocked_surfaces"]
        assert "payments_readiness" in access.json()["blocked_surfaces"]

        assert client.get("/api/health-isf/rides", headers=headers).status_code == 403
        assert client.get("/api/health-isf/drivers", headers=headers).status_code == 403
        assert client.get("/api/nova/freight/shipments", headers=headers).status_code == 403
        assert client.get("/api/platform-ops/driver-onboarding/applications", headers=headers).status_code in {401, 403, 404, 405}
        assert client.get("/app", headers=headers).status_code == 403
        assert client.get("/workspace", headers=headers).status_code == 403
        assert client.get("/nova/freight", headers=headers).status_code == 403
        assert client.get("/nova/payments/readiness", headers=headers).status_code == 403
        assert client.get("/admin", headers=headers).status_code == 403
        assert client.get("/api/admin/dashboard", headers=headers).status_code == 403
        assert client.get("/api/admin/metrics", headers=headers).status_code == 403
        assert client.post(
            "/api/nova/tenants/provision",
            headers=headers,
            json={"owner_password": _password()},
        ).status_code == 403
    finally:
        set_nova_saas_stripe_override(None)


def test_failed_payment_does_not_activate_paid_customer() -> None:
    fake = FakeNovaSaasStripeClient()
    set_nova_saas_stripe_override(fake)
    try:
        client = _client()
        payload = _signup_payload()
        created = client.post("/api/nova/signup", json=payload)
        assert created.status_code == 200, created.text
        signup_id = created.json()["signup_id"]
        failed = client.post(
            "/api/nova/signup/stripe/webhook",
            json={
                "id": f"evt_fail_{uuid4()[:12]}",
                "type": "invoice.payment_failed",
                "data": {
                    "object": {
                        "id": "in_fail_test",
                        "paid": False,
                        "amount_paid": 0,
                        "metadata": {"nova_signup_id": signup_id, "nova_product": "nova_saas"},
                    }
                },
            },
        )
        assert failed.status_code == 200, failed.text
        assert failed.json()["activated"] is False
        assert failed.json()["paid_activated"] is False
        status = client.get(f"/api/nova/signup/{signup_id}").json()
        assert status["status"] == "failed"
        assert status["login_ready"] is False
        login = client.post(
            "/api/auth/login",
            json={"email": payload["email"], "password": payload["password"]},
        )
        assert login.status_code == 401
        unpaid = fake.complete_session(created.json()["checkout_session_id"], payment_status="unpaid")
        unpaid_hook = client.post(
            "/api/nova/signup/stripe/webhook",
            json={
                "id": f"evt_unpaid_{uuid4()[:12]}",
                "type": "checkout.session.completed",
                "data": {"object": unpaid},
            },
        )
        assert unpaid_hook.status_code == 200
        assert unpaid_hook.json().get("activated") is False
    finally:
        set_nova_saas_stripe_override(None)


def test_paid_months_fifty_nine_then_ninety_nine() -> None:
    fake = FakeNovaSaasStripeClient()
    set_nova_saas_stripe_override(fake)
    try:
        client = _client()
        activated = _activate(client, fake)
        signup_id = activated["signup"]["signup_id"]
        for month in range(1, 4):
            paid = client.post(
                "/api/nova/signup/stripe/webhook",
                json={
                    "id": f"evt_paid_{month}_{uuid4()[:8]}",
                    "type": "invoice.paid",
                    "data": {
                        "object": {
                            "id": f"in_paid_{month}",
                            "billing_reason": "subscription_cycle",
                            "amount_paid": 5900,
                            "metadata": {"nova_signup_id": signup_id, "nova_product": "nova_saas"},
                        }
                    },
                },
            )
            assert paid.status_code == 200, paid.text
            assert paid.json()["paid_month_index"] == month
            assert paid.json()["expected_unit_amount"] == 5900
        fourth = client.post(
            "/api/nova/signup/stripe/webhook",
            json={
                "id": f"evt_paid_4_{uuid4()[:8]}",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_paid_4",
                        "billing_reason": "subscription_cycle",
                        "amount_paid": 9900,
                        "metadata": {"nova_signup_id": signup_id, "nova_product": "nova_saas"},
                    }
                },
            },
        )
        assert fourth.status_code == 200, fourth.text
        assert fourth.json()["paid_month_index"] == 4
        assert fourth.json()["expected_unit_amount"] == 9900
        assert fourth.json()["paid_activated"] is True
    finally:
        set_nova_saas_stripe_override(None)


def test_customer_eleven_does_not_receive_founding_pricing() -> None:
    fake = FakeNovaSaasStripeClient()
    set_nova_saas_stripe_override(fake)
    try:
        client = _client()
        with SessionLocal() as db:
            ensure_nova_signup_schema()
            stamp = now()
            for slot in range(1, FOUNDING_CAP + 1):
                db.add(
                    NovaSignupAccount(
                        business_name=f"Founding Occupied {slot}",
                        contact_name="Occupied",
                        email=f"occupied.{slot}.{uuid4()[:6]}@example.com",
                        phone="612-555-0199",
                        industry="logistics",
                        password_hash=hash_password(_password()),
                        terms_accepted_at=stamp,
                        status=STATUS_TRIALING,
                        founding_reserved=True,
                        founding_slot=slot,
                    )
                )
            db.commit()
        payload = _signup_payload(business_name="Customer Eleven Logistics")
        created = client.post("/api/nova/signup", json=payload)
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["founding_eligible"] is False
        assert body["plan"]["tier"] == "standard"
        assert body["plan"]["phases"][0]["unit_amount"] == STANDARD_UNIT_AMOUNT
        assert all(phase["unit_amount"] != FOUNDING_UNIT_AMOUNT for phase in body["plan"]["phases"])
        session = fake.complete_session(body["checkout_session_id"])
        webhook = client.post(
            "/api/nova/signup/stripe/webhook",
            json={
                "id": f"evt_c11_{uuid4()[:12]}",
                "type": "checkout.session.completed",
                "data": {"object": session},
            },
        )
        assert webhook.status_code == 200, webhook.text
        assert webhook.json()["founding"] is False
        assert webhook.json()["plan"]["tier"] == "standard"
    finally:
        set_nova_saas_stripe_override(None)
        with SessionLocal() as db:
            db.query(NovaSignupAccount).filter(NovaSignupAccount.contact_name == "Occupied").delete()
            db.commit()


def test_health_register_is_not_the_nova_signup_path() -> None:
    client = _client()
    denied = client.post(
        "/api/auth/register",
        json={
            "email": f"public.{uuid4()[:8]}@example.com",
            "password": _password(),
            "display_name": "Public User",
            "role": "admin",
            "organization_name": "American Courier",
        },
    )
    assert denied.status_code == 403


def test_live_stripe_keys_are_rejected(monkeypatch) -> None:
    set_nova_saas_stripe_override(None)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_not_allowed_for_nova_saas")
    client = _client()
    created = client.post("/api/nova/signup", json=_signup_payload())
    assert created.status_code == 503
    assert "Live Stripe" in created.text or "not allowed" in created.text.lower()


def test_api_admin_prefix_is_blocked_for_nova_customers_only() -> None:
    from app.core.nova.signup.isolation import path_blocked_for_nova_customer

    assert path_blocked_for_nova_customer("/api/admin/dashboard") is True
    assert path_blocked_for_nova_customer("/api/admin/metrics") is True
    assert path_blocked_for_nova_customer("/api/admin/unknown-platform-endpoint") is True
    assert path_blocked_for_nova_customer("/api/nova/today/dashboard") is False
    assert path_blocked_for_nova_customer("/nova/workspace") is False
    assert path_blocked_for_nova_customer("/nova/payments/readiness") is True
    assert path_blocked_for_nova_customer("/workspace") is True
    assert path_blocked_for_nova_customer("/app") is True
    assert path_blocked_for_nova_customer("/nova/freight") is True
    assert path_blocked_for_nova_customer("/nova/accounting") is False
    assert path_blocked_for_nova_customer("/nova/accounting/aging") is False
    assert path_blocked_for_nova_customer("/nova/accounting/trends") is False


def test_nova_saas_admin_cannot_access_platform_admin_apis() -> None:
    fake = FakeNovaSaasStripeClient()
    set_nova_saas_stripe_override(fake)
    try:
        client = _client()
        payload = _signup_payload()
        _activate(client, fake, payload=payload)
        login = client.post(
            "/api/auth/login",
            json={"email": payload["email"], "password": payload["password"]},
        )
        assert login.status_code == 200, login.text
        customer = {"Authorization": f"Bearer {login.json()['access_token']}"}
        internal = client.post(
            "/api/auth/login",
            json={"email": "admin@amicor.local", "password": SEED_PASSWORD},
        )
        assert internal.status_code == 200, internal.text
        admin = {"Authorization": f"Bearer {internal.json()['access_token']}"}

        admin_paths = sorted(
            {
                str(getattr(route, "path", "") or "")
                for route in app.routes
                if str(getattr(route, "path", "") or "").startswith("/api/admin")
            }
        )
        assert "/api/admin/dashboard" in admin_paths
        assert "/api/admin/metrics" in admin_paths
        for path in admin_paths:
            denied = client.get(path, headers=customer)
            assert denied.status_code == 403, f"{path} {denied.status_code} {denied.text}"
            assert "Nova customer access is limited to AMICOR Nova." in denied.text
            allowed = client.get(path, headers=admin)
            assert allowed.status_code == 200, f"{path} {allowed.status_code} {allowed.text}"

        unknown = client.get("/api/admin/not-a-real-platform-endpoint", headers=customer)
        assert unknown.status_code == 403
        today = client.get("/api/nova/today/dashboard", headers=customer)
        assert today.status_code == 200, today.text
    finally:
        set_nova_saas_stripe_override(None)


def _completed_webhook(client: TestClient, session: dict, event_id: str):
    return client.post(
        "/api/nova/signup/stripe/webhook",
        json={
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {"object": session},
        },
    )


def _counts_for_email(email: str, signup_id: str) -> dict[str, int]:
    with SessionLocal() as db:
        return {
            "users": int(db.query(UserModel).filter(UserModel.email == email).count()),
            "tenants": int(
                db.query(NovaCustomerTenant).filter(NovaCustomerTenant.signup_id == signup_id).count()
            ),
        }


def test_founding_schedule_uses_current_stripe_duration_api() -> None:
    founding = billing_plan(founding_eligible=True)
    catalog = {
        FOUNDING_PRICE_LOOKUP: "price_nova_founding_test",
        STANDARD_PRICE_LOOKUP: "price_nova_standard_test",
    }
    phases = build_stripe_schedule_phases(founding, catalog=catalog, start_date=1_700_000_000, trial_end=1_700_604_800)
    assert len(phases) == 3
    assert phases[0]["start_date"] == 1_700_000_000
    assert phases[0]["end_date"] == 1_700_604_800
    assert phases[0]["trial_end"] == 1_700_604_800
    assert "duration" not in phases[0]
    assert phases[1]["duration"] == {"interval": "month", "interval_count": 3}
    assert "iterations" not in phases[0]
    assert "iterations" not in phases[1]
    assert "iterations" not in phases[2]
    assert phases[0]["items"][0]["price"] == "price_nova_founding_test"
    assert phases[1]["items"][0]["price"] == "price_nova_founding_test"
    assert phases[2]["items"][0]["price"] == "price_nova_standard_test"
    assert expected_unit_amount(founding=True, paid_month_index=3) == 5900
    assert expected_unit_amount(founding=True, paid_month_index=4) == 9900


def test_existing_schedule_is_updated_instead_of_recreated() -> None:
    fake = FakeNovaSaasStripeClient()
    set_nova_saas_stripe_override(fake)
    try:
        client = _client()
        payload = _signup_payload()
        created = client.post("/api/nova/signup", json=payload)
        assert created.status_code == 200, created.text
        assert created.json()["founding_eligible"] is True
        session = fake.complete_session(created.json()["checkout_session_id"])
        attached = fake.attach_partial_schedule(str(session["subscription"]))
        webhook = _completed_webhook(client, session, f"evt_existing_{uuid4()[:12]}")
        assert webhook.status_code == 200, webhook.text
        assert webhook.json()["activated"] is True
        assert fake.schedule_create_calls == 0
        assert fake.schedule_update_calls == 1
        assert len(fake.schedules) == 1
        assert fake.schedules[0]["id"] == attached["id"]
        assert len(fake.last_stripe_phases) == 3
        assert "duration" not in fake.last_stripe_phases[0]
        assert fake.last_stripe_phases[1]["duration"] == {"interval": "month", "interval_count": 3}
        assert "iterations" not in fake.last_stripe_phases[0]
        assert "iterations" not in fake.last_stripe_phases[1]
        assert "iterations" not in fake.last_stripe_phases[2]
        status = client.get(f"/api/nova/signup/{created.json()['signup_id']}").json()
        assert status["status"] == "trialing"
        assert status["founding_slot"] == created.json()["founding_slot"]
    finally:
        set_nova_saas_stripe_override(None)


def test_retry_after_partial_schedule_creation_succeeds() -> None:
    fake = FakeNovaSaasStripeClient()
    fake.fail_next_update = True
    set_nova_saas_stripe_override(fake)
    try:
        client = _client()
        payload = _signup_payload(business_name=f"Nova Retry Courier {uuid4()[:8]}")
        created = client.post("/api/nova/signup", json=payload)
        assert created.status_code == 200, created.text
        assert created.json()["founding_eligible"] is True
        signup_id = created.json()["signup_id"]
        slot = created.json()["founding_slot"]
        session = fake.complete_session(created.json()["checkout_session_id"])
        event_id = f"evt_retry_{uuid4()[:12]}"
        first = _completed_webhook(client, session, event_id)
        assert first.status_code == 503, first.text
        assert "iterations" in first.text or "schedule" in first.text.lower()
        assert fake.schedule_create_calls == 1
        assert fake.schedule_update_calls == 0
        assert len(fake.schedules) == 1
        assert client.get(f"/api/nova/signup/{signup_id}").json()["status"] == "checkout_open"
        assert _counts_for_email(payload["email"], signup_id)["tenants"] == 0

        second = _completed_webhook(client, session, event_id)
        assert second.status_code == 200, second.text
        assert second.json()["activated"] is True
        assert fake.schedule_create_calls == 1
        assert fake.schedule_update_calls == 1
        assert len(fake.schedules) == 1
        assert fake.last_stripe_phases[0]["duration"] == {"interval": "month", "interval_count": 3}
        status = client.get(f"/api/nova/signup/{signup_id}").json()
        assert status["status"] == "trialing"
        assert status["founding_slot"] == slot
        counts = _counts_for_email(payload["email"], signup_id)
        assert counts["tenants"] == 1
        assert counts["users"] == 1
        with SessionLocal() as db:
            event_rows = (
                db.query(NovaSignupWebhookEvent)
                .filter(NovaSignupWebhookEvent.stripe_event_id == event_id)
                .all()
            )
            assert len(event_rows) == 1
            assert event_rows[0].processing_result == "activated"
    finally:
        set_nova_saas_stripe_override(None)


def test_duplicate_checkout_completed_webhook_is_idempotent() -> None:
    fake = FakeNovaSaasStripeClient()
    set_nova_saas_stripe_override(fake)
    try:
        client = _client()
        payload = _signup_payload(business_name=f"Nova Dup Courier {uuid4()[:8]}")
        created = client.post("/api/nova/signup", json=payload)
        assert created.status_code == 200, created.text
        assert created.json()["founding_eligible"] is True
        signup_id = created.json()["signup_id"]
        session = fake.complete_session(created.json()["checkout_session_id"])
        event_id = f"evt_dup_{uuid4()[:12]}"
        first = _completed_webhook(client, session, event_id)
        assert first.status_code == 200, first.text
        first_counts = _counts_for_email(payload["email"], signup_id)
        assert first_counts["tenants"] == 1
        assert first_counts["users"] == 1
        create_calls = fake.schedule_create_calls
        update_calls = fake.schedule_update_calls

        second = _completed_webhook(client, session, event_id)
        assert second.status_code == 200, second.text
        assert second.json().get("duplicate") is True
        assert fake.schedule_create_calls == create_calls
        assert fake.schedule_update_calls == update_calls
        assert len(fake.schedules) == 1
        second_counts = _counts_for_email(payload["email"], signup_id)
        assert second_counts == first_counts
        with SessionLocal() as db:
            assert (
                db.query(NovaSignupWebhookEvent)
                .filter(NovaSignupWebhookEvent.stripe_event_id == event_id)
                .count()
                == 1
            )
            assert (
                db.query(NovaCustomerTenant).filter(NovaCustomerTenant.signup_id == signup_id).count()
                == 1
            )
            assert db.query(UserModel).filter(UserModel.email == payload["email"]).count() == 1
    finally:
        set_nova_saas_stripe_override(None)



def test_invoice_paid_routes_by_subscription_when_invoice_metadata_is_empty() -> None:
    fake = FakeNovaSaasStripeClient()
    set_nova_saas_stripe_override(fake)
    try:
        client = _client()
        payload = _signup_payload()
        activated = _activate(client, fake, payload=payload)
        signup_id = activated["signup"]["signup_id"]

        with SessionLocal() as db:
            row = db.get(NovaSignupAccount, signup_id)
            assert row is not None
            subscription_id = row.stripe_subscription_id
            assert subscription_id

        paid = client.post(
            "/api/nova/signup/stripe/webhook",
            json={
                "id": f"evt_paid_subscription_route_{uuid4()[:8]}",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_subscription_route_test",
                        "billing_reason": "subscription_cycle",
                        "amount_paid": 5900,
                        "metadata": {},
                        "subscription": subscription_id,
                    }
                },
            },
        )
        assert paid.status_code == 200, paid.text
        body = paid.json()
        assert body["result"] == "paid"
        assert body["paid_activated"] is True
        assert body["paid_month_index"] == 1
        assert body["expected_unit_amount"] == 5900

        with SessionLocal() as db:
            row = db.get(NovaSignupAccount, signup_id)
            assert row is not None
            assert row.status == "active"
            assert row.paid_month_index == 1
            assert row.current_unit_amount == 5900
    finally:
        set_nova_saas_stripe_override(None)


def test_invoice_parent_subscription_metadata_can_resolve_signup() -> None:
    from app.core.nova.signup.service import _signup_id_from_event

    signup_id = f"signup_{uuid4()[:8]}"
    obj = {
        "metadata": {},
        "parent": {
            "subscription_details": {
                "metadata": {
                    "nova_signup_id": signup_id,
                    "nova_product": "nova_saas",
                }
            }
        },
    }
    assert _signup_id_from_event(obj) == signup_id
