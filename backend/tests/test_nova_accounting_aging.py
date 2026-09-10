"""Nova V2 read-only pending-funds aging. Does not write financial records."""
from __future__ import annotations

import json
from datetime import timedelta
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
AGING_HTML = (STATIC / "nova-accounting" / "aging.html").read_text(encoding="utf-8")
AGING_JS = (STATIC / "nova-accounting" / "aging.js").read_text(encoding="utf-8")
ACCT_HTML = (STATIC / "nova-accounting" / "index.html").read_text(encoding="utf-8")
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


def _group(section: dict, key: str) -> dict:
    return next(row for row in section["groups"] if row["key"] == key)


def _usd_slice(group: dict) -> dict:
    return next(row for row in group["currencies"] if row["currency"] == "USD")


def _bucket(slice_row: dict, key: str) -> dict:
    return next(row for row in slice_row["buckets"] if row["key"] == key)


def test_aging_page_layout_and_privacy_copy() -> None:
    assert "Pending funds aging" in AGING_HTML
    assert "Customer payment pipeline" in AGING_HTML
    assert "Freight invoice pipeline" in AGING_HTML
    assert "Stripe remains TEST" in AGING_HTML
    assert "overdue" not in AGING_HTML.lower()
    assert "collect" not in AGING_JS.lower()
    assert "/api/nova/accounting/aging" in AGING_JS
    assert "customer_id" not in AGING_JS
    assert "invoice_id" not in AGING_JS
    assert "routing" not in AGING_JS.lower()
    assert "sk_live" not in AGING_JS
    assert 'href="/nova">Nova Home</a>' in AGING_HTML
    assert 'href="/nova/today">Today</a>' in AGING_HTML
    assert 'href="/nova/accounting">Accounting</a>' in AGING_HTML
    assert 'href="/nova/accounting/aging"' in AGING_HTML
    assert 'href="/nova/accounting/aging">Aging</a>' in ACCT_HTML
    assert 'href="/nova/accounting/aging">Aging</a>' in TODAY_HTML
    assert 'name="viewport"' in AGING_HTML


def test_aging_bucket_boundaries_and_missing_fields() -> None:
    from app.core.nova.accounting.aging import _aggregate, age_days, bucket_key
    from app.helpers import now as utc_now

    stamp = utc_now()
    assert age_days(None, as_of=stamp) is None
    assert age_days(stamp, as_of=stamp) == 0
    assert age_days(stamp - timedelta(days=7), as_of=stamp) == 7
    assert age_days(stamp - timedelta(days=8), as_of=stamp) == 8
    assert age_days(stamp - timedelta(days=30), as_of=stamp) == 30
    assert age_days(stamp - timedelta(days=31), as_of=stamp) == 31
    assert age_days(stamp - timedelta(days=60), as_of=stamp) == 60
    assert age_days(stamp - timedelta(days=61), as_of=stamp) == 61
    assert age_days(stamp + timedelta(days=1), as_of=stamp) is None
    assert bucket_key(0) == "0_7"
    assert bucket_key(7) == "0_7"
    assert bucket_key(8) == "8_30"
    assert bucket_key(30) == "8_30"
    assert bucket_key(31) == "31_60"
    assert bucket_key(60) == "31_60"
    assert bucket_key(61) == "61_plus"
    rows = [
        (stamp - timedelta(days=7), 700, "usd"),
        (stamp - timedelta(days=8), 800, "usd"),
        (stamp - timedelta(days=30), 3000, "usd"),
        (stamp - timedelta(days=31), 3100, "usd"),
        (stamp - timedelta(days=60), 6000, "usd"),
        (stamp - timedelta(days=61), 6100, "usd"),
        (None, 900, "usd"),
        (stamp - timedelta(days=2), None, "usd"),
        (stamp - timedelta(days=3), 400, "eur"),
    ]
    slices = {row.currency: row for row in _aggregate(rows, as_of=stamp, amount_mode="minor")}
    usd = slices["USD"]
    assert usd.count == 8
    assert usd.unaged_count == 1
    assert usd.missing_amount_count == 1
    dumped = usd.model_dump()
    assert usd.amount == pytest.approx(206.0)
    assert _bucket(dumped, "0_7")["count"] == 2
    assert _bucket(dumped, "8_30")["count"] == 2
    assert _bucket(dumped, "31_60")["count"] == 2
    assert _bucket(dumped, "61_plus")["count"] == 1
    assert "EUR" in slices
    assert slices["EUR"].amount == pytest.approx(4.0)
    assert usd.amount != slices["EUR"].amount


