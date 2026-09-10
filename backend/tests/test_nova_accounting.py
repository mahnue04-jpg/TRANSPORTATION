"""Nova V2 read-only accounting summary. Does not write financial records in production."""
from __future__ import annotations

import json
from datetime import timedelta
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
    assert 'data-window="all"' in ACCT_HTML
    assert 'data-window="30d"' in ACCT_HTML
    assert 'data-window="7d"' in ACCT_HTML
    assert "All time" in ACCT_HTML
    assert "Last 30 days" in ACCT_HTML
    assert "Last 7 days" in ACCT_HTML
    assert "All time only" in ACCT_HTML
    assert 'name="viewport"' in ACCT_HTML
    assert "@media (max-width: 720px)" in ACCT_CSS
    assert "@media (min-width: 1280px)" in ACCT_CSS
    assert "minmax(220px, 1fr)" in ACCT_CSS
    assert "min-height: 44px" in ACCT_CSS
    assert ".window-controls" in ACCT_CSS
    assert "/api/nova/accounting/summary" in ACCT_JS
    assert "window=" in ACCT_JS
    assert "window_label" in ACCT_JS
    assert "source_note" in ACCT_JS
    assert "sk_live" not in ACCT_JS
    assert "pk_live" not in ACCT_JS
    assert "customer_id" not in ACCT_JS
    assert "passenger_name" not in ACCT_JS
    assert "routing" not in ACCT_JS.lower()
    assert 'href="/nova/accounting">Accounting</a>' in TODAY_HTML
    assert 'href="/nova/accounting/aging">Aging</a>' in ACCT_HTML
    assert 'href="/nova/accounting/aging">Aging</a>' in TODAY_HTML


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
    assert client.post("/api/nova/accounting/collect", headers=headers).status_code == 403
    assert client.post("/api/nova/accounting/remind", headers=headers).status_code == 403
    assert client.post("/api/nova/accounting/export", headers=headers).status_code == 403
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
    assert body["window"] == "all"
    assert body["window_label"] == "All time"
    assert body["window_cutoff_utc"] is None
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
    assert confirmed["window"] == "all"
    assert confirmed["complete"] is True
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

    calc = _metric(body, "completed_trip_calculated_ride_totals")
    share = _metric(body, "completed_trip_calculated_platform_share")
    assert calc["state"] == "calculated"
    assert share["state"] == "calculated"
    assert calc["complete"] is True
    admin_rev = client.get("/api/health-isf/operations/admin-revenue", headers=owner)
    if admin_rev.status_code == 200 and int(admin_rev.json().get("completed_trip_count") or 0) < 1000:
        assert calc["amount_usd"] == admin_rev.json()["ride_revenue_total_usd"]
        assert share["amount_usd"] == admin_rev.json()["platform_revenue_total_usd"]

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


def test_nova_accounting_window_helpers() -> None:
    from app.core.nova.accounting.service import (
        ALL_TIME_ONLY_LABEL,
        NovaAccountingError,
        parse_window,
        window_cutoff,
        window_display,
    )
    from app.helpers import now

    assert parse_window(None) == "all"
    assert parse_window("all") == "all"
    assert parse_window("30d") == "30d"
    assert parse_window("7d") == "7d"
    with pytest.raises(NovaAccountingError) as exc:
        parse_window("90d")
    assert exc.value.status_code == 400
    stamp = now()
    assert window_cutoff("all", at=stamp) is None
    assert window_cutoff("7d", at=stamp) == stamp - timedelta(days=7)
    assert window_cutoff("30d", at=stamp) == stamp - timedelta(days=30)
    label, supported = window_display("30d", timestamp_field=None)
    assert label == ALL_TIME_ONLY_LABEL
    assert supported is False
    label_ok, supported_ok = window_display("7d", timestamp_field="amicor_customer_payments.paid_at")
    assert label_ok == "Last 7 days"
    assert supported_ok is True


