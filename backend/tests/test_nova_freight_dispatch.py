"""Nova Freight V1 Phase 2 — dispatch board, offers, first-accept-wins."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, hash_password, seed_default_users
from app.core.nova.freight.models import NovaFreightOffer, NovaFreightShipment
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal, init_platform_db
from app.helpers import uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
NOVA_JS = (ROOT / "static" / "modules" / "nova" / "nova.js").read_text(encoding="utf-8")
OPS_HTML = (ROOT / "static" / "ops-shell.html").read_text(encoding="utf-8")
DISPATCH_HTML = (ROOT / "static" / "nova-freight" / "dispatch.html").read_text(encoding="utf-8")
CARRIER_JS = (ROOT / "static" / "nova-freight" / "carrier.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    init_platform_db()
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(client: TestClient, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, email)['access_token']}"}


def _shipment_payload(**overrides) -> dict:
    payload = {
        "customer_name": "Phase 2 Shipper",
        "pickup_address": "11 Yard Rd",
        "pickup_city": "Minneapolis",
        "pickup_state": "MN",
        "pickup_zip": "55401",
        "delivery_address": "88 Dock Ave",
        "delivery_city": "Duluth",
        "delivery_state": "MN",
        "delivery_zip": "55802",
        "commodity": "Steel coils",
        "weight": 22000,
        "equipment_type": "flatbed",
    }
    payload.update(overrides)
    return payload


def _create_shipment(client: TestClient, email: str = "rider@amicor.local", **overrides) -> dict:
    response = client.post(
        "/api/nova/freight/shipments",
        headers=_headers(client, email),
        json=_shipment_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_driver_user(email: str, organization_id: str) -> str:
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
            organization_name="Nova Freight Test Org",
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.commit()
        return user.id


def _org_id(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user and user.organization_id
        return user.organization_id


def _create_carrier(client: TestClient, name: str, user_id: str | None = None, **overrides) -> dict:
    payload = {
        "name": name,
        "equipment_type": "flatbed",
        "service_area": "MN",
        "availability": "available",
        "user_id": user_id,
    }
    payload.update(overrides)
    response = client.post("/api/nova/freight/carriers", headers=_headers(client, "dispatcher@amicor.local"), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_ready_for_dispatch_appears_on_board(client: TestClient) -> None:
    created = _create_shipment(client, commodity="Board visible load")
    board = client.get("/api/nova/freight/dispatch/shipments", headers=_headers(client, "dispatcher@amicor.local"))
    assert board.status_code == 200, board.text
    ids = [row["shipment_id"] for row in board.json()]
    assert created["shipment_id"] in ids
    page = client.get("/nova/freight/dispatch")
    assert page.status_code == 200
    assert "Freight Dispatch Board" in page.text
    assert "AMICOR Nova" in DISPATCH_HTML


def test_offer_can_be_created(client: TestClient) -> None:
    shipment = _create_shipment(client)
    org = _org_id("dispatcher@amicor.local")
    driver_id = _create_driver_user("freight.carrier.a@amicor.local", org)
    carrier = _create_carrier(client, "Northstar Flatbed A", user_id=driver_id)
    offered = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/offers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"carrier_ids": [carrier["carrier_id"]]},
    )
    assert offered.status_code == 201, offered.text
    assert offered.json()[0]["status"] == "pending"
    shipment_row = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}",
        headers=_headers(client, "dispatcher@amicor.local"),
    )
    assert shipment_row.json()["status"] == "offered"


def test_unauthorized_user_cannot_create_offers(client: TestClient) -> None:
    shipment = _create_shipment(client)
    org = _org_id("dispatcher@amicor.local")
    driver_id = _create_driver_user("freight.carrier.b@amicor.local", org)
    carrier = _create_carrier(client, "Unauthorized target", user_id=driver_id)
    rider = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/offers",
        headers=_headers(client, "rider@amicor.local"),
        json={"carrier_ids": [carrier["carrier_id"]]},
    )
    assert rider.status_code == 403
    anon = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/offers",
        json={"carrier_ids": [carrier["carrier_id"]]},
    )
    assert anon.status_code == 401


def test_carrier_can_only_see_permitted_offers(client: TestClient) -> None:
    shipment = _create_shipment(client)
    org = _org_id("dispatcher@amicor.local")
    driver_a = _create_driver_user("freight.see.a@amicor.local", org)
    driver_b = _create_driver_user("freight.see.b@amicor.local", org)
    carrier_a = _create_carrier(client, "See A", user_id=driver_a)
    carrier_b = _create_carrier(client, "See B", user_id=driver_b)
    client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/offers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"carrier_ids": [carrier_a["carrier_id"], carrier_b["carrier_id"]]},
    )
    seen_a = client.get("/api/nova/freight/offers", headers=_headers(client, "freight.see.a@amicor.local"))
    seen_b = client.get("/api/nova/freight/offers", headers=_headers(client, "freight.see.b@amicor.local"))
    assert seen_a.status_code == 200
    assert {row["carrier_id"] for row in seen_a.json()} == {carrier_a["carrier_id"]}
    assert {row["carrier_id"] for row in seen_b.json()} == {carrier_b["carrier_id"]}


def test_carrier_can_accept(client: TestClient) -> None:
    shipment = _create_shipment(client)
    org = _org_id("dispatcher@amicor.local")
    driver_id = _create_driver_user("freight.accept@amicor.local", org)
    carrier = _create_carrier(client, "Accept Carrier", user_id=driver_id)
    offers = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/offers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"carrier_ids": [carrier["carrier_id"]]},
    ).json()
    accepted = client.post(
        f"/api/nova/freight/offers/{offers[0]['offer_id']}/accept",
        headers=_headers(client, "freight.accept@amicor.local"),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["shipment_status"] == "accepted"
    loaded = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}",
        headers=_headers(client, "dispatcher@amicor.local"),
    ).json()
    assert loaded["assigned_carrier_id"] == carrier["carrier_id"]
    assert loaded["status"] == "accepted"


def test_carrier_can_decline_and_return_to_ready(client: TestClient) -> None:
    shipment = _create_shipment(client)
    org = _org_id("dispatcher@amicor.local")
    driver_id = _create_driver_user("freight.decline@amicor.local", org)
    carrier = _create_carrier(client, "Decline Carrier", user_id=driver_id)
    offers = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/offers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"carrier_ids": [carrier["carrier_id"]]},
    ).json()
    declined = client.post(
        f"/api/nova/freight/offers/{offers[0]['offer_id']}/decline",
        headers=_headers(client, "freight.decline@amicor.local"),
    )
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "declined"
    loaded = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}",
        headers=_headers(client, "dispatcher@amicor.local"),
    ).json()
    assert loaded["status"] == "ready_for_dispatch"
    assert loaded["assigned_carrier_id"] is None


def test_first_accept_wins_and_duplicate_conflicts(client: TestClient) -> None:
    shipment = _create_shipment(client)
    org = _org_id("dispatcher@amicor.local")
    driver_a = _create_driver_user("freight.win.a@amicor.local", org)
    driver_b = _create_driver_user("freight.win.b@amicor.local", org)
    carrier_a = _create_carrier(client, "Win A", user_id=driver_a)
    carrier_b = _create_carrier(client, "Win B", user_id=driver_b)
    offers = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/offers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"carrier_ids": [carrier_a["carrier_id"], carrier_b["carrier_id"]]},
    ).json()
    by_carrier = {row["carrier_id"]: row["offer_id"] for row in offers}
    first = client.post(
        f"/api/nova/freight/offers/{by_carrier[carrier_a['carrier_id']]}/accept",
        headers=_headers(client, "freight.win.a@amicor.local"),
    )
    second = client.post(
        f"/api/nova/freight/offers/{by_carrier[carrier_b['carrier_id']]}/accept",
        headers=_headers(client, "freight.win.b@amicor.local"),
    )
    duplicate = client.post(
        f"/api/nova/freight/offers/{by_carrier[carrier_a['carrier_id']]}/accept",
        headers=_headers(client, "freight.win.a@amicor.local"),
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 409
    assert duplicate.status_code == 409
    listed = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/offers",
        headers=_headers(client, "dispatcher@amicor.local"),
    ).json()
    accepted = [row for row in listed if row["status"] == "accepted"]
    cancelled = [row for row in listed if row["status"] == "cancelled"]
    assert len(accepted) == 1
    assert accepted[0]["carrier_id"] == carrier_a["carrier_id"]
    assert len(cancelled) == 1
    with SessionLocal() as db:
        assignments = (
            db.query(NovaFreightShipment)
            .filter(NovaFreightShipment.shipment_id == shipment["shipment_id"])
            .all()
        )
        assert len(assignments) == 1
        assert assignments[0].assigned_carrier_id == carrier_a["carrier_id"]
        offer_rows = db.query(NovaFreightOffer).filter(NovaFreightOffer.shipment_id == shipment["shipment_id"]).all()
        assert sum(1 for row in offer_rows if row.status == "accepted") == 1


def test_tenant_isolation_dispatch(client: TestClient) -> None:
    shipment = _create_shipment(client)
    other_email = f"freight.other.dispatch.{uuid4()[:8]}@amicor.local"
    with SessionLocal() as db:
        db.add(
            PlatformUser(
                id=uuid4(),
                email=other_email,
                hashed_password=hash_password(SEED_PASSWORD),
                display_name="Other Dispatcher",
                role="dispatcher",
                organization_id=f"org-freight-other-{uuid4()[:8]}",
                organization_name="Other Freight Org",
                is_active=True,
                is_verified=True,
            )
        )
        db.commit()
    board = client.get("/api/nova/freight/dispatch/shipments", headers=_headers(client, other_email))
    assert board.status_code == 200
    assert shipment["shipment_id"] not in [row["shipment_id"] for row in board.json()]


def test_carrier_offer_page_and_persona_display(client: TestClient) -> None:
    page = client.get("/nova/freight/carrier/offers")
    assert page.status_code == 200
    assert "Freight Carrier Offers" in page.text
    assert "ACCEPT" in CARRIER_JS
    assert "DECLINE" in CARRIER_JS
    assert "Mrs. Nova Brain" in INDEX_HTML
    assert "Ask Mrs. Nova Brain" in INDEX_HTML
    assert "Mrs. Nova Brain" in NOVA_JS
    assert "Mr. Nova Brain" not in INDEX_HTML
    assert "Mr. Nova Brin" not in INDEX_HTML
    assert "Mrs. Nova Brin" not in INDEX_HTML
    assert "Nova Brin" not in INDEX_HTML
    assert "Mr. Nova Brain" not in NOVA_JS
    nova = client.get("/openapi.json")
    assert nova.status_code == 200
    paths = nova.json()["paths"]
    assert "/api/nova/freight/shipments" in paths
    assert "/api/nova/status" in paths or any(path.startswith("/api/nova/") for path in paths)
    from app.core.nova.service import NovaCoreService
    assert NovaCoreService.__name__ == "NovaCoreService"


def test_delivery_and_health_surfaces_untouched(client: TestClient) -> None:
    assert "AMICOR Delivery" in OPS_HTML
    live = client.get("/api/health/live")
    assert live.status_code == 200
    rides = client.get("/api/health-isf/rides", headers=_headers(client, "dispatcher@amicor.local"))
    assert rides.status_code == 200
