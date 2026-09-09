"""Nova Freight V1 Phase 3 — shipment execution lifecycle."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, hash_password, seed_default_users
from app.core.nova.freight.models import NovaFreightOffer, NovaFreightShipment, NovaFreightShipmentEvent
from app.core.nova.freight.schemas import FORWARD_TRANSITIONS
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal, init_platform_db
from app.helpers import uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
OPS_HTML = (ROOT / "static" / "ops-shell.html").read_text(encoding="utf-8")
EXECUTE_HTML = (ROOT / "static" / "nova-freight" / "execute.html").read_text(encoding="utf-8")

STEPS = list(FORWARD_TRANSITIONS.items())


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


def _accept_ready(client: TestClient, email_suffix: str) -> tuple[dict, dict, dict[str, str]]:
    org = _org_id("dispatcher@amicor.local")
    driver_email = f"freight.life.{email_suffix}@amicor.local"
    driver_id = _create_driver(driver_email, org)
    shipment = client.post(
        "/api/nova/freight/shipments",
        headers=_headers(client, "rider@amicor.local"),
        json={
            "customer_name": "Lifecycle Shipper",
            "pickup_address": "1 Dock",
            "pickup_city": "Minneapolis",
            "pickup_state": "MN",
            "pickup_zip": "55401",
            "delivery_address": "9 Yard",
            "delivery_city": "Duluth",
            "delivery_state": "MN",
            "delivery_zip": "55802",
            "commodity": "Lifecycle freight",
            "weight": 900,
            "equipment_type": "box_truck",
        },
    )
    assert shipment.status_code == 201, shipment.text
    carrier = client.post(
        "/api/nova/freight/carriers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"name": f"Life Carrier {email_suffix}", "equipment_type": "box_truck", "user_id": driver_id},
    )
    assert carrier.status_code == 201, carrier.text
    offers = client.post(
        f"/api/nova/freight/shipments/{shipment.json()['shipment_id']}/offers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"carrier_ids": [carrier.json()["carrier_id"]]},
    )
    assert offers.status_code == 201, offers.text
    accepted = client.post(
        f"/api/nova/freight/offers/{offers.json()[0]['offer_id']}/accept",
        headers=_headers(client, driver_email),
    )
    assert accepted.status_code == 200, accepted.text
    return shipment.json(), carrier.json(), {"driver": driver_email, "dispatcher": "dispatcher@amicor.local"}


def _set_status(db_status: str, shipment_id: str) -> None:
    with SessionLocal() as db:
        row = db.query(NovaFreightShipment).filter(NovaFreightShipment.shipment_id == shipment_id).one()
        row.status = db_status
        db.commit()


def test_each_forward_transition(client: TestClient) -> None:
    for current, nxt in STEPS:
        shipment, _carrier, actors = _accept_ready(client, f"{current[:8]}{nxt[:8]}")
        _set_status(current, shipment["shipment_id"])
        response = client.post(
            f"/api/nova/freight/shipments/{shipment['shipment_id']}/status",
            headers=_headers(client, actors["driver"]),
            json={"status": nxt, "notes": f"{current} to {nxt}"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == nxt


def test_full_lifecycle_and_history(client: TestClient) -> None:
    shipment, carrier, actors = _accept_ready(client, "full")
    sid = shipment["shipment_id"]
    driver = _headers(client, actors["driver"])
    status = "accepted"
    for current, nxt in STEPS:
        assert status == current
        moved = client.post(f"/api/nova/freight/shipments/{sid}/status", headers=driver, json={"status": nxt})
        assert moved.status_code == 200, moved.text
        status = moved.json()["status"]
    assert status == "completed"
    events = client.get(f"/api/nova/freight/shipments/{sid}/events", headers=driver)
    assert events.status_code == 200
    pairs = [(row["status_before"], row["status_after"]) for row in events.json()]
    assert pairs == STEPS
    with SessionLocal() as db:
        assert db.query(NovaFreightShipmentEvent).filter(NovaFreightShipmentEvent.shipment_id == sid).count() == len(STEPS)
        open_offers = (
            db.query(NovaFreightOffer)
            .filter(NovaFreightOffer.shipment_id == sid, NovaFreightOffer.status == "pending")
            .count()
        )
        assert open_offers == 0
        row = db.query(NovaFreightShipment).filter(NovaFreightShipment.shipment_id == sid).one()
        assert row.assigned_carrier_id == carrier["carrier_id"]
    active = client.get("/api/nova/freight/carrier/shipments", headers=driver)
    assert sid not in [row["shipment_id"] for row in active.json()]
    board = client.get("/api/nova/freight/dispatch/shipments", headers=_headers(client, actors["dispatcher"]))
    assert sid not in [row["shipment_id"] for row in board.json()]
    completed = client.get(
        "/api/nova/freight/dispatch/shipments?status=completed",
        headers=_headers(client, actors["dispatcher"]),
    )
    assert sid in [row["shipment_id"] for row in completed.json()]


def test_skipped_and_backward_rejected(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "skip")
    driver = _headers(client, actors["driver"])
    skipped = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/status",
        headers=driver,
        json={"status": "picked_up"},
    )
    assert skipped.status_code == 409
    backward = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/status",
        headers=driver,
        json={"status": "ready_for_dispatch"},
    )
    assert backward.status_code == 409


def test_non_assigned_carrier_rejected(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "na")
    org = _org_id("dispatcher@amicor.local")
    other_email = "freight.life.other@amicor.local"
    other_id = _create_driver(other_email, org)
    client.post(
        "/api/nova/freight/carriers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"name": "Other Life Carrier", "user_id": other_id, "equipment_type": "box_truck"},
    )
    denied = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/status",
        headers=_headers(client, other_email),
        json={"status": "en_route_to_pickup"},
    )
    assert denied.status_code == 403


def test_tenant_isolation_execution(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "ten")
    other_email = f"freight.life.tenant.{uuid4()[:6]}@amicor.local"
    with SessionLocal() as db:
        db.add(
            PlatformUser(
                id=uuid4(),
                email=other_email,
                hashed_password=hash_password(SEED_PASSWORD),
                role="driver",
                organization_id=f"org-life-{uuid4()[:8]}",
                is_active=True,
                is_verified=True,
            )
        )
        db.commit()
    hidden = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/status",
        headers=_headers(client, other_email),
        json={"status": "en_route_to_pickup"},
    )
    assert hidden.status_code == 404


def test_cancelled_and_unaccepted_cannot_start(client: TestClient) -> None:
    created = client.post(
        "/api/nova/freight/shipments",
        headers=_headers(client, "rider@amicor.local"),
        json={
            "customer_name": "Blocked Start",
            "pickup_address": "1 A",
            "pickup_city": "Minneapolis",
            "pickup_state": "MN",
            "pickup_zip": "55401",
            "delivery_address": "2 B",
            "delivery_city": "Duluth",
            "delivery_state": "MN",
            "delivery_zip": "55802",
            "commodity": "Blocked",
            "equipment_type": "van",
        },
    ).json()
    unaccepted = client.post(
        f"/api/nova/freight/shipments/{created['shipment_id']}/status",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"status": "en_route_to_pickup"},
    )
    assert unaccepted.status_code == 409
    with SessionLocal() as db:
        row = db.query(NovaFreightShipment).filter(NovaFreightShipment.shipment_id == created["shipment_id"]).one()
        row.status = "cancelled"
        db.commit()
    cancelled = client.post(
        f"/api/nova/freight/shipments/{created['shipment_id']}/status",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"status": "en_route_to_pickup"},
    )
    assert cancelled.status_code == 409


def test_duplicate_same_action_and_completed_lock(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "dup")
    driver = _headers(client, actors["driver"])
    first = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/status",
        headers=driver,
        json={"status": "en_route_to_pickup"},
    )
    again = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/status",
        headers=driver,
        json={"status": "en_route_to_pickup"},
    )
    assert first.status_code == 200
    assert again.status_code == 200
    assert again.json()["status"] == "en_route_to_pickup"
    events = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/events",
        headers=driver,
    ).json()
    assert len([row for row in events if row["status_after"] == "en_route_to_pickup"]) == 1
    _set_status("completed", shipment["shipment_id"])
    restart = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/status",
        headers=driver,
        json={"status": "en_route_to_pickup"},
    )
    assert restart.status_code == 409


def test_execution_pages_and_regression_surfaces(client: TestClient) -> None:
    page = client.get("/nova/freight/carrier/shipments")
    assert page.status_code == 200
    assert "Freight Shipment Execution" in EXECUTE_HTML
    assert "Start Trip to Pickup" in (ROOT / "static" / "nova-freight" / "execute.js").read_text(encoding="utf-8")
    unauth = client.post("/api/nova/freight/shipments/NF-NONE/status", json={"status": "en_route_to_pickup"})
    assert unauth.status_code == 401
    assert "AMICOR Delivery" in OPS_HTML
    live = client.get("/api/health/live")
    assert live.status_code == 200
    rides = client.get("/api/health-isf/rides", headers=_headers(client, "dispatcher@amicor.local"))
    assert rides.status_code == 200