def test_nova_accounting_time_windows_and_boundaries(client: TestClient) -> None:
    from app.core.nova.freight.models import NovaFreightInvoice
    from app.helpers import now
    from app.modules.payments.models import PAYMENT_PENDING, PAYMENT_SUCCEEDED, AmicorCustomerPayment

    owner, org_id = _headers(client, "dispatcher@amicor.local")
    other, _ = _headers(client, "staff@amicor.local")
    before = _counts()
    stamp = now()
    paid_recent = "pi_win_" + uuid4().replace("-", "")[:10]
    paid_mid = "pi_win_" + uuid4().replace("-", "")[:10]
    paid_old = "pi_win_" + uuid4().replace("-", "")[:10]
    paid_null = "pi_win_" + uuid4().replace("-", "")[:10]
    pending_recent = "pi_win_" + uuid4().replace("-", "")[:10]
    pending_old = "pi_win_" + uuid4().replace("-", "")[:10]
    other_org_id = "org-win-" + uuid4().replace("-", "")[:8]
    other_pi = "pi_win_other_" + uuid4().replace("-", "")[:8]
    inv_paid_recent = "NFI-WIN-" + uuid4().replace("-", "")[:8].upper()
    inv_paid_old = "NFI-WIN-" + uuid4().replace("-", "")[:8].upper()
    inv_unpaid_recent = "NFI-WIN-" + uuid4().replace("-", "")[:8].upper()
    inv_unpaid_old = "NFI-WIN-" + uuid4().replace("-", "")[:8].upper()
    base_all = client.get("/api/nova/accounting/summary", headers=owner, params={"window": "all"})
    base_30 = client.get("/api/nova/accounting/summary", headers=owner, params={"window": "30d"})
    base_7 = client.get("/api/nova/accounting/summary", headers=owner, params={"window": "7d"})
    assert base_all.status_code == 200
    assert base_30.status_code == 200
    assert base_7.status_code == 200

    def _amt(body, key):
        return float(_metric(body, key)["amount_usd"] or 0)

    with SessionLocal() as db:
        db.add(
            AmicorCustomerPayment(
                id=uuid4(),
                service_type="RIDE",
                internal_service_id="win-recent",
                organization_id=org_id,
                stripe_payment_intent_id=paid_recent,
                amount_minor=2100,
                payment_status=PAYMENT_SUCCEEDED,
                paid_at=stamp - timedelta(days=2),
                created_at=stamp - timedelta(days=2),
            )
        )
        db.add(
            AmicorCustomerPayment(
                id=uuid4(),
                service_type="RIDE",
                internal_service_id="win-mid",
                organization_id=org_id,
                stripe_payment_intent_id=paid_mid,
                amount_minor=3200,
                payment_status=PAYMENT_SUCCEEDED,
                paid_at=stamp - timedelta(days=10),
                created_at=stamp - timedelta(days=10),
            )
        )
        db.add(
            AmicorCustomerPayment(
                id=uuid4(),
                service_type="RIDE",
                internal_service_id="win-old",
                organization_id=org_id,
                stripe_payment_intent_id=paid_old,
                amount_minor=4300,
                payment_status=PAYMENT_SUCCEEDED,
                paid_at=stamp - timedelta(days=40),
                created_at=stamp - timedelta(days=40),
            )
        )
        db.add(
            AmicorCustomerPayment(
                id=uuid4(),
                service_type="RIDE",
                internal_service_id="win-null-paid",
                organization_id=org_id,
                stripe_payment_intent_id=paid_null,
                amount_minor=1100,
                payment_status=PAYMENT_SUCCEEDED,
                paid_at=None,
                created_at=stamp - timedelta(days=1),
            )
        )
        db.add(
            AmicorCustomerPayment(
                id=uuid4(),
                service_type="DELIVERY",
                internal_service_id="win-pending-recent",
                organization_id=org_id,
                stripe_payment_intent_id=pending_recent,
                amount_minor=1500,
                payment_status=PAYMENT_PENDING,
                created_at=stamp - timedelta(days=1),
            )
        )
        db.add(
            AmicorCustomerPayment(
                id=uuid4(),
                service_type="DELIVERY",
                internal_service_id="win-pending-old",
                organization_id=org_id,
                stripe_payment_intent_id=pending_old,
                amount_minor=2600,
                payment_status=PAYMENT_PENDING,
                created_at=stamp - timedelta(days=40),
            )
        )
        db.add(
            AmicorCustomerPayment(
                id=uuid4(),
                service_type="RIDE",
                internal_service_id="win-other-org",
                organization_id=other_org_id,
                stripe_payment_intent_id=other_pi,
                amount_minor=8800,
                payment_status=PAYMENT_SUCCEEDED,
                paid_at=stamp - timedelta(days=1),
            )
        )
        db.add(
            NovaFreightInvoice(
                invoice_id=inv_paid_recent,
                shipment_id="NFS-WIN-PAID-R",
                organization_id=org_id,
                total_amount=Decimal("12.00"),
                total_amount_minor=1200,
                invoice_status="paid",
                paid_at=stamp - timedelta(days=3),
                created_at=stamp - timedelta(days=3),
                idempotency_key="win-paid-r-" + inv_paid_recent,
            )
        )
        db.add(
            NovaFreightInvoice(
                invoice_id=inv_paid_old,
                shipment_id="NFS-WIN-PAID-O",
                organization_id=org_id,
                total_amount=Decimal("22.00"),
                total_amount_minor=2200,
                invoice_status="paid",
                paid_at=stamp - timedelta(days=45),
                created_at=stamp - timedelta(days=45),
                idempotency_key="win-paid-o-" + inv_paid_old,
            )
        )
        db.add(
            NovaFreightInvoice(
                invoice_id=inv_unpaid_recent,
                shipment_id="NFS-WIN-UNPAID-R",
                organization_id=org_id,
                total_amount=Decimal("8.25"),
                total_amount_minor=825,
                invoice_status="ready",
                created_at=stamp - timedelta(days=2),
                idempotency_key="win-unpaid-r-" + inv_unpaid_recent,
            )
        )
        db.add(
            NovaFreightInvoice(
                invoice_id=inv_unpaid_old,
                shipment_id="NFS-WIN-UNPAID-O",
                organization_id=org_id,
                total_amount=Decimal("9.75"),
                total_amount_minor=975,
                invoice_status="draft",
                created_at=stamp - timedelta(days=50),
                idempotency_key="win-unpaid-o-" + inv_unpaid_old,
            )
        )
        db.commit()

    all_body = client.get("/api/nova/accounting/summary", headers=owner).json()
    d30 = client.get("/api/nova/accounting/summary", headers=owner, params={"window": "30d"}).json()
    d7 = client.get("/api/nova/accounting/summary", headers=owner, params={"window": "7d"}).json()
    bad = client.get("/api/nova/accounting/summary", headers=owner, params={"window": "90d"})
    assert bad.status_code == 400
    assert all_body["window"] == "all"
    assert d30["window"] == "30d"
    assert d7["window"] == "7d"
    assert d7["window_cutoff_utc"]
    assert _amt(all_body, "confirmed_customer_payments") == pytest.approx(_amt(base_all.json(), "confirmed_customer_payments") + 21 + 32 + 43 + 11)
    assert _amt(d30, "confirmed_customer_payments") == pytest.approx(_amt(base_30.json(), "confirmed_customer_payments") + 21 + 32)
    assert _amt(d7, "confirmed_customer_payments") == pytest.approx(_amt(base_7.json(), "confirmed_customer_payments") + 21)
    assert _amt(all_body, "pending_customer_payments") == pytest.approx(_amt(base_all.json(), "pending_customer_payments") + 15 + 26)
    assert _amt(d7, "pending_customer_payments") == pytest.approx(_amt(base_7.json(), "pending_customer_payments") + 15)
    assert _amt(all_body, "freight_paid_invoice_totals") == pytest.approx(_amt(base_all.json(), "freight_paid_invoice_totals") + 12 + 22)
    assert _amt(d7, "freight_paid_invoice_totals") == pytest.approx(_amt(base_7.json(), "freight_paid_invoice_totals") + 12)
    assert _amt(all_body, "freight_unpaid_invoice_totals") == pytest.approx(_amt(base_all.json(), "freight_unpaid_invoice_totals") + 8.25 + 9.75)
    assert _amt(d7, "freight_unpaid_invoice_totals") == pytest.approx(_amt(base_7.json(), "freight_unpaid_invoice_totals") + 8.25)
    for row in d7["metrics"]:
        assert row["state"] in {"confirmed", "pending", "calculated", "unavailable"}
        assert row["window_supported"] is True
        assert row["window_label"] == "Last 7 days"
        assert "total revenue" not in (row.get("label") or "").lower()
    blob = json.dumps(d7)
    for needle in (paid_recent, other_pi, "passenger_name", "customer_id", "driver_id", "routing", "ssn", "bank", "sk_live"):
        assert needle not in blob
    other_7 = client.get("/api/nova/accounting/summary", headers=other, params={"window": "7d"})
    assert other_7.status_code == 200
    assert 88.0 not in [row.get("amount_usd") for row in other_7.json()["metrics"]]
    cross = client.get(
        "/api/nova/accounting/summary",
        headers=owner,
        params={"window": "7d", "organization_id": "org-not-the-caller"},
    )
    assert cross.status_code == 403
    after = _counts()
    assert after["driver_001"] == before["driver_001"]
    assert after["health_rides"] == before["health_rides"]
    with SessionLocal() as db:
        db.query(AmicorCustomerPayment).filter(
            AmicorCustomerPayment.stripe_payment_intent_id.in_(
                [paid_recent, paid_mid, paid_old, paid_null, pending_recent, pending_old, other_pi]
            )
        ).delete(synchronize_session=False)
        db.query(NovaFreightInvoice).filter(
            NovaFreightInvoice.invoice_id.in_([inv_paid_recent, inv_paid_old, inv_unpaid_recent, inv_unpaid_old])
        ).delete(synchronize_session=False)
        db.commit()


