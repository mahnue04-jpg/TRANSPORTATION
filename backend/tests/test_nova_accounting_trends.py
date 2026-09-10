"""Nova V2 read-only monthly accounting trends. Does not write financial records."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.helpers import now, uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TREND_HTML = (STATIC / "nova-accounting" / "trends.html").read_text(encoding="utf-8")
TREND_JS = (STATIC / "nova-accounting" / "trends.js").read_text(encoding="utf-8")
TREND_CSS = (STATIC / "nova-accounting" / "accounting.css").read_text(encoding="utf-8")
ACCT_HTML = (STATIC / "nova-accounting" / "index.html").read_text(encoding="utf-8")
AGING_HTML = (STATIC / "nova-accounting" / "aging.html").read_text(encoding="utf-8")
TODAY_HTML = (STATIC / "nova-today" / "index.html").read_text(encoding="utf-8")
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
    from app.core.nova.freight.models import NovaFreightInvoice
    from app.modules.health_isf.models import HealthISFRide
    from app.modules.payments.models import AmicorCustomerPayment
    from app.modules.platform_ops.models import PlatformDriverOnboardingApplication

    from sqlalchemy import text

    with SessionLocal() as db:
        return {
            "freight_shipments": int(db.execute(text("SELECT COUNT(*) FROM nova_freight_shipments")).scalar() or 0),
            "health_rides": db.query(HealthISFRide).count(),
            "customer_payments": db.query(AmicorCustomerPayment).count(),
            "driver_001": db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.internal_driver_number == "DRV-001")
            .count(),
        }


def _stream(body: dict, key: str) -> dict:
    return next(row for row in body["streams"] if row["key"] == key)


def _group(stream: dict, key: str) -> dict:
    return next(row for row in stream["groups"] if row["key"] == key)


def _usd(group: dict) -> dict:
    return next(row for row in group["currencies"] if row["currency"] == "USD")


def _month(slice_row: dict, key: str) -> dict:
    return next(row for row in slice_row["months"] if row["month"] == key)


def test_trends_page_layout_and_privacy() -> None:
    assert "Monthly financial trends" in TREND_HTML
    assert "Last 3 months" in TREND_HTML
    assert "Last 6 months" in TREND_HTML
    assert "Last 12 months" in TREND_HTML
    assert 'data-months="12"' in TREND_HTML
    assert "Month to date" in TREND_HTML
    assert "/api/nova/accounting/forecast" not in TREND_JS
    assert "chart.js" not in TREND_JS.lower()
    assert "<svg" in TREND_JS
    assert "customer_id" not in TREND_JS
    assert "invoice_id" not in TREND_JS
    assert "routing" not in TREND_JS.lower()
    assert "sk_live" not in TREND_JS
    assert ".trend-chart" in TREND_CSS
    assert "@media (max-width: 720px)" in TREND_CSS
    assert 'href="/nova">Nova Home</a>' in TREND_HTML
    assert 'href="/nova/today">Today</a>' in TREND_HTML
    assert 'href="/nova/accounting">Accounting</a>' in TREND_HTML
    assert 'href="/nova/accounting/aging">Aging</a>' in TREND_HTML
    assert 'href="/nova/accounting/trends"' in TREND_HTML
    assert 'href="/nova/accounting/trends">Trends</a>' in ACCT_HTML
    assert 'href="/nova/accounting/trends">Trends</a>' in AGING_HTML
    assert 'href="/nova/accounting/trends">Trends</a>' in TODAY_HTML
    assert 'name="viewport"' in TREND_HTML


def test_trends_month_helpers() -> None:
    from app.core.nova.accounting.trends import month_key, month_window, parse_months
    from app.core.nova.accounting.service import NovaAccountingError

    as_of = datetime(2026, 9, 10, 15, 30, tzinfo=timezone.utc)
    first, keys = month_window(as_of, 3)
    assert keys == ["2026-07", "2026-08", "2026-09"]
    assert first == datetime(2026, 7, 1, tzinfo=timezone.utc)
    _, keys12 = month_window(as_of, 12)
    assert len(keys12) == 12
    assert keys12[-1] == "2026-09"
    assert month_key(datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)) == "2026-08"
    assert month_key(datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)) == "2026-09"
    assert month_key(None) is None
    assert parse_months(None) == 12
    assert parse_months(3) == 3
    assert parse_months(6) == 6
    with pytest.raises(NovaAccountingError):
        parse_months(9)


def test_trends_auth_and_refuses(client: TestClient) -> None:
    page = client.get("/nova/accounting/trends")
    assert page.status_code == 200
    assert "Monthly financial trends" in page.text
    assert client.get("/api/nova/accounting/trends").status_code == 401
    headers, _org = _headers(client)
    assert client.post("/api/nova/accounting/forecast", headers=headers).status_code == 403
    assert client.post("/api/nova/accounting/collect", headers=headers).status_code == 403
    driver, _ = _headers(client, "driver@amicor.local")
    assert client.get("/api/nova/accounting/trends", headers=driver).status_code == 403
    cross = client.get("/api/nova/accounting/trends", headers=headers, params={"organization_id": "org-not-the-caller"})
    assert cross.status_code == 403
    bad = client.get("/api/nova/accounting/trends", headers=headers, params={"months": 9})
    assert bad.status_code == 400


def test_trends_windows_boundaries_currencies_and_privacy(client: TestClient) -> None:
    from app.core.nova.freight.models import NovaFreightInvoice
    from app.modules.payments.models import PAYMENT_PENDING, PAYMENT_SUCCEEDED, AmicorCustomerPayment

    owner, org_id = _headers(client)
    other, _ = _headers(client, "staff@amicor.local")
    before = _counts()
    as_of = now()
    current = as_of.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev = datetime(current.year if current.month > 1 else current.year - 1, current.month - 1 if current.month > 1 else 12, 1, tzinfo=timezone.utc)
    prev_end = current - timedelta(seconds=1)
    current_key = current.strftime("%Y-%m")
    prev_key = prev.strftime("%Y-%m")
    prefix = "pi_tr_" + uuid4().replace("-", "")[:8]
    other_org = "org-tr-" + uuid4().replace("-", "")[:8]
    ids = []
    invoices = []

    def pay(suffix, stamp, minor, status=PAYMENT_SUCCEEDED, org=org_id, currency="usd", paid=None):
        pi = f"{prefix}_{suffix}"
        ids.append(pi)
        return AmicorCustomerPayment(
            id=uuid4(),
            service_type="RIDE",
            internal_service_id=f"tr-{suffix}",
            organization_id=org,
            stripe_payment_intent_id=pi,
            amount_minor=minor,
            currency=currency,
            payment_status=status,
            created_at=stamp,
            paid_at=paid,
        )

    def invoice(suffix, stamp, amount, status, currency="USD", paid=None):
        invoice_id = "NFI-TR-" + suffix + uuid4().replace("-", "")[:6].upper()
        invoices.append(invoice_id)
        return NovaFreightInvoice(
            invoice_id=invoice_id,
            shipment_id="NFS-TR-" + suffix,
            organization_id=org_id,
            total_amount=Decimal(amount),
            total_amount_minor=int(Decimal(amount) * 100),
            currency=currency,
            invoice_status=status,
            created_at=stamp,
            paid_at=paid,
            idempotency_key="tr-" + invoice_id,
        )

    with SessionLocal() as db:
        db.add_all(
            [
                pay("cur", current + timedelta(days=1), 2500, paid=current + timedelta(days=1)),
                pay("cur2", current + timedelta(days=2), 2500, paid=current + timedelta(days=2)),
                pay("prev", prev_end, 4000, paid=prev_end),
                pay("eur", current + timedelta(hours=2), 300, paid=current + timedelta(hours=2), currency="eur"),
                pay("pend", current + timedelta(days=1), 1800, status=PAYMENT_PENDING),
                pay("pendprev", prev + timedelta(days=2), 900, status=PAYMENT_PENDING),
                pay("missing", current + timedelta(days=1), 7700, paid=None),
                pay("nullorg", current + timedelta(days=1), 9900, org=None, paid=current + timedelta(days=1)),
                pay("other", current + timedelta(days=1), 8800, org=other_org, paid=current + timedelta(days=1)),
                invoice("P", current + timedelta(days=1), "11.00", "paid", paid=current + timedelta(days=1)),
                invoice("D", current + timedelta(days=1), "6.00", "draft"),
                invoice("R", prev + timedelta(days=3), "7.00", "ready"),
                invoice("PP", current + timedelta(days=1), "8.00", "payment_pending"),
                invoice("F", current + timedelta(days=1), "9.00", "failed"),
                invoice("CAD", current + timedelta(days=1), "5.00", "draft", currency="CAD"),
            ]
        )
        db.commit()
    try:
        default = client.get("/api/nova/accounting/trends", headers=owner)
        assert default.status_code == 200, default.text
        body12 = default.json()
        assert body12["months"] == 12
        assert len(body12["streams"]) == 6
        assert body12["streams"][0]["key"] != body12["streams"][4]["key"]
        confirmed = _group(_stream(body12, "confirmed_customer_payments"), "confirmed_customer_payments")
        usd = _usd(confirmed)
        assert len(usd["months"]) == 12
        assert usd["months"][-1]["month_to_date"] is True
        assert "Month to date" in usd["months"][-1]["label"]
        assert _month(usd, current_key)["amount"] == pytest.approx(50.0)
        assert _month(usd, current_key)["count"] == 2
        assert _month(usd, prev_key)["amount"] == pytest.approx(40.0)
        empty_keys = [row["month"] for row in usd["months"] if row["month"] not in {current_key, prev_key}]
        if empty_keys:
            assert _month(usd, empty_keys[0])["amount"] == 0.0
            assert _month(usd, empty_keys[0])["count"] == 0
        assert usd["excluded_missing_timestamp_count"] >= 1
        eur = next(row for row in confirmed["currencies"] if row["currency"] == "EUR")
        assert eur["months"][-1]["amount"] == pytest.approx(3.0)
        pending = _group(_stream(body12, "current_pending_customer_payments"), "current_pending_customer_payments")
        assert pending["label"] == "Current pending payments by creation month"
        assert pending["cohort"] == "current_pending_by_created_month"
        assert "not a historical month-end balance" in pending["source_note"].lower()
        pend_usd = _usd(pending)
        assert _month(pend_usd, current_key)["amount"] == pytest.approx(18.0)
        ride = _stream(body12, "completed_trip_calculated_ride_totals")
        share = _stream(body12, "completed_trip_calculated_platform_share")
        assert ride["groups"][0]["state"] == "calculated"
        assert share["groups"][0]["state"] == "calculated"
        freight_paid = _group(_stream(body12, "freight_paid_invoice_totals"), "freight_paid_invoice_totals")
        assert _month(_usd(freight_paid), current_key)["amount"] == pytest.approx(11.0)
        unpaid = _stream(body12, "current_unpaid_freight_invoices")
        groups = {row["key"]: row for row in unpaid["groups"]}
        assert set(groups) == {"freight_draft", "freight_ready", "freight_payment_pending", "freight_failed"}
        assert groups["freight_draft"]["collectible"] is False
        assert "not collectible" in groups["freight_draft"]["source_note"].lower()
        assert _month(_usd(groups["freight_draft"]), current_key)["amount"] == pytest.approx(6.0)
        cad = next(row for row in groups["freight_draft"]["currencies"] if row["currency"] == "CAD")
        assert _month(cad, current_key)["amount"] == pytest.approx(5.0)
        assert _month(_usd(groups["freight_ready"]), prev_key)["amount"] == pytest.approx(7.0)
        body3 = client.get("/api/nova/accounting/trends", headers=owner, params={"months": 3}).json()
        body6 = client.get("/api/nova/accounting/trends", headers=owner, params={"months": 6}).json()
        assert body3["months"] == 3
        assert body6["months"] == 6
        assert len(_usd(_group(_stream(body3, "confirmed_customer_payments"), "confirmed_customer_payments"))["months"]) == 3
        assert len(_usd(_group(_stream(body6, "confirmed_customer_payments"), "confirmed_customer_payments"))["months"]) == 6
        blob = json.dumps(body12)
        assert "total_revenue" not in blob
        assert all("forecast" not in row["key"] for row in body12["streams"])
        for needle in (prefix, other_org, "customer_id", "driver_id", "invoice_id", "passenger_name", "routing", "sk_live"):
            assert needle not in blob
        other_body = client.get("/api/nova/accounting/trends", headers=other).json()
        other_usd = _usd(_group(_stream(other_body, "confirmed_customer_payments"), "confirmed_customer_payments"))
        assert 88.0 not in [row.get("amount") for row in other_usd["months"]]
        assert 99.0 not in [row.get("amount") for row in other_usd["months"]]
        summary = client.get("/api/nova/accounting/summary", headers=owner)
        aging = client.get("/api/nova/accounting/aging", headers=owner)
        assert summary.status_code == 200
        assert aging.status_code == 200
        assert len(summary.json()["metrics"]) == 6
        assert "customer_payment_pipeline" in aging.json()
    finally:
        with SessionLocal() as db:
            db.query(AmicorCustomerPayment).filter(AmicorCustomerPayment.stripe_payment_intent_id.in_(ids)).delete(
                synchronize_session=False
            )
            db.query(NovaFreightInvoice).filter(NovaFreightInvoice.invoice_id.in_(invoices)).delete(
                synchronize_session=False
            )
            db.commit()
        after = _counts()
        assert after["driver_001"] == before["driver_001"]
        assert after["health_rides"] == before["health_rides"]
        assert after["freight_shipments"] == before["freight_shipments"]


def test_trends_does_not_truncate_over_1000(client: TestClient) -> None:
    from app.modules.payments.models import PAYMENT_SUCCEEDED, AmicorCustomerPayment

    owner, org_id = _headers(client)
    baseline = client.get("/api/nova/accounting/trends", headers=owner, params={"months": 3})
    usd = _usd(_group(_stream(baseline.json(), "confirmed_customer_payments"), "confirmed_customer_payments"))
    current_key = usd["months"][-1]["month"]
    base_count = _month(usd, current_key)["count"]
    prefix = "pi_trbulk_" + uuid4().replace("-", "")[:8]
    stamp = now()
    rows = [
        AmicorCustomerPayment(
            id=uuid4(),
            service_type="RIDE",
            internal_service_id=f"trbulk-{index}",
            organization_id=org_id,
            stripe_payment_intent_id=f"{prefix}_{index:04d}",
            amount_minor=1,
            currency="usd",
            payment_status=PAYMENT_SUCCEEDED,
            created_at=stamp,
            paid_at=stamp,
        )
        for index in range(1001)
    ]
    with SessionLocal() as db:
        db.add_all(rows)
        db.commit()
    try:
        dash = client.get("/api/nova/accounting/trends", headers=owner, params={"months": 3})
        assert dash.status_code == 200
        usd_after = _usd(_group(_stream(dash.json(), "confirmed_customer_payments"), "confirmed_customer_payments"))
        assert _month(usd_after, current_key)["count"] == base_count + 1001
        assert _month(usd_after, current_key)["amount"] == pytest.approx(_month(usd, current_key)["amount"] + 10.01)
    finally:
        with SessionLocal() as db:
            db.query(AmicorCustomerPayment).filter(
                AmicorCustomerPayment.stripe_payment_intent_id.like(prefix + "%")
            ).delete(synchronize_session=False)
            db.commit()


def test_trends_fail_soft_and_phase123_unchanged(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("confirmed trends unavailable")

    monkeypatch.setattr("app.core.nova.accounting.trends._customer_confirmed", boom)
    headers, _org = _headers(client)
    dash = client.get("/api/nova/accounting/trends", headers=headers, params={"months": 6})
    assert dash.status_code == 200, dash.text
    body = dash.json()
    confirmed = _stream(body, "confirmed_customer_payments")
    pending = _stream(body, "current_pending_customer_payments")
    assert confirmed["status"] == "unavailable"
    assert confirmed["groups"][0]["status"] == "unavailable"
    assert pending["status"] == "ok"
    assert pending["groups"][0]["label"] == "Current pending payments by creation month"
    summary = client.get("/api/nova/accounting/summary", headers=headers)
    aging = client.get("/api/nova/accounting/aging", headers=headers)
    assert summary.status_code == 200
    assert aging.status_code == 200
    assert len(summary.json()["metrics"]) == 6


def test_trends_does_not_change_frozen_boundaries(client: TestClient) -> None:
    before = _counts()
    headers, _org = _headers(client)
    client.get("/nova/accounting")
    client.get("/nova/accounting/aging")
    client.get("/nova/accounting/trends")
    client.get("/api/nova/accounting/trends", headers=headers)
    after = _counts()
    assert after["driver_001"] == before["driver_001"]
    assert after["health_rides"] == before["health_rides"]
    assert after["freight_shipments"] == before["freight_shipments"]
    assert "DRV-001" not in TREND_HTML + TREND_JS
    assert "Driver 001" not in TREND_HTML + TREND_JS
    assert "nova-accounting" not in OPS_JS
    assert "/api/nova/accounting" not in HOME_JS
    for path in FROZEN_V1:
        text = path.read_text(encoding="utf-8")
        assert "nova_accounting" not in text
        if path.name == "index.html" and "nova-home" in str(path):
            assert "/api/nova/accounting" not in text
