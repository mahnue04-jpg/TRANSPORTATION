"""Nova Freight V1 Phase 6 — carrier payout, settlement, and TEST remittance."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, hash_password, seed_default_users
from app.core.nova.freight.models import (
    NovaFreightPayout,
    NovaFreightSettlement,
    NovaFreightShipment,
    NovaFreightShipmentEvent,
)
from app.core.nova.freight.money import money
from app.core.nova.freight.payout_config import CARRIER_PAYOUT_RATIO, split_customer_amount
from app.core.nova.freight.service import NovaFreightError
from app.core.nova.freight.settlement import assert_test_payout_mode
from app.core.nova.freight.stripe_checkout import FakeNovaFreightStripeClient, set_nova_freight_stripe_override
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal, init_platform_db
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFPayout, HealthISFSettlementLedger
from app.modules.payments.models import AmicorCustomerPayment

ROOT = Path(__file__).resolve().parents[1]
OPS_HTML = (ROOT / "static" / "ops-shell.html").read_text(encoding="utf-8")
DISPATCH_HTML = (ROOT / "static" / "nova-freight" / "dispatch.html").read_text(encoding="utf-8")
FINANCE_HTML = (ROOT / "static" / "nova-freight" / "finance.html").read_text(encoding="utf-8")
EARNINGS_HTML = (ROOT / "static" / "nova-freight" / "earnings.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    init_platform_db()
    ensure_auth_schema()
    seed_default_users()
    fake = FakeNovaFreightStripeClient()
    set_nova_freight_stripe_override(fake)
    yield TestClient(app)
    set_nova_freight_stripe_override(None)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(client: TestClient, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, email)['access_token']}"}


def _org_id(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user and user.organization_id
        return user.organization_id


def _create_driver(email: str, organization_id: str) -> str:
    with SessionLocal() as db:
        existing = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        if existing:
            existing.organization_id = organization_id
            existing.role = "driver"
            existing.is_active = True
            db.commit()
            return existing.id
        user = PlatformUser(
            id=uuid4(),
            email=email,
            hashed_password=hash_password(SEED_PASSWORD),
            display_name=email.split("@")[0],
            role="driver",
            organization_id=organization_id,
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.commit()
        return user.id


def _dec(value) -> Decimal:
    return money(value)


def _create_shipment(client: TestClient, suffix: str) -> dict:
    response = client.post(
        "/api/nova/freight/shipments",
        headers=_headers(client, "rider@amicor.local"),
        json={
            "customer_name": f"Settlement {suffix}",
            "pickup_address": "1 Dock",
            "pickup_city": "Minneapolis",
            "pickup_state": "MN",
            "pickup_zip": "55401",
            "delivery_address": "9 Yard",
            "delivery_city": "Duluth",
            "delivery_state": "MN",
            "delivery_zip": "55802",
            "commodity": "Settled freight",
            "weight": 12000,
            "pallet_count": 2,
            "equipment_type": "box_truck",
            "hazardous": False,
            "fragile": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _accept_and_complete(client: TestClient, shipment_id: str, suffix: str, *, proofs: bool = True) -> dict[str, str]:
    org = _org_id("dispatcher@amicor.local")
    driver_email = f"freight.set.{suffix}@amicor.local"
    driver_id = _create_driver(driver_email, org)
    carrier = client.post(
        "/api/nova/freight/carriers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"name": f"Set Carrier {suffix}", "equipment_type": "box_truck", "user_id": driver_id},
    )
    assert carrier.status_code == 201, carrier.text
    offers = client.post(
        f"/api/nova/freight/shipments/{shipment_id}/offers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"carrier_ids": [carrier.json()["carrier_id"]]},
    )
    assert offers.status_code == 201, offers.text
    accepted = client.post(
        f"/api/nova/freight/offers/{offers.json()[0]['offer_id']}/accept",
        headers=_headers(client, driver_email),
    )
    assert accepted.status_code == 200, accepted.text
    driver = _headers(client, driver_email)
    for status in [
        "en_route_to_pickup",
        "arrived_pickup",
        "picked_up",
        "in_transit",
        "arrived_delivery",
        "delivered",
        "completed",
    ]:
        moved = client.post(
            f"/api/nova/freight/shipments/{shipment_id}/status",
            headers=driver,
            json={"status": status},
        )
        assert moved.status_code == 200, moved.text
        if proofs and status == "arrived_pickup":
            pop = client.post(
                f"/api/nova/freight/shipments/{shipment_id}/proofs",
                headers=driver,
                json={"proof_type": "pickup_photo", "document_ref": f"nfr-set-pop-{suffix}", "content_type": "image/jpeg"},
            )
            assert pop.status_code == 201, pop.text
        if proofs and status == "arrived_delivery":
            pod = client.post(
                f"/api/nova/freight/shipments/{shipment_id}/proofs",
                headers=driver,
                json={"proof_type": "delivery_photo", "document_ref": f"nfr-set-pod-{suffix}", "content_type": "image/jpeg"},
            )
            assert pod.status_code == 201, pod.text
    return {
        "driver": driver_email,
        "dispatcher": "dispatcher@amicor.local",
        "admin": "admin@amicor.local",
        "rider": "rider@amicor.local",
        "carrier_id": carrier.json()["carrier_id"],
    }


def _quote_finalize(client: TestClient, shipment_id: str, miles: int = 40) -> dict:
    dispatcher = _headers(client, "dispatcher@amicor.local")
    quote = client.post(
        f"/api/nova/freight/shipments/{shipment_id}/quote",
        headers=dispatcher,
        json={"estimated_miles": miles},
    )
    assert quote.status_code == 200, quote.text
    finalized = client.post(f"/api/nova/freight/shipments/{shipment_id}/quote/finalize", headers=dispatcher)
    assert finalized.status_code == 200, finalized.text
    return finalized.json()


def _invoice_and_pay(client: TestClient, shipment_id: str) -> dict:
    dispatcher = _headers(client, "dispatcher@amicor.local")
    rider = _headers(client, "rider@amicor.local")
    created = client.post(f"/api/nova/freight/shipments/{shipment_id}/invoice", headers=dispatcher)
    assert created.status_code == 201, created.text
    finalized = client.post(f"/api/nova/freight/shipments/{shipment_id}/invoice/finalize", headers=dispatcher)
    assert finalized.status_code == 200, finalized.text
    pay = client.post(f"/api/nova/freight/shipments/{shipment_id}/invoice/pay", headers=rider, json={})
    assert pay.status_code == 200, pay.text
    paid = client.post(
        f"/api/nova/freight/shipments/{shipment_id}/invoice/confirm-payment",
        headers=rider,
        json={"simulate": "succeed"},
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["invoice_status"] == "paid"
    return paid.json()


def _paid_completed(client: TestClient, suffix: str, *, proofs: bool = True) -> tuple[dict, dict, dict]:
    shipment = _create_shipment(client, suffix)
    quote = _quote_finalize(client, shipment["shipment_id"])
    actors = _accept_and_complete(client, shipment["shipment_id"], suffix, proofs=proofs)
    invoice = _invoice_and_pay(client, shipment["shipment_id"])
    return shipment, actors, {**quote, "invoice": invoice}


def test_paid_completed_shipment_is_payout_eligible(client: TestClient) -> None:
    shipment, _actors, _meta = _paid_completed(client, "elg")
    check = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout/eligibility",
        headers=_headers(client, "dispatcher@amicor.local"),
    )
    assert check.status_code == 200, check.text
    body = check.json()
    assert body["eligible"] is True
    assert body["reasons"] == []
    customer, carrier, margin = split_customer_amount(body["suggested_customer_amount"])
    assert _dec(body["suggested_carrier_payout"]) == carrier
    assert _dec(body["suggested_amicor_margin"]) == margin
    assert customer == carrier + margin


def test_unpaid_invoice_is_not_payout_eligible(client: TestClient) -> None:
    shipment = _create_shipment(client, "unpaid")
    _quote_finalize(client, shipment["shipment_id"])
    _accept_and_complete(client, shipment["shipment_id"], "unpaid")
    dispatcher = _headers(client, "dispatcher@amicor.local")
    client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice", headers=dispatcher)
    client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice/finalize", headers=dispatcher)
    check = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout/eligibility",
        headers=dispatcher,
    )
    assert check.json()["eligible"] is False
    assert any("paid" in reason.lower() or "pending" in reason.lower() for reason in check.json()["reasons"])
    created = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout",
        headers=dispatcher,
    )
    assert created.status_code == 409


def test_incomplete_shipment_is_not_payout_eligible(client: TestClient) -> None:
    shipment = _create_shipment(client, "inc")
    _quote_finalize(client, shipment["shipment_id"])
    check = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout/eligibility",
        headers=_headers(client, "dispatcher@amicor.local"),
    )
    assert check.json()["eligible"] is False
    assert any("completed" in reason.lower() for reason in check.json()["reasons"])


def test_payout_creates_once_and_duplicate_is_blocked(client: TestClient) -> None:
    shipment, _actors, _meta = _paid_completed(client, "once")
    dispatcher = _headers(client, "dispatcher@amicor.local")
    first = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout", headers=dispatcher)
    second = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout", headers=dispatcher)
    assert first.status_code == 201, first.text
    assert second.status_code == 409
    with SessionLocal() as db:
        count = db.query(NovaFreightPayout).filter(NovaFreightPayout.shipment_id == shipment["shipment_id"]).count()
    assert count == 1


def test_default_configurable_payout_split(client: TestClient) -> None:
    assert CARRIER_PAYOUT_RATIO == Decimal("0.70")
    customer, carrier, margin = split_customer_amount("100.00")
    assert customer == Decimal("100.00")
    assert carrier == Decimal("70.00")
    assert margin == Decimal("30.00")
    shipment, _actors, meta = _paid_completed(client, "split")
    created = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout",
        headers=_headers(client, "dispatcher@amicor.local"),
    )
    assert created.status_code == 201, created.text
    expected_customer, expected_carrier, expected_margin = split_customer_amount(meta["quoted_amount"])
    assert _dec(created.json()["customer_amount"]) == expected_customer
    assert _dec(created.json()["carrier_payout_amount"]) == expected_carrier
    assert _dec(created.json()["amicor_margin_amount"]) == expected_margin
    assert _dec(created.json()["customer_amount"]) == _dec(created.json()["carrier_payout_amount"]) + _dec(
        created.json()["amicor_margin_amount"]
    )


def test_admin_adjust_recalculates_margin_and_unauthorized_cannot(client: TestClient) -> None:
    shipment, actors, _meta = _paid_completed(client, "adj")
    dispatcher = _headers(client, "dispatcher@amicor.local")
    admin = _headers(client, "admin@amicor.local")
    driver = _headers(client, actors["driver"])
    created = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout", headers=dispatcher)
    payout_id = created.json()["payout_id"]
    denied_dispatcher = client.post(
        f"/api/nova/freight/payouts/{payout_id}/adjust",
        headers=dispatcher,
        json={"carrier_payout_amount": "10.00", "reason": "dispatcher should not"},
    )
    denied_driver = client.post(
        f"/api/nova/freight/payouts/{payout_id}/adjust",
        headers=driver,
        json={"carrier_payout_amount": "10.00", "reason": "carrier should not"},
    )
    denied_approve = client.post(f"/api/nova/freight/payouts/{payout_id}/approve", headers=dispatcher)
    assert denied_dispatcher.status_code == 403
    assert denied_driver.status_code == 403
    assert denied_approve.status_code == 403
    adjusted = client.post(
        f"/api/nova/freight/payouts/{payout_id}/adjust",
        headers=admin,
        json={"carrier_payout_amount": "80.00", "reason": "Desk review TEST override"},
    )
    assert adjusted.status_code == 200, adjusted.text
    assert _dec(adjusted.json()["carrier_payout_amount"]) == Decimal("80.00")
    assert _dec(adjusted.json()["amicor_margin_amount"]) == _dec(adjusted.json()["customer_amount"]) - Decimal("80.00")
    assert adjusted.json()["adjustment_reason"] == "Desk review TEST override"


def test_hold_approve_and_simulated_payout(client: TestClient) -> None:
    shipment, _actors, _meta = _paid_completed(client, "hold")
    dispatcher = _headers(client, "dispatcher@amicor.local")
    admin = _headers(client, "admin@amicor.local")
    created = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout", headers=dispatcher)
    payout_id = created.json()["payout_id"]
    held = client.post(
        f"/api/nova/freight/payouts/{payout_id}/hold",
        headers=admin,
        json={"reason": "Review POD warning"},
    )
    assert held.status_code == 200
    assert held.json()["payout_status"] == "held"
    blocked = client.post(f"/api/nova/freight/payouts/{payout_id}/execute", headers=admin)
    assert blocked.status_code == 409
    approved = client.post(f"/api/nova/freight/payouts/{payout_id}/approve", headers=admin)
    assert approved.status_code == 200
    assert approved.json()["payout_status"] == "ready"
    again = client.post(f"/api/nova/freight/payouts/{payout_id}/approve", headers=admin)
    assert again.status_code == 200
    assert again.json()["payout_id"] == payout_id
    paid = client.post(f"/api/nova/freight/payouts/{payout_id}/execute", headers=admin)
    assert paid.status_code == 200, paid.text
    assert paid.json()["payout_status"] == "paid"
    assert paid.json()["payout_method"] == "simulated_test"
    assert str(paid.json()["external_payout_reference"]).startswith("SIM-TEST-")
    assert paid.json()["stripe_transfer_id"] is None
    retry = client.post(f"/api/nova/freight/payouts/{payout_id}/execute", headers=admin)
    assert retry.status_code == 200
    assert retry.json()["payout_id"] == payout_id
    assert retry.json()["external_payout_reference"] == paid.json()["external_payout_reference"]
    with SessionLocal() as db:
        assert db.query(NovaFreightPayout).filter(NovaFreightPayout.payout_id == payout_id).count() == 1
        assert db.query(NovaFreightSettlement).filter(NovaFreightSettlement.payout_id == payout_id).count() == 1


def test_settlement_and_remittance_created(client: TestClient) -> None:
    shipment, actors, _meta = _paid_completed(client, "remit")
    dispatcher = _headers(client, "dispatcher@amicor.local")
    admin = _headers(client, "admin@amicor.local")
    created = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout", headers=dispatcher)
    payout_id = created.json()["payout_id"]
    client.post(f"/api/nova/freight/payouts/{payout_id}/approve", headers=admin)
    client.post(f"/api/nova/freight/payouts/{payout_id}/execute", headers=admin)
    settlement = client.get(f"/api/nova/freight/payouts/{payout_id}/settlement", headers=dispatcher)
    remit = client.get(f"/api/nova/freight/payouts/{payout_id}/remittance", headers=dispatcher)
    assert settlement.status_code == 200, settlement.text
    assert remit.status_code == 200, remit.text
    assert settlement.json()["settlement_status"] == "paid"
    assert settlement.json()["shipment_id"] == shipment["shipment_id"]
    assert remit.json()["mode"] == "SIMULATED_TEST"
    assert remit.json()["money_moved"] is False
    assert "AMICOR Nova" in remit.json()["remittance_text"]
    assert shipment["shipment_id"] in remit.json()["remittance_text"]
    assert "1099" not in remit.json()["remittance_text"]
    rider_hidden = client.get(f"/api/nova/freight/payouts/{payout_id}/remittance", headers=_headers(client, "rider@amicor.local"))
    assert rider_hidden.status_code == 403
    driver_ok = client.get(f"/api/nova/freight/payouts/{payout_id}/remittance", headers=_headers(client, actors["driver"]))
    assert driver_ok.status_code == 200
    assert "amicor_margin" not in driver_ok.json()
    assert "customer_amount" not in driver_ok.json()


def test_carrier_only_sees_own_earnings(client: TestClient) -> None:
    shipment, actors, _meta = _paid_completed(client, "earn")
    dispatcher = _headers(client, "dispatcher@amicor.local")
    admin = _headers(client, "admin@amicor.local")
    created = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout", headers=dispatcher)
    payout_id = created.json()["payout_id"]
    client.post(f"/api/nova/freight/payouts/{payout_id}/approve", headers=admin)
    client.post(f"/api/nova/freight/payouts/{payout_id}/execute", headers=admin)
    mine = client.get("/api/nova/freight/carrier/earnings", headers=_headers(client, actors["driver"]))
    assert mine.status_code == 200, mine.text
    assert mine.json()["rows"]
    assert mine.json()["rows"][0]["shipment_id"] == shipment["shipment_id"]
    assert "customer_amount" not in mine.json()["rows"][0]
    assert "amicor_margin" not in str(mine.json())
    other_email = f"freight.set.other.{uuid4()[:6]}@amicor.local"
    other_id = _create_driver(other_email, _org_id("dispatcher@amicor.local"))
    other_carrier = client.post(
        "/api/nova/freight/carriers",
        headers=dispatcher,
        json={"name": "Other earnings carrier", "equipment_type": "box_truck", "user_id": other_id},
    )
    assert other_carrier.status_code == 201
    other = client.get("/api/nova/freight/carrier/earnings", headers=_headers(client, other_email))
    assert other.status_code == 200
    assert all(row["shipment_id"] != shipment["shipment_id"] for row in other.json()["rows"])
    dispatch_blocked = client.get("/api/nova/freight/carrier/earnings", headers=dispatcher)
    assert dispatch_blocked.status_code == 403


def test_cross_tenant_and_customer_cannot_see_margin(client: TestClient) -> None:
    shipment, _actors, _meta = _paid_completed(client, "ten")
    dispatcher = _headers(client, "dispatcher@amicor.local")
    created = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout", headers=dispatcher)
    assert created.status_code == 201
    rider = _headers(client, "rider@amicor.local")
    detail = client.get(f"/api/nova/freight/shipments/{shipment['shipment_id']}", headers=rider)
    assert detail.json()["amicor_margin"] is None
    assert detail.json()["carrier_payout_amount"] is None
    customer = client.get(f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote/customer", headers=rider)
    assert "estimated_amicor_margin" not in customer.json()
    board = client.get("/api/nova/freight/payouts", headers=rider)
    assert board.status_code == 403
    other_email = f"freight.set.tenant.{uuid4()[:6]}@amicor.local"
    with SessionLocal() as db:
        db.add(
            PlatformUser(
                id=uuid4(),
                email=other_email,
                hashed_password=hash_password(SEED_PASSWORD),
                role="admin",
                organization_id=f"org-set-{uuid4()[:8]}",
                is_active=True,
                is_verified=True,
            )
        )
        db.commit()
    hidden = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout",
        headers=_headers(client, other_email),
    )
    assert hidden.status_code == 404


def test_live_stripe_keys_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_notarealkey")
    with pytest.raises(NovaFreightError) as exc:
        assert_test_payout_mode()
    assert exc.value.status_code == 503


def test_missing_proof_is_warning_not_block(client: TestClient) -> None:
    shipment, _actors, _meta = _paid_completed(client, "warn", proofs=False)
    check = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout/eligibility",
        headers=_headers(client, "dispatcher@amicor.local"),
    )
    assert check.json()["eligible"] is True
    assert check.json()["warnings"]
    created = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/payout",
        headers=_headers(client, "dispatcher@amicor.local"),
    )
    assert created.status_code == 201
    assert created.json()["proof_warning"]


def test_phase6_local_e2e_surfaces_and_isolation(client: TestClient) -> None:
    with SessionLocal() as db:
        delivery_before = db.query(AmicorCustomerPayment).count()
        health_payout_before = db.query(HealthISFPayout).count()
        health_ledger_before = db.query(HealthISFSettlementLedger).count()
    shipment, actors, meta = _paid_completed(client, "e2e6")
    sid = shipment["shipment_id"]
    dispatcher = _headers(client, "dispatcher@amicor.local")
    admin = _headers(client, "admin@amicor.local")
    rider = _headers(client, "rider@amicor.local")
    created = client.post(f"/api/nova/freight/shipments/{sid}/payout", headers=dispatcher)
    assert created.status_code == 201, created.text
    payout_id = created.json()["payout_id"]
    customer, carrier, margin = split_customer_amount(meta["quoted_amount"])
    assert _dec(created.json()["customer_amount"]) == customer
    assert _dec(created.json()["carrier_payout_amount"]) == carrier
    assert _dec(created.json()["amicor_margin_amount"]) == margin
    client.post(f"/api/nova/freight/payouts/{payout_id}/approve", headers=admin)
    paid = client.post(f"/api/nova/freight/payouts/{payout_id}/execute", headers=admin)
    assert paid.json()["payout_status"] == "paid"
    retry = client.post(f"/api/nova/freight/payouts/{payout_id}/execute", headers=admin)
    assert retry.json()["external_payout_reference"] == paid.json()["external_payout_reference"]
    earnings = client.get("/api/nova/freight/carrier/earnings", headers=_headers(client, actors["driver"]))
    assert earnings.json()["paid_total"]
    remit = client.get(f"/api/nova/freight/payouts/{payout_id}/remittance", headers=admin)
    assert remit.json()["money_moved"] is False
    events = client.get(f"/api/nova/freight/shipments/{sid}/events", headers=dispatcher).json()
    types = {row["event_type"] for row in events}
    assert {
        "carrier_payout_created",
        "carrier_payout_approved",
        "carrier_payout_processing",
        "carrier_payout_paid",
        "settlement_created",
        "remittance_created",
    } <= types
    rider_detail = client.get(f"/api/nova/freight/shipments/{sid}", headers=rider)
    assert rider_detail.json()["amicor_margin"] is None
    unauth = client.get("/api/nova/freight/payouts")
    assert unauth.status_code == 401
    finance_page = client.get("/nova/freight/finance")
    earnings_page = client.get("/nova/freight/carrier/earnings")
    assert finance_page.status_code == 200
    assert earnings_page.status_code == 200
    assert "Freight Payout Review" in finance_page.text
    assert "Carrier Earnings" in earnings_page.text
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/nova/freight/shipments/{shipment_id}/payout" in paths
    assert "/api/nova/freight/payouts/{payout_id}/execute" in paths
    assert "/api/nova/freight/carrier/earnings" in paths
    assert "Create pending payout" in DISPATCH_HTML
    assert "SIMULATED" in FINANCE_HTML or "TEST" in FINANCE_HTML
    assert "AMICOR margin" in EARNINGS_HTML
    assert "AMICOR Delivery" in OPS_HTML
    with SessionLocal() as db:
        assert db.query(NovaFreightPayout).filter(NovaFreightPayout.shipment_id == sid).count() == 1
        assert db.query(NovaFreightSettlement).filter(NovaFreightSettlement.shipment_id == sid).count() == 1
        assert db.query(NovaFreightShipment).filter(NovaFreightShipment.shipment_id == sid).one().status == "completed"
        assert db.query(AmicorCustomerPayment).count() == delivery_before
        assert db.query(HealthISFPayout).count() == health_payout_before
        assert db.query(HealthISFSettlementLedger).count() == health_ledger_before
        assert db.query(AmicorCustomerPayment).filter(AmicorCustomerPayment.internal_service_id == sid).count() == 0
        assert (
            db.query(NovaFreightShipmentEvent)
            .filter(NovaFreightShipmentEvent.shipment_id == sid, NovaFreightShipmentEvent.payout_id == payout_id)
            .count()
            >= 1
        )
    assert NovaFreightPayout.__tablename__ == "nova_freight_payouts"
    assert NovaFreightSettlement.__tablename__ == "nova_freight_settlements"
    assert HealthISFPayout.__tablename__ == "health_isf_payouts"
    assert AmicorCustomerPayment.__tablename__ == "amicor_customer_payments"
    live = client.get("/api/health/live")
    assert live.status_code == 200
    rides = client.get("/api/health-isf/rides", headers=dispatcher)
    assert rides.status_code == 200