def test_nova_accounting_does_not_truncate_over_1000(client: TestClient) -> None:
    from app.helpers import now
    from app.modules.payments.models import PAYMENT_SUCCEEDED, AmicorCustomerPayment

    owner, org_id = _headers(client, "dispatcher@amicor.local")
    baseline = client.get("/api/nova/accounting/summary", headers=owner, params={"window": "7d"})
    assert baseline.status_code == 200
    base = float(_metric(baseline.json(), "confirmed_customer_payments")["amount_usd"] or 0)
    base_count = int(_metric(baseline.json(), "confirmed_customer_payments")["count"] or 0)
    prefix = "pi_bulk_" + uuid4().replace("-", "")[:10]
    stamp = now()
    rows = [
        AmicorCustomerPayment(
            id=uuid4(),
            service_type="RIDE",
            internal_service_id=f"bulk-{index}",
            organization_id=org_id,
            stripe_payment_intent_id=f"{prefix}_{index:04d}",
            amount_minor=1,
            payment_status=PAYMENT_SUCCEEDED,
            paid_at=stamp - timedelta(hours=2),
            created_at=stamp - timedelta(hours=2),
        )
        for index in range(1001)
    ]
    with SessionLocal() as db:
        db.add_all(rows)
        db.commit()
    try:
        dash = client.get("/api/nova/accounting/summary", headers=owner, params={"window": "7d"})
        assert dash.status_code == 200, dash.text
        confirmed = _metric(dash.json(), "confirmed_customer_payments")
        assert confirmed["complete"] is True
        assert confirmed["count"] == base_count + 1001
        assert confirmed["amount_usd"] == pytest.approx(base + 10.01)
        assert confirmed["state"] == "confirmed"
        assert confirmed["window_label"] == "Last 7 days"
    finally:
        with SessionLocal() as db:
            db.query(AmicorCustomerPayment).filter(
                AmicorCustomerPayment.stripe_payment_intent_id.like(prefix + "%")
            ).delete(synchronize_session=False)
            db.commit()