def test_aging_auth_isolation_and_refuses(client: TestClient) -> None:
    page = client.get("/nova/accounting/aging")
    assert page.status_code == 200
    assert "Pending funds aging" in page.text
    assert client.get("/api/nova/accounting/aging").status_code == 401
    headers, _org = _headers(client)
    assert client.post("/api/nova/accounting/collect", headers=headers).status_code == 403
    assert client.post("/api/nova/accounting/remind", headers=headers).status_code == 403
    assert client.post("/api/nova/accounting/export", headers=headers).status_code == 403
    driver, _ = _headers(client, "driver@amicor.local")
    assert client.get("/api/nova/accounting/aging", headers=driver).status_code == 403
    cross = client.get("/api/nova/accounting/aging", headers=headers, params={"organization_id": "org-not-the-caller"})
    assert cross.status_code == 403


def test_aging_pipelines_boundaries_currencies_and_privacy(client: TestClient) -> None:
    from app.core.nova.freight.models import NovaFreightInvoice
    from app.modules.payments.models import PAYMENT_PENDING, PAYMENT_SUCCEEDED, AmicorCustomerPayment

    owner, org_id = _headers(client, "dispatcher@amicor.local")
    other, _ = _headers(client, "staff@amicor.local")
    before = _counts()
    stamp = now()
    prefix = "pi_age_" + uuid4().replace("-", "")[:8]
    other_org = "org-age-" + uuid4().replace("-", "")[:8]
    ids = []
    invoices = []

    def pay(suffix: str, days: int, minor: int, status: str = PAYMENT_PENDING, org: str | None = org_id, currency: str = "usd"):
        pi = f"{prefix}_{suffix}"
        ids.append(pi)
        return AmicorCustomerPayment(
            id=uuid4(),
            service_type="RIDE",
            internal_service_id=f"age-{suffix}",
            organization_id=org,
            stripe_payment_intent_id=pi,
            amount_minor=minor,
            currency=currency,
            payment_status=status,
            created_at=stamp - timedelta(days=days),
        )

    def invoice(suffix: str, days: int, amount: str, status: str, currency: str = "USD"):
        invoice_id = "NFI-AGE-" + suffix + uuid4().replace("-", "")[:6].upper()
        invoices.append(invoice_id)
        return NovaFreightInvoice(
            invoice_id=invoice_id,
            shipment_id="NFS-AGE-" + suffix,
            organization_id=org_id,
            total_amount=Decimal(amount),
            total_amount_minor=int(Decimal(amount) * 100),
            currency=currency,
            invoice_status=status,
            created_at=stamp - timedelta(days=days),
            idempotency_key="age-" + invoice_id,
        )

    with SessionLocal() as db:
        db.add_all(
            [
                pay("d0", 0, 100),
                pay("d7", 7, 700),
                pay("d8", 8, 800),
                pay("d30", 30, 3000),
                pay("d31", 31, 3100),
                pay("d60", 60, 6000),
                pay("d61", 61, 6100),
                pay("eur", 3, 250, currency="eur"),
                pay("nullorg", 2, 9900, org=None),
                pay("succeeded", 2, 4400, status=PAYMENT_SUCCEEDED),
                pay("other", 2, 8800, org=other_org),
                invoice("D0", 0, "1.00", "draft"),
                invoice("R8", 8, "2.00", "ready"),
                invoice("P31", 31, "3.00", "payment_pending"),
                invoice("F61", 61, "4.00", "failed"),
                invoice("CAD", 4, "5.00", "ready", currency="CAD"),
            ]
        )
        db.commit()

    try:
        dash = client.get("/api/nova/accounting/aging", headers=owner)
        assert dash.status_code == 200, dash.text
        body = dash.json()
        assert body["stripe_mode"] == "TEST"
        assert body["calculated_as_of_utc"]
        assert "overdue" not in json.dumps(body).lower()
        customer = _group(body["customer_payment_pipeline"], "customer_pending")
        assert customer["status"] == "ok"
        assert customer["uses_due_date"] is False
        assert customer["due_date_field"] is None
        assert customer["measurement"] == "Age since created"
        usd = _usd_slice(customer)
        assert usd["count"] == 7
        assert usd["oldest_age_days"] == 61
        assert _bucket(usd, "0_7")["count"] == 2
        assert _bucket(usd, "0_7")["amount"] == pytest.approx(8.0)
        assert _bucket(usd, "8_30")["count"] == 2
        assert _bucket(usd, "31_60")["count"] == 2
        assert _bucket(usd, "61_plus")["count"] == 1
        assert _bucket(usd, "61_plus")["amount"] == pytest.approx(61.0)
        eur = next(row for row in customer["currencies"] if row["currency"] == "EUR")
        assert eur["amount"] == pytest.approx(2.5)
        assert usd["amount"] != eur["amount"]
        freight = {row["key"]: row for row in body["freight_invoice_pipeline"]["groups"]}
        assert set(freight) == {
            "freight_draft",
            "freight_ready",
            "freight_payment_pending",
            "freight_failed",
        }
        assert freight["freight_draft"]["collectible"] is False
        assert "not collectible" in freight["freight_draft"]["source_note"].lower()
        assert _usd_slice(freight["freight_draft"])["amount"] == pytest.approx(1.0)
        assert _usd_slice(freight["freight_ready"])["amount"] == pytest.approx(2.0)
        assert _usd_slice(freight["freight_payment_pending"])["amount"] == pytest.approx(3.0)
        assert _usd_slice(freight["freight_failed"])["amount"] == pytest.approx(4.0)
        cad = next(row for row in freight["freight_ready"]["currencies"] if row["currency"] == "CAD")
        assert cad["amount"] == pytest.approx(5.0)
        customer_total = sum(float(row["amount"] or 0) for row in customer["currencies"])
        freight_total = sum(
            float(slice_row["amount"] or 0)
            for group in freight.values()
            for slice_row in group["currencies"]
        )
        assert customer_total != freight_total
        blob = json.dumps(body)
        for needle in (
            prefix,
            other_org,
            "passenger_name",
            "customer_id",
            "driver_id",
            "invoice_id",
            "routing",
            "ssn",
            "bank",
            "sk_live",
        ):
            assert needle not in blob
        other_dash = client.get("/api/nova/accounting/aging", headers=other)
        assert other_dash.status_code == 200
        other_customer = _group(other_dash.json()["customer_payment_pipeline"], "customer_pending")
        assert 88.0 not in [row.get("amount") for row in other_customer["currencies"]]
        assert 99.0 not in [row.get("amount") for row in other_customer["currencies"]]
        summary = client.get("/api/nova/accounting/summary", headers=owner)
        assert summary.status_code == 200
        assert len(summary.json()["metrics"]) == 6
        assert summary.json()["window"] == "all"
    finally:
        with SessionLocal() as db:
            db.query(AmicorCustomerPayment).filter(
                AmicorCustomerPayment.stripe_payment_intent_id.in_(ids)
            ).delete(synchronize_session=False)
            db.query(NovaFreightInvoice).filter(NovaFreightInvoice.invoice_id.in_(invoices)).delete(
                synchronize_session=False
            )
            db.commit()
        after = _counts()
        assert after["driver_001"] == before["driver_001"]
        assert after["health_rides"] == before["health_rides"]
        assert after["freight_shipments"] == before["freight_shipments"]


