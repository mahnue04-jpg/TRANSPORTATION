"""Nova Freight V1 Phase 7 — launch readiness, history, and ops hardening."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, hash_password, seed_default_users
from app.core.nova.freight.models import (
    NovaFreightInvoice,
    NovaFreightOffer,
    NovaFreightPayout,
    NovaFreightSettlement,
    NovaFreightShipment,
)
from app.core.nova.freight.payout_config import split_customer_amount
from app.core.nova.freight.service import NovaFreightError
from app.core.nova.freight.settlement import assert_test_payout_mode
from app.core.nova.freight.stripe_checkout import FakeNovaFreightStripeClient, set_nova_freight_stripe_override
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal, init_platform_db
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFPayout, HealthISFSettlementLedger
from app.modules.payments.models import AmicorCustomerPayment
from app.modules.platform_ops.models import PlatformDriverOnboardingApplication

ROOT = Path(__file__).resolve().parents[1]
OPS_HTML = (ROOT / "static" / "ops-shell.html").read_text(encoding="utf-8")
FREIGHT_CSS = (ROOT / "static" / "nova-freight" / "freight.css").read_text(encoding="utf-8")
OPS_PAGE = (ROOT / "static" / "nova-freight" / "ops.html").read_text(encoding="utf-8")
HISTORY_PAGE = (ROOT / "static" / "nova-freight" / "history.html").read_text(encoding="utf-8")


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


def _create_shipment(client: TestClient, suffix: str) -> dict:
    response = client.post(
        "/api/nova/freight/shipments",
        headers=_headers(client, "rider@amicor.local"),
        json={
            "customer_name": f"Phase7 {suffix}",
            "pickup_address": "1 Dock",
            "pickup_city": "Minneapolis",
            "pickup_state": "MN",
            "pickup_zip": "55401",
            "delivery_address": "9 Yard",
            "delivery_city": "Duluth",
            "delivery_state": "MN",
            "delivery_zip": "55802",
            "commodity": "Launch freight",
            "weight": 12000,
            "pallet_count": 2,
            "equipment_type": "box_truck",
            "hazardous": False,
            "fragile": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _accept_and_complete(client: TestClient, shipment_id: str, suffix: str) -> dict[str, str]:
    org = _org_id("dispatcher@amicor.local")
    driver_email = f"freight.p7.{suffix}@amicor.local"
    driver_id = _create_driver(driver_email, org)
    carrier = client.post(
        "/api/nova/freight/carriers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"name": f"P7 Carrier {suffix}", "equipment_type": "box_truck", "user_id": driver_id},
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
        if status == "arrived_pickup":
            assert client.post(
                f"/api/nova/freight/shipments/{shipment_id}/proofs",
                headers=driver,
                json={"proof_type": "pickup_photo", "document_ref": f"nfr-p7-pop-{suffix}", "content_type": "image/jpeg"},
            ).status_code == 201
        if status == "arrived_delivery":
            assert client.post(
                f"/api/nova/freight/shipments/{shipment_id}/proofs",
                headers=driver,
                json={"proof_type": "delivery_photo", "document_ref": f"nfr-p7-pod-{suffix}", "content_type": "image/jpeg"},
            ).status_code == 201
    return {
        "driver": driver_email,
        "carrier_id": carrier.json()["carrier_id"],
        "offer_id": offers.json()[0]["offer_id"],
    }


def _quote_pay_payout(client: TestClient, shipment_id: str) -> dict:
    dispatcher = _headers(client, "dispatcher@amicor.local")
    admin = _headers(client, "admin@amicor.local")
    rider = _headers(client, "rider@amicor.local")
    quote = client.post(
        f"/api/nova/freight/shipments/{shipment_id}/quote",
        headers=dispatcher,
        json={"estimated_miles": 40},
    )
    assert quote.status_code == 200, quote.text
    client.post(f"/api/nova/freight/shipments/{shipment_id}/quote/finalize", headers=dispatcher)
    _accept_and_complete(client, shipment_id, shipment_id[-6:].lower())
    client.post(f"/api/nova/freight/shipments/{shipment_id}/invoice", headers=dispatcher)
    client.post(f"/api/nova/freight/shipments/{shipment_id}/invoice/finalize", headers=dispatcher)
    client.post(f"/api/nova/freight/shipments/{shipment_id}/invoice/pay", headers=rider, json={})
    paid = client.post(
        f"/api/nova/freight/shipments/{shipment_id}/invoice/confirm-payment",
        headers=rider,
        json={"simulate": "succeed"},
    )
    assert paid.json()["invoice_status"] == "paid"
    created = client.post(f"/api/nova/freight/shipments/{shipment_id}/payout", headers=dispatcher)
    assert created.status_code == 201, created.text
    payout_id = created.json()["payout_id"]
    client.post(f"/api/nova/freight/payouts/{payout_id}/approve", headers=admin)
    executed = client.post(f"/api/nova/freight/payouts/{payout_id}/execute", headers=admin)
    assert executed.json()["payout_status"] == "paid"
    return {"quote": quote.json(), "invoice": paid.json(), "payout": executed.json()}


def test_full_shipment_e2e_leaves_active_queues_and_history(client: TestClient) -> None:
    shipment = _create_shipment(client, "e2e")
    sid = shipment["shipment_id"]
    actors = _quote_pay_payout(client, sid)
    dispatcher = _headers(client, "dispatcher@amicor.local")
    driver = _headers(client, f"freight.p7.{sid[-6:].lower()}@amicor.local")
    active = client.get("/api/nova/freight/shipments?scope=active", headers=_headers(client, "rider@amicor.local"))
    assert active.status_code == 200
    assert all(row["shipment_id"] != sid for row in active.json())
    carrier_active = client.get("/api/nova/freight/carrier/shipments", headers=driver)
    assert all(row["shipment_id"] != sid for row in carrier_active.json())
    board = client.get("/api/nova/freight/dispatch/shipments", headers=dispatcher)
    assert all(row["shipment_id"] != sid for row in board.json())
    history = client.get("/api/nova/freight/history", headers=dispatcher)
    assert history.status_code == 200, history.text
    match = [row for row in history.json() if row["shipment_id"] == sid]
    assert match
    assert match[0]["invoice_status"] == "paid"
    assert match[0]["carrier_payout_status"] == "paid"
    assert match[0]["settlement_status"] == "paid"
    assert match[0]["has_pickup_proof"] is True
    assert match[0]["has_delivery_proof"] is True
    detail = client.get(f"/api/nova/freight/history/{sid}", headers=dispatcher)
    assert detail.status_code == 200
    types = {row["event_type"] for row in detail.json()["events"]}
    assert {"carrier_payout_paid", "settlement_created", "remittance_created"} <= types
    retry = client.post(
        f"/api/nova/freight/payouts/{actors['payout']['payout_id']}/execute",
        headers=_headers(client, "admin@amicor.local"),
    )
    assert retry.json()["external_payout_reference"] == actors["payout"]["external_payout_reference"]
    customer, carrier, margin = split_customer_amount(actors["quote"]["quoted_amount"])
    assert actors["payout"]["customer_amount"]
    assert str(customer)
    assert str(carrier)
    assert str(margin)


def test_duplicate_accept_invoice_charge_and_payout_blocked(client: TestClient) -> None:
    shipment = _create_shipment(client, "dup")
    sid = shipment["shipment_id"]
    dispatcher = _headers(client, "dispatcher@amicor.local")
    quote = client.post(f"/api/nova/freight/shipments/{sid}/quote", headers=dispatcher, json={"estimated_miles": 20})
    client.post(f"/api/nova/freight/shipments/{sid}/quote/finalize", headers=dispatcher)
    actors = _accept_and_complete(client, sid, "dupx")
    second_accept = client.post(
        f"/api/nova/freight/offers/{actors['offer_id']}/accept",
        headers=_headers(client, actors["driver"]),
    )
    assert second_accept.status_code == 409
    same_status = client.post(
        f"/api/nova/freight/shipments/{sid}/status",
        headers=_headers(client, actors["driver"]),
        json={"status": "completed"},
    )
    assert same_status.status_code == 200
    first_inv = client.post(f"/api/nova/freight/shipments/{sid}/invoice", headers=dispatcher)
    second_inv = client.post(f"/api/nova/freight/shipments/{sid}/invoice", headers=dispatcher)
    assert first_inv.status_code == 201
    assert second_inv.status_code == 201
    assert first_inv.json()["invoice_id"] == second_inv.json()["invoice_id"]
    rider = _headers(client, "rider@amicor.local")
    client.post(f"/api/nova/freight/shipments/{sid}/invoice/finalize", headers=dispatcher)
    pay1 = client.post(f"/api/nova/freight/shipments/{sid}/invoice/pay", headers=rider, json={})
    pay2 = client.post(f"/api/nova/freight/shipments/{sid}/invoice/pay", headers=rider, json={})
    assert pay2.json()["stripe_payment_intent_id"] == pay1.json()["stripe_payment_intent_id"]
    client.post(f"/api/nova/freight/shipments/{sid}/invoice/confirm-payment", headers=rider, json={"simulate": "succeed"})
    first_payout = client.post(f"/api/nova/freight/shipments/{sid}/payout", headers=dispatcher)
    second_payout = client.post(f"/api/nova/freight/shipments/{sid}/payout", headers=dispatcher)
    assert first_payout.status_code == 201
    assert second_payout.status_code == 409
    _ = quote


def test_payment_failure_recovery_and_void_reinvoice(client: TestClient) -> None:
    shipment = _create_shipment(client, "fail")
    sid = shipment["shipment_id"]
    dispatcher = _headers(client, "dispatcher@amicor.local")
    rider = _headers(client, "rider@amicor.local")
    client.post(f"/api/nova/freight/shipments/{sid}/quote", headers=dispatcher, json={"estimated_miles": 12})
    client.post(f"/api/nova/freight/shipments/{sid}/quote/finalize", headers=dispatcher)
    _accept_and_complete(client, sid, "failx")
    client.post(f"/api/nova/freight/shipments/{sid}/invoice", headers=dispatcher)
    client.post(f"/api/nova/freight/shipments/{sid}/invoice/finalize", headers=dispatcher)
    client.post(f"/api/nova/freight/shipments/{sid}/invoice/pay", headers=rider, json={})
    failed = client.post(
        f"/api/nova/freight/shipments/{sid}/invoice/confirm-payment",
        headers=rider,
        json={"simulate": "fail"},
    )
    assert failed.json()["invoice_status"] == "failed"
    retry = client.post(f"/api/nova/freight/shipments/{sid}/invoice/pay", headers=rider, json={})
    assert retry.status_code == 200
    paid = client.post(
        f"/api/nova/freight/shipments/{sid}/invoice/confirm-payment",
        headers=rider,
        json={"simulate": "succeed"},
    )
    assert paid.json()["invoice_status"] == "paid"
    other = _create_shipment(client, "void")
    oid = other["shipment_id"]
    client.post(f"/api/nova/freight/shipments/{oid}/quote", headers=dispatcher, json={"estimated_miles": 8})
    client.post(f"/api/nova/freight/shipments/{oid}/quote/finalize", headers=dispatcher)
    _accept_and_complete(client, oid, "voidx")
    first = client.post(f"/api/nova/freight/shipments/{oid}/invoice", headers=dispatcher)
    voided = client.post(f"/api/nova/freight/shipments/{oid}/invoice/void", headers=dispatcher)
    assert voided.status_code == 200
    assert voided.json()["invoice_status"] == "void"
    recreated = client.post(f"/api/nova/freight/shipments/{oid}/invoice", headers=dispatcher)
    assert recreated.status_code == 201, recreated.text
    assert recreated.json()["invoice_id"] != first.json()["invoice_id"]


def test_cancel_role_tenant_proof_and_margin(client: TestClient) -> None:
    shipment = _create_shipment(client, "sec")
    sid = shipment["shipment_id"]
    dispatcher = _headers(client, "dispatcher@amicor.local")
    rider = _headers(client, "rider@amicor.local")
    cancelled = client.post(f"/api/nova/freight/shipments/{sid}/cancel", headers=rider)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    again = client.post(f"/api/nova/freight/shipments/{sid}/cancel", headers=dispatcher)
    assert again.status_code == 200
    paid_ship = _create_shipment(client, "sec2")
    _quote_pay_payout(client, paid_ship["shipment_id"])
    blocked = client.post(
        f"/api/nova/freight/shipments/{paid_ship['shipment_id']}/cancel",
        headers=dispatcher,
    )
    assert blocked.status_code == 409
    detail = client.get(f"/api/nova/freight/shipments/{paid_ship['shipment_id']}", headers=rider)
    assert detail.json()["amicor_margin"] is None
    assert detail.json()["carrier_payout_amount"] is None
    quote = client.get(
        f"/api/nova/freight/shipments/{paid_ship['shipment_id']}/quote/customer",
        headers=rider,
    )
    assert "estimated_amicor_margin" not in quote.json()
    finance = client.get("/api/nova/freight/payouts", headers=rider)
    assert finance.status_code == 403
    other_email = f"freight.p7.tenant.{uuid4()[:6]}@amicor.local"
    with SessionLocal() as db:
        db.add(
            PlatformUser(
                id=uuid4(),
                email=other_email,
                hashed_password=hash_password(SEED_PASSWORD),
                role="admin",
                organization_id=f"org-p7-{uuid4()[:8]}",
                is_active=True,
                is_verified=True,
            )
        )
        db.commit()
    hidden = client.get(
        f"/api/nova/freight/history/{paid_ship['shipment_id']}",
        headers=_headers(client, other_email),
    )
    assert hidden.status_code == 404
    proofs = client.get(
        f"/api/nova/freight/shipments/{paid_ship['shipment_id']}/proofs",
        headers=dispatcher,
    )
    assert proofs.status_code == 200
    assert proofs.json()
    assert "nova_freight_proofs" not in str(proofs.json())
    assert ":\\" not in str(proofs.json())
    assert "/data/" not in str(proofs.json())
    unauth_proof = client.get(
        f"/api/nova/freight/shipments/{paid_ship['shipment_id']}/proofs/{proofs.json()[0]['proof_id']}/file"
    )
    assert unauth_proof.status_code == 401


def test_invalid_money_and_live_keys(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    shipment = _create_shipment(client, "money")
    denied = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"quoted_amount": "-1.00"},
    )
    assert denied.status_code == 409
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_notarealkey")
    with pytest.raises(NovaFreightError) as exc:
        assert_test_payout_mode()
    assert exc.value.status_code == 503


def test_dashboard_counts_match_database_and_isolation(client: TestClient) -> None:
    shipment = _create_shipment(client, "ops")
    _quote_pay_payout(client, shipment["shipment_id"])
    dispatcher = _headers(client, "dispatcher@amicor.local")
    org = _org_id("dispatcher@amicor.local")
    summary = client.get("/api/nova/freight/ops/summary", headers=dispatcher)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    with SessionLocal() as db:
        assert body["awaiting_dispatch"] == db.query(NovaFreightShipment).filter(
            NovaFreightShipment.organization_id == org,
            NovaFreightShipment.status == "ready_for_dispatch",
        ).count()
        assert body["paid_invoices"] == db.query(NovaFreightInvoice).filter(
            NovaFreightInvoice.organization_id == org,
            NovaFreightInvoice.invoice_status == "paid",
        ).count()
        assert body["paid_payouts"] == db.query(NovaFreightPayout).filter(
            NovaFreightPayout.organization_id == org,
            NovaFreightPayout.payout_status == "paid",
        ).count()
        assert db.query(NovaFreightSettlement).filter(
            NovaFreightSettlement.organization_id == org,
            NovaFreightSettlement.payout_id.isnot(None),
        ).count() == body["paid_payouts"]
        assert db.query(AmicorCustomerPayment).filter(
            AmicorCustomerPayment.internal_service_id == shipment["shipment_id"]
        ).count() == 0
        delivery = db.query(AmicorCustomerPayment).count()
        health_payouts = db.query(HealthISFPayout).count()
        health_ledger = db.query(HealthISFSettlementLedger).count()
        driver_apps = db.query(PlatformDriverOnboardingApplication).count()
    rider_ops = client.get("/api/nova/freight/ops/summary", headers=_headers(client, "rider@amicor.local"))
    assert rider_ops.status_code == 403
    assert NovaFreightPayout.__tablename__ == "nova_freight_payouts"
    assert HealthISFPayout.__tablename__ == "health_isf_payouts"
    assert AmicorCustomerPayment.__tablename__ == "amicor_customer_payments"
    pages = [
        client.get("/nova/freight/ops"),
        client.get("/nova/freight/history"),
        client.get("/nova/freight/finance"),
        client.get("/nova/freight/carrier/earnings"),
    ]
    assert all(page.status_code == 200 for page in pages)
    assert "Operational counts" in OPS_PAGE
    assert "Completed Freight History" in HISTORY_PAGE
    assert "metric-grid" in FREIGHT_CSS
    assert "AMICOR Delivery" in OPS_HTML
    unauth = client.get("/api/nova/freight/ops/summary")
    assert unauth.status_code == 401
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/nova/freight/ops/summary" in paths
    assert "/api/nova/freight/history" in paths
    assert "/api/nova/freight/shipments/{shipment_id}/cancel" in paths
    with SessionLocal() as db:
        assert db.query(AmicorCustomerPayment).count() == delivery
        assert db.query(HealthISFPayout).count() == health_payouts
        assert db.query(HealthISFSettlementLedger).count() == health_ledger
        assert db.query(PlatformDriverOnboardingApplication).count() == driver_apps
    live = client.get("/api/health/live")
    assert live.status_code == 200
    rides = client.get("/api/health-isf/rides", headers=dispatcher)
    assert rides.status_code == 200
    _ = NovaFreightOffer