def test_nova_accounting_window_auth_fail_soft_and_no_truncated_engine(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("trip ledger unavailable")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("admin-revenue truncated summary must not be used")

    monkeypatch.setattr("app.core.nova.accounting.service._completed_trip_ride", boom)
    monkeypatch.setattr(
        "app.modules.health_isf.financial_engine.TripFinancialEngine.get_admin_revenue_summary",
        forbidden,
    )
    headers, _org = _headers(client)
    assert client.get("/api/nova/accounting/summary", params={"window": "30d"}).status_code == 401
    driver, _ = _headers(client, "driver@amicor.local")
    assert client.get("/api/nova/accounting/summary", headers=driver, params={"window": "30d"}).status_code == 403
    dash = client.get("/api/nova/accounting/summary", headers=headers, params={"window": "30d"})
    assert dash.status_code == 200, dash.text
    body = dash.json()
    ride = _metric(body, "completed_trip_calculated_ride_totals")
    platform = _metric(body, "completed_trip_calculated_platform_share")
    confirmed = _metric(body, "confirmed_customer_payments")
    assert ride["status"] == "unavailable"
    assert ride["amount_usd"] is None
    assert ride["window_label"] == "Last 30 days"
    assert platform["status"] == "ok"
    assert confirmed["status"] == "ok"
    assert confirmed["state"] != platform["state"] or platform["state"] == "calculated"
    assert "total_revenue" not in json.dumps(body)
