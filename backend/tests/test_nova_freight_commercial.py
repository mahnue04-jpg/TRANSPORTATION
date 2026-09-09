"""Nova Freight V1 Phase 5 — rates, invoices, and Stripe TEST customer charges."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, hash_password, seed_default_users
from app.core.nova.freight.models import (
    NovaFreightInvoice,
    NovaFreightPaymentEvent,
    NovaFreightQuote,
    NovaFreightShipment,
    NovaFreightShipmentEvent,
)
from app.core.nova.freight.money import money, to_minor_units
from app.core.nova.freight.rates import suggested_quote
from app.core.nova.freight.stripe_checkout import FakeNovaFreightStripeClient, set_nova_freight_stripe_override
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal, init_platform_db
from app.helpers import uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
OPS_HTML = (ROOT / "static" / "ops-shell.html").read_text(encoding="utf-8")
DISPATCH_HTML = (ROOT / "static" / "nova-freight" / "dispatch.html").read_text(encoding="utf-8")
FREIGHT_HTML = (ROOT / "static" / "nova-freight" / "index.html").read_text(encoding="utf-8")


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
            "customer_name": f"Commercial {suffix}",
            "pickup_address": "1 Dock",
            "pickup_city": "Minneapolis",
            "pickup_state": "MN",
            "pickup_zip": "55401",
            "delivery_address": "9 Yard",
            "delivery_city": "Duluth",
            "delivery_state": "MN",
            "delivery_zip": "55802",
            "commodity": "Quoted freight",
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
    driver_email = f"freight.pay.{suffix}@amicor.local"
    driver_id = _create_driver(driver_email, org)
    carrier = client.post(
        "/api/nova/freight/carriers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"name": f"Pay Carrier {suffix}", "equipment_type": "box_truck", "user_id": driver_id},
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
            pop = client.post(
                f"/api/nova/freight/shipments/{shipment_id}/proofs",
                headers=driver,
                json={"proof_type": "pickup_photo", "document_ref": f"nfr-pop-{suffix}", "content_type": "image/jpeg"},
            )
            assert pop.status_code == 201, pop.text
        if status == "arrived_delivery":
            pod = client.post(
                f"/api/nova/freight/shipments/{shipment_id}/proofs",
                headers=driver,
                json={"proof_type": "delivery_photo", "document_ref": f"nfr-pod-{suffix}", "content_type": "image/jpeg"},
            )
            assert pod.status_code == 201, pod.text
    return {"driver": driver_email, "dispatcher": "dispatcher@amicor.local", "rider": "rider@amicor.local"}


def test_suggested_quote_calculates() -> None:
    quote = suggested_quote(
        equipment_type="box_truck",
        estimated_miles=100,
        weight=12000,
        pallet_count=2,
        fragile=True,
    )
    assert quote["tax_amount"] == Decimal("0.00")
    assert quote["fuel_surcharge"] == Decimal("0.00")
    assert quote["suggested_amount"] == money(
        Decimal("145.00") + Decimal("255.00") + Decimal("20.00") + Decimal("25.00") + Decimal("16.00")
    )
    assert quote["estimated_amicor_margin"] == money(quote["suggested_amount"] - quote["estimated_carrier_cost"])


def test_manual_quote_and_unauthorized_cannot_edit(client: TestClient) -> None:
    shipment = _create_shipment(client, "adj")
    dispatcher = _headers(client, "dispatcher@amicor.local")
    suggested = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote/suggest",
        headers=dispatcher,
        json={"estimated_miles": 80},
    )
    assert suggested.status_code == 200, suggested.text
    saved = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote",
        headers=dispatcher,
        json={
            "estimated_miles": 80,
            "quoted_amount": "499.00",
            "quote_notes": "Manual desk review",
            "customer_notes": "Flat quoted rate",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["quoted_amount"] == "499.00"
    assert saved.json()["suggested_amount"] != "499.00"
    assert saved.json()["pricing_method"] == "manual_override"
    finalized = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote/finalize",
        headers=dispatcher,
    )
    assert finalized.status_code == 200
    assert finalized.json()["pricing_status"] == "finalized"
    persisted = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote",
        headers=dispatcher,
    )
    assert persisted.json()["quoted_amount"] == "499.00"
    driver_email = f"freight.pay.noquote.{uuid4()[:6]}@amicor.local"
    _create_driver(driver_email, _org_id("dispatcher@amicor.local"))
    denied = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote",
        headers=_headers(client, driver_email),
        json={"quoted_amount": "1.00"},
    )
    assert denied.status_code == 403


def test_customer_cannot_see_internal_margin(client: TestClient) -> None:
    shipment = _create_shipment(client, "hide")
    dispatcher = _headers(client, "dispatcher@amicor.local")
    client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote",
        headers=dispatcher,
        json={"estimated_miles": 40},
    )
    client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote/finalize", headers=dispatcher)
    rider = _headers(client, "rider@amicor.local")
    customer = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote/customer",
        headers=rider,
    )
    assert customer.status_code == 200, customer.text
    body = customer.json()
    assert "estimated_amicor_margin" not in body
    assert "estimated_carrier_cost" not in body
    assert body["quoted_amount"] is not None
    detail = client.get(f"/api/nova/freight/shipments/{shipment['shipment_id']}", headers=rider)
    assert detail.status_code == 200
    assert detail.json()["amicor_margin"] is None
    assert detail.json()["carrier_payout_amount"] is None


def test_invoice_from_completed_shipment_is_idempotent(client: TestClient) -> None:
    shipment = _create_shipment(client, "inv")
    dispatcher = _headers(client, "dispatcher@amicor.local")
    saved = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote",
        headers=dispatcher,
        json={"estimated_miles": 50},
    )
    client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote/finalize", headers=dispatcher)
    early = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice", headers=dispatcher)
    assert early.status_code == 409
    _accept_and_complete(client, shipment["shipment_id"], "inv")
    first = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice", headers=dispatcher)
    second = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice", headers=dispatcher)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["invoice_id"] == second.json()["invoice_id"]
    assert first.json()["total_amount"] == saved.json()["quoted_amount"]
    assert first.json()["total_amount_minor"] == to_minor_units(saved.json()["quoted_amount"])
    with SessionLocal() as db:
        count = db.query(NovaFreightInvoice).filter(NovaFreightInvoice.shipment_id == shipment["shipment_id"]).count()
    assert count == 1


def test_stripe_test_payment_and_duplicate_guard(client: TestClient) -> None:
    shipment = _create_shipment(client, "pay")
    dispatcher = _headers(client, "dispatcher@amicor.local")
    rider = _headers(client, "rider@amicor.local")
    quote = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote",
        headers=dispatcher,
        json={"estimated_miles": 25, "customer_notes": "Ready for TEST pay"},
    )
    client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote/finalize", headers=dispatcher)
    _accept_and_complete(client, shipment["shipment_id"], "pay")
    client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice", headers=dispatcher)
    client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice/finalize", headers=dispatcher)
    rejected = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice/pay",
        headers=rider,
        json={"amount": "1.00"},
    )
    assert rejected.status_code == 409
    first = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice/pay", headers=rider, json={})
    second = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice/pay", headers=rider, json={})
    assert first.status_code == 200, first.text
    assert second.status_code == 200
    assert first.json()["stripe_payment_intent_id"] == second.json()["stripe_payment_intent_id"]
    assert second.json()["reused"] is True
    paid = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice/confirm-payment",
        headers=rider,
        json={"simulate": "succeed"},
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["invoice_status"] == "paid"
    assert paid.json()["total_amount"] == quote.json()["quoted_amount"]
    detail = client.get(f"/api/nova/freight/shipments/{shipment['shipment_id']}", headers=dispatcher)
    assert detail.json()["status"] == "completed"
    assert detail.json()["amicor_margin"] == quote.json()["estimated_amicor_margin"]
    assert detail.json()["carrier_payout_amount"] is None
    with SessionLocal() as db:
        invoices = db.query(NovaFreightInvoice).filter(NovaFreightInvoice.shipment_id == shipment["shipment_id"]).all()
        assert len(invoices) == 1
        assert invoices[0].invoice_status == "paid"
        assert db.query(NovaFreightShipment).filter(NovaFreightShipment.shipment_id == shipment["shipment_id"]).one().carrier_payout_amount is None


def test_payment_failure_and_duplicate_webhook(client: TestClient) -> None:
    shipment = _create_shipment(client, "fail")
    dispatcher = _headers(client, "dispatcher@amicor.local")
    rider = _headers(client, "rider@amicor.local")
    client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote",
        headers=dispatcher,
        json={"estimated_miles": 10},
    )
    client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote/finalize", headers=dispatcher)
    _accept_and_complete(client, shipment["shipment_id"], "fail")
    invoice = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice", headers=dispatcher).json()
    client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice/finalize", headers=dispatcher)
    started = client.post(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice/pay", headers=rider, json={})
    failed = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice/confirm-payment",
        headers=rider,
        json={"simulate": "fail"},
    )
    assert failed.status_code == 200
    assert failed.json()["invoice_status"] == "failed"
    assert failed.json()["failure_reason"]
    event = {
        "id": "evt_nf_dup_1",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": started.json()["stripe_payment_intent_id"],
                "status": "succeeded",
                "amount": invoice["total_amount_minor"],
                "amount_received": invoice["total_amount_minor"],
                "metadata": {
                    "service_type": "NOVA_FREIGHT",
                    "shipment_id": shipment["shipment_id"],
                    "invoice_id": invoice["invoice_id"],
                    "organization_id": shipment["organization_id"],
                },
            }
        },
    }
    first = client.post("/api/nova/freight/stripe/webhook", json=event)
    second = client.post("/api/nova/freight/stripe/webhook", json=event)
    assert first.status_code == 200, first.text
    assert second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    paid = client.get(f"/api/nova/freight/shipments/{shipment['shipment_id']}/invoice", headers=dispatcher)
    assert paid.json()["invoice_status"] == "paid"
    with SessionLocal() as db:
        assert db.query(NovaFreightPaymentEvent).filter(NovaFreightPaymentEvent.stripe_event_id == "evt_nf_dup_1").count() == 1


def test_cross_tenant_commercial_access_rejected(client: TestClient) -> None:
    shipment = _create_shipment(client, "ten")
    other_email = f"freight.pay.tenant.{uuid4()[:6]}@amicor.local"
    with SessionLocal() as db:
        db.add(
            PlatformUser(
                id=uuid4(),
                email=other_email,
                hashed_password=hash_password(SEED_PASSWORD),
                role="dispatcher",
                organization_id=f"org-pay-{uuid4()[:8]}",
                is_active=True,
                is_verified=True,
            )
        )
        db.commit()
    hidden = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/quote",
        headers=_headers(client, other_email),
    )
    assert hidden.status_code == 404


def test_phase5_local_e2e_and_surfaces(client: TestClient) -> None:
    shipment = _create_shipment(client, "e2e")
    sid = shipment["shipment_id"]
    dispatcher = _headers(client, "dispatcher@amicor.local")
    rider = _headers(client, "rider@amicor.local")
    client.post(f"/api/nova/freight/shipments/{sid}/quote", headers=dispatcher, json={"estimated_miles": 60})
    client.post(f"/api/nova/freight/shipments/{sid}/quote/finalize", headers=dispatcher)
    actors = _accept_and_complete(client, sid, "e2e")
    driver = _headers(client, actors["driver"])
    proofs = client.get(f"/api/nova/freight/shipments/{sid}/proofs", headers=dispatcher)
    assert proofs.status_code == 200
    assert len(proofs.json()) == 2
    late = client.post(
        f"/api/nova/freight/shipments/{sid}/proofs",
        headers=dispatcher,
        json={"proof_type": "delivery_photo", "document_ref": "nfr-e2e-late", "content_type": "image/jpeg"},
    )
    assert late.status_code == 409
    client.post(f"/api/nova/freight/shipments/{sid}/invoice", headers=dispatcher)
    invoice = client.post(f"/api/nova/freight/shipments/{sid}/invoice/finalize", headers=dispatcher)
    assert invoice.status_code == 200
    pay = client.post(f"/api/nova/freight/shipments/{sid}/invoice/pay", headers=rider, json={})
    assert pay.status_code == 200
    retry = client.post(f"/api/nova/freight/shipments/{sid}/invoice/pay", headers=rider, json={})
    assert retry.json()["reused"] is True
    paid = client.post(f"/api/nova/freight/shipments/{sid}/invoice/confirm-payment", headers=rider, json={"simulate": "succeed"})
    assert paid.json()["invoice_status"] == "paid"
    events = client.get(f"/api/nova/freight/shipments/{sid}/events", headers=dispatcher).json()
    types = {row["event_type"] for row in events}
    assert {"quote_created", "quote_finalized", "invoice_created", "invoice_finalized", "payment_started", "payment_succeeded"} <= types
    completed = client.get(f"/api/nova/freight/shipments/{sid}", headers=dispatcher).json()
    assert completed["status"] == "completed"
    assert completed["carrier_payout_amount"] is None
    assert completed["amicor_margin"] is not None
    unauth = client.post(f"/api/nova/freight/shipments/{sid}/quote/suggest", json={})
    assert unauth.status_code == 401
    nova = client.get("/openapi.json")
    paths = nova.json()["paths"]
    assert "/api/nova/freight/shipments/{shipment_id}/quote" in paths
    assert "/api/nova/freight/shipments/{shipment_id}/invoice/pay" in paths
    assert "/api/nova/freight/stripe/webhook" in paths
    assert "Commercial" in DISPATCH_HTML
    assert "Pay TEST invoice" in FREIGHT_HTML
    assert "AMICOR Delivery" in OPS_HTML
    live = client.get("/api/health/live")
    assert live.status_code == 200
    rides = client.get("/api/health-isf/rides", headers=dispatcher)
    assert rides.status_code == 200
    assert NovaFreightQuote.__tablename__ == "nova_freight_quotes"
    assert NovaFreightInvoice.__tablename__ == "nova_freight_invoices"
    _ = driver