def test_aging_does_not_truncate_over_1000(client: TestClient) -> None:
    from app.modules.payments.models import PAYMENT_PENDING, AmicorCustomerPayment

    owner, org_id = _headers(client)
    baseline = client.get("/api/nova/accounting/aging", headers=owner)
    assert baseline.status_code == 200
    customer = _group(baseline.json()["customer_payment_pipeline"], "customer_pending")
    usd_rows = [row for row in customer["currencies"] if row["currency"] == "USD"]
    base_count = usd_rows[0]["count"] if usd_rows else 0
    prefix = "pi_agebulk_" + uuid4().replace("-", "")[:8]
    stamp = now()
    rows = [
        AmicorCustomerPayment(
            id=uuid4(),
            service_type="RIDE",
            internal_service_id=f"agebulk-{index}",
            organization_id=org_id,
            stripe_payment_intent_id=f"{prefix}_{index:04d}",
            amount_minor=1,
            currency="usd",
            payment_status=PAYMENT_PENDING,
            created_at=stamp - timedelta(days=1),
        )
        for index in range(1001)
    ]
    with SessionLocal() as db:
        db.add_all(rows)
        db.commit()
    try:
        dash = client.get("/api/nova/accounting/aging", headers=owner)
        assert dash.status_code == 200, dash.text
        usd = _usd_slice(_group(dash.json()["customer_payment_pipeline"], "customer_pending"))
        assert usd["count"] == base_count + 1001
        assert _bucket(usd, "0_7")["count"] >= 1001
    finally:
        with SessionLocal() as db:
            db.query(AmicorCustomerPayment).filter(
                AmicorCustomerPayment.stripe_payment_intent_id.like(prefix + "%")
            ).delete(synchronize_session=False)
            db.commit()


