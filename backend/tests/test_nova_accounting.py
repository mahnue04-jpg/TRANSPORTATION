"""Nova V2 read-only accounting summary. Does not write financial records in production."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
ACCT_HTML = (STATIC / "nova-accounting" / "index.html").read_text(encoding="utf-8")
ACCT_JS = (STATIC / "nova-accounting" / "accounting.js").read_text(encoding="utf-8")
ACCT_CSS = (STATIC / "nova-accounting" / "accounting.css").read_text(encoding="utf-8")
TODAY_HTML = (STATIC / "nova-today" / "index.html").read_text(encoding="utf-8")
HOME_HTML = (STATIC / "nova-home" / "index.html").read_text(encoding="utf-8")
HOME_JS = (STATIC / "nova-home" / "home.js").read_text(encoding="utf-8")
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
FROZEN_V1 = [
    STATIC / "nova-home" / "index.html",
    STATIC / "nova-home" / "home.js",
    STATIC / "nova-workspace" / "workspace.js",
    STATIC / "nova-communications" / "communications.js",
    STATIC / "nova-government" / "government.js",
    STATIC / "nova-business" / "business.js",
    ROOT / "app" / "core" / "nova" / "router.py",
    ROOT / "app" / "core" / "nova" / "service.py",
]


@pytest.fixture(scope="module")
def client() -> TestClient:
    from app.modules.payments.models import ensure_payments_test_schema

    ensure_auth_schema()
    seed_default_users()
    ensure_payments_test_schema()
    return TestClient(app)


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> tuple[dict[str, str], str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, str(body["organization_id"])


def _counts() -> dict[str, int]:
    from app.core.nova.freight.models import NovaFreightInvoice, NovaFreightShipment
    from app.modules.health_isf.models import HealthISFRide
    from app.modules.payments.models import AmicorCustomerPayment
    from app.modules.platform_ops.models import PlatformDriverOnboardingApplication

    with SessionLocal() as db:
        return {
            "freight_shipments": db.query(NovaFreightShipment).count(),
            "freight_invoices": db.query(NovaFreightInvoice).count(),
            "health_rides": db.query(HealthISFRide).count(),
            "customer_payments": db.query(AmicorCustomerPayment).count(),
            "driver_001": db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.internal_driver_number == "DRV-001")
            .count(),
        }


def _metric(body: dict, key: str) -> dict:
    return next(row for row in body["metrics"] if row["key"] == key)


def test_nova_accounting_page_and_layout() -> None:
    assert "Accounting summary" in ACCT_HTML
    assert "Confirmed customer payments" in ACCT_HTML
    assert "Pending customer payments" in ACCT_HTML
    assert "Completed-trip calculated ride totals" in ACCT_HTML
    assert "Freight paid invoice totals" in ACCT_HTML
    assert "Stripe remains TEST" in ACCT_HTML
    assert 'name="viewport"' in ACCT_HTML
    assert "@media (max-width: 720px)" in ACCT_CSS
    assert "@media (min-width: 1280px)" in ACCT_CSS
    assert "minmax(220px, 1fr)" in ACCT_CSS
    assert "min-height: 44px" in ACCT_CSS
    assert "/api/nova/accounting/summary" in ACCT_JS
    assert "sk_live" not in ACCT_JS
    assert "pk_live" not in ACCT_JS
    assert "customer_id" not in ACCT_JS
    assert "passenger_name" not in ACCT_JS
    assert "routing" not in ACCT_JS.lower()
    assert 'href="/nova/accounting">Accounting</a>' in TODAY_HTML


def test_nova_accounting_auth_and_refuses(client: TestClient) -> None:
    page = client.get("/nova/accounting")
    assert page.status_code == 200
    assert "Accounting summary" in page.text
    assert client.get("/api/nova/accounting/summary").status_code == 401
    headers, _org = _headers(client)
    assert client.post("/api/nova/accounting/pay", headers=headers).status_code == 403
    assert client.post("/api/nova/accounting/payout", headers=headers).status_code == 403
    assert client.post("/api/nova/accounting/invoice", headers=headers).status_code == 403
    assert client.post("/api/nova/accounting/refund", headers=headers).status_code == 403
    driver, _ = _headers(client, "driver@amicor.local")
    assert client.get("/api/nova/accounting/summary", headers=driver).status_code == 403
    cross = client.get("/api/nova/accounting/summary", headers=headers, params={"organization_id": "org-not-the-caller"})
    assert cross.status_code == 403


def test_nova_accounting_aggregation_privacy_and_isolation(client: TestClient) -> None:
    from app.core.nova.freight.models import NovaFreightInvoice
    from app.modules.payments.models import PAYMENT_PENDING, PAYMENT_SUCCEEDED, AmicorCustomerPayment

    owner, org_id = _headers(client, "dispatcher@amicor.local")
    other, _ = _headers(client, "staff@amicor.local")
    before = _counts()
    baseline = client.get("/api/nova/accounting/summary", headers=owner)
    assert baseline.status_code == 200, baseline.text
    base_confirmed = float(_metric(baseline.json(), "confirmed_customer_payments")["amount_usd"] or 0)
    base_pending = float(_metric(baseline.json(), "pending_customer_payments")["amount_usd"] or 0)
    base_freight_paid = float(_metric(baseline.json(), "freight_paid_invoice_totals")["amount_usd"] or 0)
    base_freight_unpaid = float(_metric(baseline.json(), "freight_unpaid_invoice_totals")["amount_usd"] or 0)
    paid_id = "pi_acct_" + uuid4().replace("-", "")[:10]
    pending_id = "pi_acct_" + uuid4().replace("-", "")[:10]
    other_org_id = "org-acct-" + uuid4().replace("-", "")[:8]
    invoice_paid = "NFI-ACCT-" + uuid4().replace("-", "")[:8].upper()
    invoice_unpaid = "NFI-ACCT-" + uuid4().replace("-", "")[:8].upper()

    with SessionLocal() as db:
        db.add(
            AmicorCustomerPayment(
                id=uuid4(),
                service_type="RIDE",
                internal_service_id="acct-paid",
                organization_id=org_id,
                stripe_payment_intent_id=paid_id,
                amount_minor=2500,
                payment_status=PAYMENT_SUCCEEDED,
            )
        )
        db.add(
            AmicorCustomerPayment(
                id=uuid4(),
                service_type="DELIVERY",
                internal_service_id="acct-pending",
                organization_id=org_id,
                stripe_payment_intent_id=pending_id,
                amount_minor=1800,
                payment_status=PAYMENT_PENDING,
            )
        )
        db.add(
            AmicorCustomerPayment(
                id=uuid4(),
                service_type="RIDE",
                internal_service_id="acct-other-org",
                organization_id=other_org_id,
                stripe_payment_intent_id="pi_acct_other_" + uuid4().replace("-", "")[:8],
                amount_minor=9900,
                payment_status=PAYMENT_SUCCEEDED,
            )
        )
        db.add(
            NovaFreightInvoice(
                invoice_id=invoice_paid,
                shipment_id="NFS-ACCT-PAID",
                organization_id=org_id,
                total_amount=Decimal("40.00"),
                total_amount_minor=4000,
                invoice_status="paid",
                idempotency_key="acct-paid-" + invoice_paid,
            )
        )
        db.add(
            NovaFreightInvoice(
                invoice_id=invoice_unpaid,
                shipment_id="NFS-ACCT-UNPAID",
                organization_id=org_id,
                total_amount=Decimal("15.50"),
                total_amount_minor=1550,
                invoice_status="payment_pending",
                idempotency_key="acct-unpaid-" + invoice_unpaid,
            )
        )
        db.commit()

    dash = client.get("/api/nova/accounting/summary", headers=owner)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["stripe_mode"] == "TEST"
    keys = [row["key"] for row in body["metrics"]]
    assert keys == [
        "confirmed_customer_payments",
        "pending_customer_payments",
        "completed_trip_calculated_ride_totals",
        "completed_trip_calculated_platform_share",
        "freight_paid_invoice_totals",
        "freight_unpaid_invoice_totals",
    ]
    confirmed = _metric(body, "confirmed_customer_payments")
    pending = _metric(body, "pending_customer_payments")
    freight_paid = _metric(body, "freight_paid_invoice_totals")
    freight_unpaid = _metric(body, "freight_unpaid_invoice_totals")
    assert confirmed["status"] == "ok"
    assert confirmed["state"] == "confirmed"
    assert confirmed["amount_usd"] == pytest.approx(base_confirmed + 25.0)
    assert pending["amount_usd"] == pytest.approx(base_pending + 18.0)
    assert pending["state"] == "pending"
    assert freight_paid["amount_usd"] == pytest.approx(base_freight_paid + 40.0)
    assert freight_unpaid["amount_usd"] == pytest.approx(base_freight_unpaid + 15.5)
    assert freight_unpaid["state"] == "pending"
    blob = json.dumps(body)
    for needle in (
        "passenger_name",
        "pickup_address",
        "customer_id",
        "driver_id",
        paid_id,
        "routing",
        "ssn",
        "bank",
        "sk_live",
    ):
        assert needle not in blob

    admin_rev = client.get("/api/health-isf/operations/admin-revenue", headers=owner)
    if admin_rev.status_code == 200:
        calc = _metric(body, "completed_trip_calculated_ride_totals")
        share = _metric(body, "completed_trip_calculated_platform_share")
        assert calc["amount_usd"] == admin_rev.json()["ride_revenue_total_usd"]
        assert share["amount_usd"] == admin_rev.json()["platform_revenue_total_usd"]
        assert calc["state"] == "calculated"

    other_dash = client.get("/api/nova/accounting/summary", headers=other)
    assert other_dash.status_code == 200
    other_confirmed = _metric(other_dash.json(), "confirmed_customer_payments")
    assert other_confirmed["amount_usd"] == pytest.approx(base_confirmed + 25.0)
    assert 99.0 not in [row.get("amount_usd") for row in other_dash.json()["metrics"]]

    after = _counts()
    assert after["health_rides"] == before["health_rides"]
    assert after["freight_shipments"] == before["freight_shipments"]
    assert after["driver_001"] == before["driver_001"]
    with SessionLocal() as db:
        db.query(AmicorCustomerPayment).filter(
            AmicorCustomerPayment.stripe_payment_intent_id.in_([paid_id, pending_id])
            | (AmicorCustomerPayment.organization_id == other_org_id)
        ).delete(synchronize_session=False)
        db.query(NovaFreightInvoice).filter(
            NovaFreightInvoice.invoice_id.in_([invoice_paid, invoice_unpaid])
        ).delete(synchronize_session=False)
        db.commit()


def test_nova_accounting_fail_soft(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("payment ledger unavailable")

    monkeypatch.setattr("app.core.nova.accounting.service._confirmed_customer_payments", boom)
    headers, _org = _headers(client)
    dash = client.get("/api/nova/accounting/summary", headers=headers)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    confirmed = _metric(body, "confirmed_customer_payments")
    pending = _metric(body, "pending_customer_payments")
    assert confirmed["status"] == "unavailable"
    assert confirmed["amount_usd"] is None
    assert pending["status"] == "ok"
    assert len(body["metrics"]) == 6


def test_nova_accounting_does_not_change_frozen_boundaries(client: TestClient) -> None:
    before = _counts()
    headers, _org = _headers(client)
    client.get("/nova/accounting")
    client.get("/nova")
    client.get("/nova/today")
    client.get("/api/nova/accounting/summary", headers=headers)
    after = _counts()
    assert after["health_rides"] == before["health_rides"]
    assert after["freight_shipments"] == before["freight_shipments"]
    assert after["driver_001"] == before["driver_001"]
    assert "DRV-001" not in ACCT_HTML + ACCT_JS
    assert "Driver 001" not in ACCT_HTML + ACCT_JS
    assert "nova-accounting" not in OPS_JS
    assert "/api/nova/accounting" not in HOME_JS
    for path in FROZEN_V1:
        text = path.read_text(encoding="utf-8")
        assert "nova_accounting" not in text
        if path.name == "index.html" and "nova-home" in str(path):
            assert "/api/nova/accounting" not in text
