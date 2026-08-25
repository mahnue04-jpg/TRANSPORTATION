"""Dispatch OFFERED assignment must appear on Maria's Driver Mobile after phone login."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    DriverStatus,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFProvider,
    HealthISFRide,
    RideStatus,
)
from tests.health_isf_driver_test_helpers import prepare_driver, reset_organization_driver_test_state

MARIA_PHONE = "917-555-1002"
MARIA_NAME = "Maria Garcia"


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None and user.organization_id is not None
        return str(user.organization_id)


def _ensure_provider(organization_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if provider:
            return str(provider.id)
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Maria Offer Provider {uuid4()[:6]}",
            address="500 Maria Offer Avenue",
            phone="212-555-0800",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _isolate_maria(organization_id: str, maria_id: str) -> None:
    with SessionLocal() as db:
        maria = db.query(HealthISFDriver).filter(HealthISFDriver.id == maria_id).first()
        assert maria is not None
        maria.rating = 5.0
        maria.total_trips = 100
        maria.status = DriverStatus.AVAILABLE
        maria.availability_state = "available"
        maria.is_online = True
        maria.auth_state = "active"
        maria.is_active = True
        maria.phone = MARIA_PHONE
        for row in db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.id != maria_id,
            HealthISFDriver.is_active == True,  # noqa: E712
        ):
            row.status = DriverStatus.OFFLINE
            row.availability_state = "offline"
            row.is_online = False
        db.commit()


def _maria_login(client: TestClient) -> tuple[str, dict[str, str], dict]:
    login = client.post("/api/health-isf/drivers/mobile-login", json={"phone": MARIA_PHONE})
    assert login.status_code == 200, login.text
    body = login.json()
    driver_id = str(body["driver_id"])
    headers = {"X-Driver-Session-Token": str(body["session_token"])}
    return driver_id, headers, body


def _request_ride_now_payload(suffix: str) -> dict:
    now = datetime.now(timezone.utc)
    pickup = now + timedelta(minutes=10)
    arrival = pickup + timedelta(minutes=15)
    return {
        "rider_name": f"Saye Rider {suffix}",
        "rider_phone": f"+1 646-555-{''.join(ch for ch in suffix if ch.isdigit()).ljust(4, '8')[:4]}",
        "pickup_address": f"100 Rider Pickup {suffix}, New York, NY 10001",
        "dropoff_address": f"200 Rider Dropoff {suffix}, New York, NY 10002",
        "ride_type": "healthcare",
        "notes": "Request Ride Now verification",
        "service_date": now.date().isoformat(),
        "pickup_time": pickup.isoformat(),
        "arrival_time": arrival.isoformat(),
        "trip_type": "one_way",
        "return_pickup_type": "scheduled_time",
        "return_pickup_time": (arrival + timedelta(hours=1)).isoformat(),
        "recurrence": "none",
        "recurrence_weekdays": [],
        "recurrence_start_date": now.date().isoformat(),
        "recurrence_end_date": None,
        "same_driver_preference": False,
        "client_timezone": "America/Chicago",
        "recurring": False,
        "scheduled_time": arrival.isoformat(),
    }


def _assignment_diag(ride_id: str) -> dict:
    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assignment = hs._latest_assignment_for_ride(db, ride_id) if ride else None
        marias = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.is_active.is_(True), HealthISFDriver.name.ilike(MARIA_NAME))
            .all()
        )
        phone_matches = [
            d
            for d in db.query(HealthISFDriver).filter(HealthISFDriver.is_active.is_(True)).all()
            if hs._phones_match_for_driver_login(d.phone, MARIA_PHONE)
        ]
        return {
            "ride_id": ride_id,
            "ride_org": str(getattr(ride, "organization_id", "") or ""),
            "ride_driver_id": str(getattr(ride, "driver_id", "") or ""),
            "ride_lifecycle": str(getattr(ride, "lifecycle_state", "") or getattr(ride, "status", "") or ""),
            "ride_status": str(getattr(ride, "status", "") or ""),
            "eligible": bool(ride and hs._ride_is_driver_mobile_eligible(ride)),
            "excluded": bool(ride and hs.is_operational_excluded_ride(ride)),
            "assignment_id": str(getattr(assignment, "id", "") or ""),
            "assignment_state": str(getattr(assignment, "assignment_state", "") or ""),
            "assignment_driver_id": str(getattr(assignment, "driver_id", "") or ""),
            "assignment_org": str(getattr(assignment, "organization_id", "") or ""),
            "offer_expires_at": str(getattr(assignment, "offer_expires_at", "") or ""),
            "maria_ids": [
                {"id": str(d.id), "org": str(d.organization_id), "phone": str(d.phone)} for d in marias
            ],
            "phone_match_ids": [
                {"id": str(d.id), "org": str(d.organization_id), "name": str(d.name), "phone": str(d.phone)}
                for d in phone_matches
            ],
        }


def test_maria_mobile_login_loads_dispatch_offered_ride(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEALTH_ISF_AUTO_DISPATCH_ENABLED", "1")
    org_id = _org_id_for("dispatcher@amicor.local")
    reset_organization_driver_test_state(
        org_id, driver_names=(MARIA_NAME, "James Smith", "David Chen", "Test Driver Four")
    )
    maria_id = prepare_driver(org_id, MARIA_NAME)
    _ensure_provider(org_id)
    _isolate_maria(org_id, maria_id)

    rider_auth = _login(client, "rider@amicor.local")
    rider_org = _org_id_for("rider@amicor.local")
    assert rider_org == org_id
    suffix = uuid4()[:8]
    create = client.post(
        f"/api/health-isf/customer-requests?organization_id={org_id}",
        headers={
            "Authorization": f"Bearer {rider_auth['access_token']}",
            "X-Idempotency-Key": f"maria-offer-{suffix}",
        },
        json=_request_ride_now_payload(suffix),
    )
    assert create.status_code == 201, create.text
    created = create.json()
    ride_id = created["ride_id"]
    request_status = str(created.get("dispatch_status") or "")

    dispatcher_headers = {"Authorization": f"Bearer {_login(client, 'dispatcher@amicor.local')['access_token']}"}
    assignments = client.get(
        "/api/health-isf/dispatch/active-assignments",
        headers=dispatcher_headers,
        params={"limit": 80},
    )
    assert assignments.status_code == 200, assignments.text
    offered = [
        row
        for row in assignments.json()
        if str(row.get("ride_id") or "") == ride_id
    ]
    diag = _assignment_diag(ride_id)
    assert offered, {
        "msg": "dispatch grid missing offered ride",
        "request_status": request_status,
        "diag": diag,
        "grid": assignments.json()[:8],
    }
    grid_driver_id = str(offered[0].get("driver_id") or "")
    grid_state = str(offered[0].get("assignment_state") or "").lower()
    assert grid_driver_id == maria_id, {"grid_driver_id": grid_driver_id, "maria_id": maria_id, "diag": diag}

    login_driver_id, driver_headers, login_body = _maria_login(client)
    assert login_driver_id == maria_id, {
        "login_driver_id": login_driver_id,
        "maria_id": maria_id,
        "login": {k: login_body.get(k) for k in ("driver_id", "organization_id")},
        "diag": diag,
    }
    assert str(login_body.get("organization_id") or "") == org_id

    offer = client.get(
        f"/api/health-isf/drivers/{login_driver_id}/active-offer",
        headers=driver_headers,
    )
    assert offer.status_code == 200, offer.text
    offer_body = offer.json()
    offer_row = offer_body.get("offer") or {}
    assert str(offer_body.get("driver_id") or "") == maria_id
    assert str(offer_row.get("ride_id") or "") == ride_id, {
        "msg": "Driver Mobile active-offer did not return the dispatch offered ride",
        "request_status": request_status,
        "grid_state": grid_state,
        "grid_driver_id": grid_driver_id,
        "login_driver_id": login_driver_id,
        "offer": offer_body,
        "diag": diag,
    }
    assert str(offer_row.get("driver_id") or "") == maria_id
    assert str(offer_row.get("assignment_state") or "").lower() == "offered"
    assert str(offer_row.get("organization_id") or "") == org_id
    assert str(offer_row.get("pickup_address") or "")
    assert str(offer_row.get("ride_id") or "") == ride_id

    assigned = client.get(
        f"/api/health-isf/drivers/{login_driver_id}/assigned-rides?limit=15",
        headers=driver_headers,
    )
    assert assigned.status_code == 200, assigned.text
    assigned_ids = {str(row.get("id") or "") for row in assigned.json()}
    assert ride_id in assigned_ids, {"assigned_ids": sorted(assigned_ids), "ride_id": ride_id, "offer": offer_body}

    active = client.get(
        f"/api/health-isf/drivers/{login_driver_id}/active-ride",
        headers=driver_headers,
    )
    assert active.status_code == 200, active.text
    active_body = active.json()
    assert str(active_body.get("driver_id") or "") == maria_id


def test_offered_assignment_not_crowded_out_by_older_driver_rows(client: TestClient) -> None:
    org_id = _org_id_for("dispatcher@amicor.local")
    maria_id = prepare_driver(org_id, MARIA_NAME)
    _ensure_provider(org_id)

    now_ts = hs.now()
    with SessionLocal() as db:
        for idx in range(40):
            ride = HealthISFRide(
                id=uuid4(),
                organization_id=org_id,
                passenger_name=f"Crowd Rider {idx}",
                passenger_phone="646-555-3000",
                pickup_address=f"{100 + idx} Crowd Ave, New York, NY",
                dropoff_address=f"{200 + idx} Crowd Rd, New York, NY",
                service_type="healthcare",
                status=RideStatus.PENDING.value,
                lifecycle_state="scheduled",
                driver_id=maria_id,
                requested_at=now_ts - timedelta(hours=2, minutes=idx),
                updated_at=now_ts + timedelta(seconds=idx),
            )
            db.add(ride)
            db.flush()
            db.add(
                HealthISFDispatchAssignment(
                    id=uuid4(),
                    organization_id=org_id,
                    ride_id=ride.id,
                    driver_id=maria_id,
                    assignment_state=DispatchAssignmentState.SCHEDULED_ACCEPTED.value,
                    attempt_index=1,
                    timeout_seconds=90,
                    queued_at=now_ts,
                    offered_at=now_ts,
                    accepted_at=now_ts,
                    created_at=now_ts - timedelta(hours=2, minutes=idx),
                    updated_at=now_ts + timedelta(seconds=idx),
                )
            )
        target_ride = HealthISFRide(
            id=uuid4(),
            organization_id=org_id,
            passenger_name="Offer Rider Visible",
            passenger_phone="646-555-3100",
            pickup_address="10 Offer Pickup Ave, New York, NY",
            dropoff_address="20 Offer Dropoff Rd, New York, NY",
            service_type="healthcare",
            status=RideStatus.PENDING.value,
            lifecycle_state=RideStatus.QUEUED.value,
            driver_id=maria_id,
            requested_at=now_ts,
            updated_at=now_ts,
        )
        db.add(target_ride)
        db.flush()
        db.add(
            HealthISFDispatchAssignment(
                id=uuid4(),
                organization_id=org_id,
                ride_id=target_ride.id,
                driver_id=maria_id,
                assignment_state=DispatchAssignmentState.OFFERED.value,
                attempt_index=1,
                timeout_seconds=90,
                queued_at=now_ts,
                offered_at=now_ts,
                offer_expires_at=now_ts + timedelta(minutes=15),
                created_at=now_ts,
                updated_at=now_ts,
            )
        )
        db.commit()
        target_ride_id = str(target_ride.id)

    login_driver_id, driver_headers, _ = _maria_login(client)
    assert login_driver_id == maria_id
    offer = client.get(
        f"/api/health-isf/drivers/{login_driver_id}/active-offer",
        headers=driver_headers,
    )
    assert offer.status_code == 200, offer.text
    offer_row = (offer.json().get("offer") or {})
    assert str(offer_row.get("ride_id") or "") == target_ride_id, {
        "msg": "newest offered ride was crowded out of Driver Mobile snapshot",
        "offer": offer.json(),
        "target_ride_id": target_ride_id,
        "login_driver_id": login_driver_id,
        "maria_id": maria_id,
    }
    assert str(offer_row.get("assignment_state") or "").lower() == "offered"
    assert str(offer_row.get("driver_id") or "") == maria_id
    assigned = client.get(
        f"/api/health-isf/drivers/{login_driver_id}/assigned-rides?limit=15",
        headers=driver_headers,
    )
    assert assigned.status_code == 200, assigned.text
    assert target_ride_id in {str(row.get("id") or "") for row in assigned.json()}