def test_aging_fail_soft_and_phase12_unchanged(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("customer aging unavailable")

    monkeypatch.setattr("app.core.nova.accounting.aging._customer_group", boom)
    headers, _org = _headers(client)
    dash = client.get("/api/nova/accounting/aging", headers=headers)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    customer = body["customer_payment_pipeline"]
    freight = body["freight_invoice_pipeline"]
    assert customer["status"] == "unavailable"
    assert customer["groups"][0]["status"] == "unavailable"
    assert freight["status"] == "ok"
    assert all(group["status"] == "ok" for group in freight["groups"])
    summary = client.get("/api/nova/accounting/summary", headers=headers, params={"window": "7d"})
    assert summary.status_code == 200
    assert summary.json()["window"] == "7d"
    assert len(summary.json()["metrics"]) == 6


def test_aging_freight_status_fails_independently(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    original = __import__("app.core.nova.accounting.aging", fromlist=["_freight_group"])._freight_group

    def maybe_boom(db, organization_id, as_of, status):
        if status == "draft":
            raise RuntimeError("draft aging unavailable")
        return original(db, organization_id, as_of, status)

    monkeypatch.setattr("app.core.nova.accounting.aging._freight_group", maybe_boom)
    headers, _org = _headers(client)
    dash = client.get("/api/nova/accounting/aging", headers=headers)
    assert dash.status_code == 200, dash.text
    groups = {row["key"]: row for row in dash.json()["freight_invoice_pipeline"]["groups"]}
    assert groups["freight_draft"]["status"] == "unavailable"
    assert groups["freight_ready"]["status"] == "ok"
    assert groups["freight_payment_pending"]["status"] == "ok"
    assert groups["freight_failed"]["status"] == "ok"


def test_aging_does_not_change_frozen_boundaries(client: TestClient) -> None:
    before = _counts()
    headers, _org = _headers(client)
    client.get("/nova/accounting")
    client.get("/nova/accounting/aging")
    client.get("/nova/today")
    client.get("/api/nova/accounting/aging", headers=headers)
    after = _counts()
    assert after["driver_001"] == before["driver_001"]
    assert after["health_rides"] == before["health_rides"]
    assert after["freight_shipments"] == before["freight_shipments"]
    assert "DRV-001" not in AGING_HTML + AGING_JS
    assert "Driver 001" not in AGING_HTML + AGING_JS
    assert "nova-accounting" not in OPS_JS
    assert "/api/nova/accounting" not in HOME_JS
    for path in FROZEN_V1:
        text = path.read_text(encoding="utf-8")
        assert "nova_accounting" not in text
        if path.name == "index.html" and "nova-home" in str(path):
            assert "/api/nova/accounting" not in text
