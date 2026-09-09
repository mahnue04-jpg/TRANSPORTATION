"""Nova Freight V1 Phase 4 — proof of pickup and proof of delivery."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, hash_password, seed_default_users
from app.core.nova.freight.models import NovaFreightProof, NovaFreightShipment, NovaFreightShipmentEvent
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal, init_platform_db
from app.helpers import uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
OPS_HTML = (ROOT / "static" / "ops-shell.html").read_text(encoding="utf-8")
EXECUTE_HTML = (ROOT / "static" / "nova-freight" / "execute.html").read_text(encoding="utf-8")
EXECUTE_JS = (ROOT / "static" / "nova-freight" / "execute.js").read_text(encoding="utf-8")
DISPATCH_HTML = (ROOT / "static" / "nova-freight" / "dispatch.html").read_text(encoding="utf-8")


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
    driver_email = f"freight.proof.{email_suffix}@amicor.local"
    driver_id = _create_driver(driver_email, org)
    shipment = client.post(
        "/api/nova/freight/shipments",
        headers=_headers(client, "rider@amicor.local"),
        json={
            "customer_name": "Proof Shipper",
            "pickup_address": "1 Dock",
            "pickup_city": "Minneapolis",
            "pickup_state": "MN",
            "pickup_zip": "55401",
            "delivery_address": "9 Yard",
            "delivery_city": "Duluth",
            "delivery_state": "MN",
            "delivery_zip": "55802",
            "commodity": "Proof freight",
            "weight": 400,
            "equipment_type": "box_truck",
        },
    )
    assert shipment.status_code == 201, shipment.text
    carrier = client.post(
        "/api/nova/freight/carriers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"name": f"Proof Carrier {email_suffix}", "equipment_type": "box_truck", "user_id": driver_id},
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


def _walk(client: TestClient, shipment_id: str, headers: dict[str, str], steps: list[str]) -> None:
    for status in steps:
        moved = client.post(
            f"/api/nova/freight/shipments/{shipment_id}/status",
            headers=headers,
            json={"status": status},
        )
        assert moved.status_code == 200, moved.text


def _add_proof(client: TestClient, shipment_id: str, headers: dict[str, str], **payload) -> object:
    body = {
        "proof_type": "pickup_photo",
        "document_ref": "nfr-" + uuid4().replace("-", "")[:12],
        "original_filename": "dock.jpg",
        "content_type": "image/jpeg",
    }
    body.update(payload)
    return client.post(
        f"/api/nova/freight/shipments/{shipment_id}/proofs",
        headers=headers,
        json=body,
    )


def test_assigned_carrier_adds_pickup_proof_at_valid_state(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "pick")
    driver = _headers(client, actors["driver"])
    _walk(client, shipment["shipment_id"], driver, ["en_route_to_pickup", "arrived_pickup"])
    added = _add_proof(
        client,
        shipment["shipment_id"],
        driver,
        notes="Dock photo",
        signer_name="Yard clerk",
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["proof_type"] == "pickup_photo"
    assert body["notes"] == "Dock photo"
    assert body["signer_name"] == "Yard clerk"
    assert body["document_ref"]
    fetched = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/proofs/{body['proof_id']}",
        headers=driver,
    )
    assert fetched.status_code == 200
    assert fetched.json()["notes"] == "Dock photo"
    assert fetched.json()["signer_name"] == "Yard clerk"
    detail = client.get(f"/api/nova/freight/shipments/{shipment['shipment_id']}", headers=driver)
    assert detail.json()["has_pickup_proof"] is True
    events = client.get(f"/api/nova/freight/shipments/{shipment['shipment_id']}/events", headers=driver).json()
    proof_events = [row for row in events if row["event_type"] == "pickup_proof_added"]
    assert len(proof_events) == 1
    assert proof_events[0]["proof_id"] == body["proof_id"]
    assert proof_events[0]["status_before"] == proof_events[0]["status_after"] == "arrived_pickup"


def test_assigned_carrier_adds_delivery_proof_at_valid_state(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "del")
    driver = _headers(client, actors["driver"])
    _walk(
        client,
        shipment["shipment_id"],
        driver,
        ["en_route_to_pickup", "arrived_pickup", "picked_up", "in_transit", "arrived_delivery"],
    )
    added = _add_proof(
        client,
        shipment["shipment_id"],
        driver,
        proof_type="delivery_signature",
        original_filename="receiver.png",
        content_type="image/png",
        signer_name="Pat Receiver",
        notes="Signed at dock",
    )
    assert added.status_code == 201, added.text
    assert added.json()["signer_name"] == "Pat Receiver"
    events = client.get(f"/api/nova/freight/shipments/{shipment['shipment_id']}/events", headers=driver).json()
    assert any(row["event_type"] == "delivery_signature_added" for row in events)


def test_pickup_and_delivery_proof_rejected_at_invalid_state(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "badst")
    driver = _headers(client, actors["driver"])
    too_early = _add_proof(client, shipment["shipment_id"], driver)
    assert too_early.status_code == 409
    _walk(client, shipment["shipment_id"], driver, ["en_route_to_pickup", "arrived_pickup"])
    delivery_too_early = _add_proof(
        client,
        shipment["shipment_id"],
        driver,
        proof_type="delivery_photo",
    )
    assert delivery_too_early.status_code == 409


def test_unaccepted_and_cancelled_cannot_upload_proof(client: TestClient) -> None:
    created = client.post(
        "/api/nova/freight/shipments",
        headers=_headers(client, "rider@amicor.local"),
        json={
            "customer_name": "Blocked Proof",
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
    unaccepted = _add_proof(
        client,
        created["shipment_id"],
        _headers(client, "dispatcher@amicor.local"),
    )
    assert unaccepted.status_code == 409
    with SessionLocal() as db:
        row = db.query(NovaFreightShipment).filter(NovaFreightShipment.shipment_id == created["shipment_id"]).one()
        row.status = "cancelled"
        db.commit()
    cancelled = _add_proof(
        client,
        created["shipment_id"],
        _headers(client, "dispatcher@amicor.local"),
    )
    assert cancelled.status_code == 409


def test_non_assigned_carrier_and_cross_tenant_rejected(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "deny")
    driver = _headers(client, actors["driver"])
    _walk(client, shipment["shipment_id"], driver, ["en_route_to_pickup", "arrived_pickup"])
    org = _org_id("dispatcher@amicor.local")
    other_email = f"freight.proof.other.{uuid4()[:6]}@amicor.local"
    other_id = _create_driver(other_email, org)
    other_carrier = client.post(
        "/api/nova/freight/carriers",
        headers=_headers(client, "dispatcher@amicor.local"),
        json={"name": "Other Proof Carrier", "equipment_type": "box_truck", "user_id": other_id},
    )
    assert other_carrier.status_code == 201
    denied = _add_proof(client, shipment["shipment_id"], _headers(client, other_email))
    assert denied.status_code == 403
    hidden_view = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/proofs",
        headers=_headers(client, other_email),
    )
    assert hidden_view.status_code == 403
    tenant_email = f"freight.proof.tenant.{uuid4()[:6]}@amicor.local"
    with SessionLocal() as db:
        db.add(
            PlatformUser(
                id=uuid4(),
                email=tenant_email,
                hashed_password=hash_password(SEED_PASSWORD),
                role="driver",
                organization_id=f"org-proof-{uuid4()[:8]}",
                is_active=True,
                is_verified=True,
            )
        )
        db.commit()
    hidden = _add_proof(client, shipment["shipment_id"], _headers(client, tenant_email))
    assert hidden.status_code == 404
    hidden_get = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/proofs",
        headers=_headers(client, tenant_email),
    )
    assert hidden_get.status_code == 404


def test_dispatch_can_view_proof_and_unauth_cannot(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "view")
    driver = _headers(client, actors["driver"])
    _walk(client, shipment["shipment_id"], driver, ["en_route_to_pickup", "arrived_pickup"])
    added = _add_proof(client, shipment["shipment_id"], driver, notes="Visible to dispatch")
    assert added.status_code == 201
    seen = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/proofs",
        headers=_headers(client, actors["dispatcher"]),
    )
    assert seen.status_code == 200
    assert seen.json()[0]["notes"] == "Visible to dispatch"
    unauth = client.get(f"/api/nova/freight/shipments/{shipment['shipment_id']}/proofs")
    assert unauth.status_code == 401


def test_duplicate_retry_does_not_create_extra_records(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "dup")
    driver = _headers(client, actors["driver"])
    _walk(client, shipment["shipment_id"], driver, ["en_route_to_pickup", "arrived_pickup"])
    payload = {
        "proof_type": "pickup_document",
        "document_ref": "nfr-retry-same",
        "original_filename": "bol.pdf",
        "content_type": "application/pdf",
        "notes": "BOL",
    }
    first = _add_proof(client, shipment["shipment_id"], driver, **payload)
    second = _add_proof(client, shipment["shipment_id"], driver, **payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["proof_id"] == second.json()["proof_id"]
    listed = client.get(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/proofs",
        headers=driver,
    ).json()
    assert len(listed) == 1
    with SessionLocal() as db:
        count = (
            db.query(NovaFreightProof)
            .filter(NovaFreightProof.shipment_id == shipment["shipment_id"])
            .count()
        )
        events = (
            db.query(NovaFreightShipmentEvent)
            .filter(
                NovaFreightShipmentEvent.shipment_id == shipment["shipment_id"],
                NovaFreightShipmentEvent.event_type == "pickup_proof_added",
            )
            .count()
        )
    assert count == 1
    assert events == 1


def test_completed_shipment_proof_remains_readable(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "done")
    driver = _headers(client, actors["driver"])
    sid = shipment["shipment_id"]
    _walk(client, sid, driver, ["en_route_to_pickup", "arrived_pickup"])
    pickup = _add_proof(client, sid, driver, notes="POP")
    assert pickup.status_code == 201
    _walk(client, sid, driver, ["picked_up", "in_transit", "arrived_delivery"])
    delivery = _add_proof(
        client,
        sid,
        driver,
        proof_type="delivery_photo",
        notes="POD",
        signer_name="Receiver",
    )
    assert delivery.status_code == 201
    _walk(client, sid, driver, ["delivered", "completed"])
    listed = client.get(f"/api/nova/freight/shipments/{sid}/proofs", headers=driver)
    assert listed.status_code == 200
    assert {row["notes"] for row in listed.json()} == {"POP", "POD"}
    blocked = _add_proof(client, sid, driver, document_ref="nfr-after-complete")
    assert blocked.status_code == 409
    active = client.get("/api/nova/freight/carrier/shipments", headers=driver).json()
    assert sid not in [row["shipment_id"] for row in active]
    detail = client.get(f"/api/nova/freight/shipments/{sid}", headers=driver).json()
    assert detail["has_pickup_proof"] is True
    assert detail["has_delivery_proof"] is True
    assert detail["quoted_amount"] is None
    assert detail["carrier_payout_amount"] is None


def test_unsafe_file_type_rejected(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "exe")
    driver = _headers(client, actors["driver"])
    _walk(client, shipment["shipment_id"], driver, ["en_route_to_pickup", "arrived_pickup"])
    rejected = _add_proof(
        client,
        shipment["shipment_id"],
        driver,
        original_filename="payload.exe",
        content_type="application/x-msdownload",
    )
    assert rejected.status_code == 415
    upload = client.post(
        f"/api/nova/freight/shipments/{shipment['shipment_id']}/proofs/upload",
        headers=driver,
        data={"proof_type": "pickup_document", "document_ref": "nfr-exe"},
        files={"file": ("payload.exe", b"MZ-not-safe", "application/octet-stream")},
    )
    assert upload.status_code == 415


def test_phase4_local_e2e_and_pages(client: TestClient) -> None:
    shipment, _carrier, actors = _accept_ready(client, "e2e")
    driver = _headers(client, actors["driver"])
    dispatcher = _headers(client, actors["dispatcher"])
    sid = shipment["shipment_id"]
    _walk(client, sid, driver, ["en_route_to_pickup", "arrived_pickup"])
    pickup = _add_proof(client, sid, driver, notes="E2E pickup", signer_name="Shipper A")
    assert pickup.status_code == 201
    _walk(client, sid, driver, ["picked_up", "in_transit", "arrived_delivery"])
    delivery = _add_proof(
        client,
        sid,
        driver,
        proof_type="delivery_document",
        original_filename="pod.pdf",
        content_type="application/pdf",
        notes="E2E delivery",
        signer_name="Receiver B",
    )
    assert delivery.status_code == 201
    _walk(client, sid, driver, ["delivered", "completed"])
    proofs = client.get(f"/api/nova/freight/shipments/{sid}/proofs", headers=dispatcher).json()
    assert len(proofs) == 2
    events = client.get(f"/api/nova/freight/shipments/{sid}/events", headers=dispatcher).json()
    assert {row["event_type"] for row in events} >= {"status_transition", "pickup_proof_added", "delivery_proof_added"}
    page = client.get("/nova/freight/carrier/shipments")
    assert page.status_code == 200
    assert "Proof of Pickup" in EXECUTE_HTML
    assert "Proof of Delivery" in EXECUTE_HTML
    assert "Pickup proof:" in EXECUTE_JS
    assert "detail-proof-flags" in DISPATCH_HTML
    unauth = client.post(
        "/api/nova/freight/shipments/NF-NONE/proofs",
        json={"proof_type": "pickup_photo"},
    )
    assert unauth.status_code == 401
    nova = client.get("/openapi.json")
    assert "/api/nova/freight/shipments/{shipment_id}/proofs" in nova.json()["paths"]
    assert "AMICOR Delivery" in OPS_HTML
    live = client.get("/api/health/live")
    assert live.status_code == 200
    rides = client.get("/api/health-isf/rides", headers=dispatcher)
    assert rides.status_code == 200
    assert NovaFreightProof.__tablename__ == "nova_freight_proofs"
