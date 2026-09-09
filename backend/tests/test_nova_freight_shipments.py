"""Nova Freight V1 Phase 1 — shipment intake APIs, auth isolation, UI smoke."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, hash_password, seed_default_users
from app.core.nova.freight.models import NovaFreightShipment
from app.core.nova.freight.schemas import NovaFreightShipmentCreate
from app.core.nova.freight import service as freight_service
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal, init_platform_db
from app.helpers import uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
FREIGHT_HTML = (ROOT / "static" / "nova-freight" / "index.html").read_text(encoding="utf-8")
OPS_HTML = (ROOT / "static" / "ops-shell.html").read_text(encoding="utf-8")


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


def _valid_payload(**overrides) -> dict:
    payload = {
        "customer_name": "Northstar Shippers",
        "contact_name": "Ada Freight",
        "contact_phone": "612-555-0100",
        "contact_email": "ada@northstar.example",
        "pickup_address": "100 Warehouse Rd",
        "pickup_city": "Minneapolis",
        "pickup_state": "MN",
        "pickup_zip": "55401",
        "pickup_contact": "Dock 2",
        "pickup_phone": "612-555-0101",
        "pickup_window_start": "2026-09-10T09:00:00-05:00",
        "pickup_window_end": "2026-09-10T12:00:00-05:00",
        "delivery_address": "900 Receiving Ave",
        "delivery_city": "St Paul",
        "delivery_state": "MN",
        "delivery_zip": "55101",
        "delivery_contact": "Receiving",
        "delivery_phone": "651-555-0199",
        "delivery_window_start": "2026-09-10T14:00:00-05:00",
        "delivery_window_end": "2026-09-10T17:00:00-05:00",
        "commodity": "Palletized packaged goods",
        "quantity": 12,
        "weight": 2400,
        "weight_unit": "lb",
        "piece_count": 12,
        "pallet_count": 4,
        "length_in": 48,
        "width_in": 40,
        "height_in": 48,
        "special_handling_notes": "Keep upright",
        "hazardous": False,
        "temperature_controlled": False,
        "fragile": True,
        "equipment_type": "box_truck",
    }
    payload.update(overrides)
    return payload


def _create_other_org_user() -> str:
    email = f"freight.other.{uuid4()[:8]}@amicor.local"
    with SessionLocal() as db:
        user = PlatformUser(
            id=uuid4(),
            email=email,
            hashed_password=hash_password(SEED_PASSWORD),
            display_name="Other Org Shipper",
            role="rider",
            organization_name="Other Freight Org",
            organization_id=f"org-freight-{uuid4()[:8]}",
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.commit()
    return email


def test_create_shipment_successfully(client: TestClient) -> None:
    response = client.post(
        "/api/nova/freight/shipments",
        headers=_headers(client, "rider@amicor.local"),
        json=_valid_payload(),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["shipment_id"].startswith("NF-")
    assert body["status"] == "ready_for_dispatch"
    assert body["commodity"] == "Palletized packaged goods"
    assert body["equipment_type"] == "box_truck"
    assert body["pickup_city"] == "Minneapolis"
    assert body["delivery_city"] == "St Paul"
    assert body["organization_id"]
    assert "quoted_amount" in body
    assert "proof_of_delivery_ref" in body


def test_required_field_validation(client: TestClient) -> None:
    response = client.post(
        "/api/nova/freight/shipments",
        headers=_headers(client, "rider@amicor.local"),
        json={"customer_name": "Missing Load"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    fields = {item["loc"][-1] for item in detail if isinstance(item, dict)}
    assert "pickup_address" in fields
    assert "delivery_address" in fields
    assert "commodity" in fields


def test_invalid_weight_and_date_rejected(client: TestClient) -> None:
    headers = _headers(client, "rider@amicor.local")
    weight = client.post(
        "/api/nova/freight/shipments",
        headers=headers,
        json=_valid_payload(weight=0),
    )
    assert weight.status_code == 422
    dates = client.post(
        "/api/nova/freight/shipments",
        headers=headers,
        json=_valid_payload(
            pickup_window_start="2026-09-10T15:00:00-05:00",
            pickup_window_end="2026-09-10T09:00:00-05:00",
        ),
    )
    assert dates.status_code == 422


def test_list_and_retrieve_shipment(client: TestClient) -> None:
    headers = _headers(client, "rider@amicor.local")
    created = client.post(
        "/api/nova/freight/shipments",
        headers=headers,
        json=_valid_payload(commodity="Listed freight lot"),
    )
    assert created.status_code == 201
    shipment_id = created.json()["shipment_id"]

    listed = client.get("/api/nova/freight/shipments", headers=headers)
    assert listed.status_code == 200
    ids = [row["shipment_id"] for row in listed.json()]
    assert shipment_id in ids

    fetched = client.get(f"/api/nova/freight/shipments/{shipment_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["commodity"] == "Listed freight lot"


def test_update_allowed_pre_dispatch_fields(client: TestClient) -> None:
    headers = _headers(client, "admin@amicor.local")
    created = client.post(
        "/api/nova/freight/shipments",
        headers=headers,
        json=_valid_payload(commodity="Original commodity"),
    )
    shipment_id = created.json()["shipment_id"]
    patched = client.patch(
        f"/api/nova/freight/shipments/{shipment_id}",
        headers=headers,
        json={"commodity": "Updated commodity", "weight": 1800},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["commodity"] == "Updated commodity"
    assert float(patched.json()["weight"]) == 1800

    with SessionLocal() as db:
        row = db.query(NovaFreightShipment).filter(NovaFreightShipment.shipment_id == shipment_id).one()
        row.status = "assigned"
        db.commit()
    blocked = client.patch(
        f"/api/nova/freight/shipments/{shipment_id}",
        headers=headers,
        json={"commodity": "Too late"},
    )
    assert blocked.status_code == 409


def test_unauthorized_access_rejected(client: TestClient) -> None:
    response = client.get("/api/nova/freight/shipments")
    assert response.status_code == 401

    driver = client.get(
        "/api/nova/freight/shipments",
        headers=_headers(client, "driver@amicor.local"),
    )
    assert driver.status_code == 403


def test_tenant_isolation(client: TestClient) -> None:
    rider_headers = _headers(client, "rider@amicor.local")
    created = client.post(
        "/api/nova/freight/shipments",
        headers=rider_headers,
        json=_valid_payload(commodity="Tenant A load"),
    )
    shipment_id = created.json()["shipment_id"]
    other_headers = _headers(client, _create_other_org_user())

    hidden = client.get(f"/api/nova/freight/shipments/{shipment_id}", headers=other_headers)
    assert hidden.status_code == 404

    listed = client.get("/api/nova/freight/shipments", headers=other_headers)
    assert listed.status_code == 200
    assert shipment_id not in [row["shipment_id"] for row in listed.json()]


def test_shipment_id_uniqueness(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    headers = _headers(client, "rider@amicor.local")
    first = client.post("/api/nova/freight/shipments", headers=headers, json=_valid_payload())
    second = client.post("/api/nova/freight/shipments", headers=headers, json=_valid_payload())
    assert first.json()["shipment_id"] != second.json()["shipment_id"]

    colliding = ["NF-COLLIDE01", "NF-COLLIDE01", "NF-UNIQUE009"]
    monkeypatch.setattr(freight_service, "_new_shipment_id", lambda: colliding.pop(0))
    with SessionLocal() as db:
        one_id = freight_service.create_shipment(
            db,
            NovaFreightShipmentCreate.model_validate(_valid_payload(commodity="Collision A")),
            organization_id="org-collision-a",
            user_id="user-a",
        ).shipment_id
        two_id = freight_service.create_shipment(
            db,
            NovaFreightShipmentCreate.model_validate(_valid_payload(commodity="Collision B")),
            organization_id="org-collision-a",
            user_id="user-a",
        ).shipment_id
    assert one_id != two_id
    assert two_id == "NF-UNIQUE009"


def test_shipper_form_saves_and_lists(client: TestClient) -> None:
    page = client.get("/nova/freight")
    assert page.status_code == 200
    assert "AMICOR Nova" in page.text
    assert "Freight / Logistics" in page.text
    assert "New Freight Request" in page.text
    assert "My Shipments / Shipment Requests" in page.text
    assert "/api/nova/freight/shipments" in FREIGHT_HTML or "freight-form" in FREIGHT_HTML

    headers = _headers(client, "rider@amicor.local")
    created = client.post(
        "/api/nova/freight/shipments",
        headers=headers,
        json=_valid_payload(commodity="UI smoke pallet"),
    )
    assert created.status_code == 201
    shipment_id = created.json()["shipment_id"]
    listed = client.get("/api/nova/freight/shipments", headers=headers)
    assert any(row["shipment_id"] == shipment_id for row in listed.json())
    detail_page = client.get(f"/nova/freight/shipments/{shipment_id}")
    assert detail_page.status_code == 200
    assert "AMICOR Nova" in detail_page.text


def test_health_and_delivery_surfaces_unchanged(client: TestClient) -> None:
    live = client.get("/api/health/live")
    assert live.status_code == 200
    assert "AMICOR Delivery" in OPS_HTML
    rides = client.get("/api/health-isf/rides", headers=_headers(client, "dispatcher@amicor.local"))
    assert rides.status_code == 200
    assert NovaFreightShipment.__tablename__ == "nova_freight_shipments"
    assert NovaFreightShipment.__tablename__ != "health_isf_rides"
