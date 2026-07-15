"""Driver app authoritative assignment selection and offer coherence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    DriverStatus,
    HealthISFBillingHandoff,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFPaymentTransaction,
    HealthISFPayout,
    HealthISFRide,
    HealthISFTrip,
    HealthISFTripFinancialRecord,
    RideStatus,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None and user.organization_id is not None
        return str(user.organization_id)


def _drain_org_dispatch_queue(org_id: str) -> None:
    """Cancel unassigned queue rides so post-completion auto-assign does not pollute tests."""
    with SessionLocal() as db:
        queue = hs.get_dispatch_queue(db, organization_id=org_id, limit=200)
        now_ts = hs.now()
        for row in queue:
            ride_id = str(row.get("ride_id") or "")
            if not ride_id:
                continue
            ride = hs.get_ride_by_id(db, ride_id)
            if not ride or hs._ride_is_terminal(ride):
                continue
            if ride.driver_id:
                continue
            ride.status = RideStatus.CANCELLED.value
            ride.lifecycle_state = RideStatus.CANCELLED.value
            ride.updated_at = now_ts
            hs._close_active_assignments_for_ride(
                db,
                ride_id=ride_id,
                target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
                reason="test_queue_drain",
            )
        db.commit()


def _prepare_driver(org_id: str, name: str = "James Smith") -> str:
    _drain_org_dispatch_queue(org_id)
    with SessionLocal() as db:
        hs.ensure_sample_driver_credentials(db, organization_id=org_id)
        driver = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.name.ilike(name))
            .first()
        )
        assert driver is not None
        now_ts = hs.now()
        active_ride_ids: set[str] = set()
        for ride in db.query(HealthISFRide).filter(HealthISFRide.driver_id == driver.id).all():
            active_ride_ids.add(str(ride.id))
            if str(ride.status) not in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value}:
                ride.status = RideStatus.COMPLETED.value
                ride.lifecycle_state = RideStatus.COMPLETED.value
                ride.completed_at = now_ts
        for assignment in db.query(HealthISFDispatchAssignment).filter(
            HealthISFDispatchAssignment.driver_id == driver.id
        ).all():
            if assignment.ride_id:
                active_ride_ids.add(str(assignment.ride_id))
            assignment.assignment_state = DispatchAssignmentState.DROPOFF_COMPLETE.value
        for ride_id in active_ride_ids:
            ride = hs.get_ride_by_id(db, ride_id)
            if not ride or str(ride.status) in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value}:
                continue
            ride.status = RideStatus.COMPLETED.value
            ride.lifecycle_state = RideStatus.COMPLETED.value
            ride.completed_at = now_ts
            ride.driver_id = driver.id
            ride.updated_at = now_ts
        driver.status = DriverStatus.AVAILABLE
        driver.availability_state = "available"
        driver.is_online = True
        driver.auth_state = "active"
        driver.last_seen_at = now_ts
        db.commit()
        return str(driver.id)


def _create_and_assign(client: TestClient, dispatcher_headers: dict[str, str], rider_headers: dict[str, str], driver_id: str) -> str:
    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Driver App Test {suffix}",
            "rider_phone": f"646-555-{phone_digits}",
            "pickup_address": "10 Driver Ave, New York, NY 10001",
            "dropoff_address": "20 Driver Rd, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    assert create.status_code == 201, create.text
    request_id = create.json()["id"]
    ride_id = create.json()["ride_id"]
    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=dispatcher_headers,
    )
    assert approve.status_code == 200, approve.text
    ride_before = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    assert ride_before.status_code == 200, ride_before.text
    if str(ride_before.json().get("driver_id") or "") != driver_id:
        assign = client.post(
            f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            headers=dispatcher_headers,
            json={"driver_id": driver_id},
        )
        assert assign.status_code == 200, assign.text
    return ride_id


def test_offered_ride_visible_when_ride_driver_id_cleared(client: TestClient) -> None:
    org_id = _org_id_for("dispatcher@amicor.local")
    driver_id = _prepare_driver(org_id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])
    ride_id = _create_and_assign(client, dispatcher_headers, rider_headers, driver_id)

    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        ride.driver_id = None
        assignment = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride_id)
            .order_by(HealthISFDispatchAssignment.updated_at.desc())
            .first()
        )
        assert assignment is not None
        assignment.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
        db.commit()

    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        hs.reconcile_ride_assignment_coherence(db, ride)
        db.commit()
        assigned = hs.list_driver_assigned_rides(db, organization_id=org_id, driver_id=driver_id)
        assert any(str(row.id) == ride_id for row in assigned)

    active = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
    assert active.status_code == 200, active.text
    assert active.json()["has_active_ride"] is True
    assert (active.json().get("ride") or {}).get("id") == ride_id


def test_accepted_assignment_not_expired(client: TestClient) -> None:
    org_id = _org_id_for("dispatcher@amicor.local")
    driver_id = _prepare_driver(org_id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])
    ride_id = _create_and_assign(client, dispatcher_headers, rider_headers, driver_id)
    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dispatcher_headers,
        json={"ride_id": ride_id},
    )
    assert accept.status_code == 200, accept.text

    with SessionLocal() as db:
        assignment = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride_id)
            .order_by(HealthISFDispatchAssignment.updated_at.desc())
            .first()
        )
        assert assignment is not None
        assignment.offer_expires_at = hs.now() - timedelta(minutes=5)
        db.commit()
        expired = hs.expire_stale_dispatch_offers(db, organization_id=org_id, ride_id=ride_id)
        assert expired == []
        db.refresh(assignment)
        assert str(assignment.assignment_state) == DispatchAssignmentState.ACCEPTED.value


def test_terminal_ride_excluded_from_driver_assigned_list(client: TestClient) -> None:
    org_id = _org_id_for("dispatcher@amicor.local")
    driver_id = _prepare_driver(org_id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])
    ride_id = _create_and_assign(client, dispatcher_headers, rider_headers, driver_id)
    client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dispatcher_headers,
        json={"ride_id": ride_id},
    )
    for target_state in ("en_route_pickup", "arrived_pickup", "rider_loaded", "trip_in_progress", "arrived_destination"):
        step = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=dispatcher_headers,
            json={"ride_id": ride_id, "target_state": target_state},
        )
        assert step.status_code == 200, step.text
    complete = client.post(
        f"/api/health-isf/drivers/{driver_id}/route-progress",
        headers=dispatcher_headers,
        json={"ride_id": ride_id, "target_state": "completed"},
    )
    assert complete.status_code == 200, complete.text

    assigned = client.get(f"/api/health-isf/drivers/{driver_id}/assigned-rides", headers=dispatcher_headers)
    assert assigned.status_code == 200, assigned.text
    assert all(str(row.get("id")) != ride_id for row in assigned.json())

    active = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
    assert active.status_code == 200, active.text
    active_payload = active.json()
    if active_payload.get("has_active_ride"):
        assert (active_payload.get("ride") or {}).get("id") != ride_id
    else:
        assert active_payload.get("has_active_ride") is False


def test_controlled_two_ride_driver_workflow(client: TestClient) -> None:
    org_id = _org_id_for("dispatcher@amicor.local")
    driver_id = _prepare_driver(org_id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    admin_headers = _headers(_login(client, "admin@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])

    with SessionLocal() as db:
        before_handoffs = db.query(HealthISFBillingHandoff).count()
        before_payments = db.query(HealthISFPaymentTransaction).count()
        before_payouts = db.query(HealthISFPayout).count()
        before_earnings = client.get(
            f"/api/health-isf/drivers/{driver_id}/earnings",
            headers=dispatcher_headers,
        ).json().get("earnings_lifetime_usd", 0)

    ride_one = _create_and_assign(client, dispatcher_headers, rider_headers, driver_id)
    active_one = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
    assert active_one.json()["has_active_ride"] is True
    assert (active_one.json().get("ride") or {}).get("id") == ride_one

    client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dispatcher_headers,
        json={"ride_id": ride_one},
    )
    for target_state in ("en_route_pickup", "arrived_pickup", "rider_loaded", "trip_in_progress", "arrived_destination", "completed"):
        step = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=dispatcher_headers,
            json={"ride_id": ride_one, "target_state": target_state},
        )
        assert step.status_code == 200, step.text

    duplicate_complete = client.post(
        f"/api/health-isf/drivers/{driver_id}/route-progress",
        headers=dispatcher_headers,
        json={"ride_id": ride_one, "target_state": "completed"},
    )
    assert duplicate_complete.status_code in {200, 409}, duplicate_complete.text

    active_after = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
    active_after_payload = active_after.json()
    if active_after_payload.get("has_active_ride"):
        assert (active_after_payload.get("ride") or {}).get("id") != ride_one
    else:
        assert active_after_payload.get("has_active_ride") is False

    assigned_after = client.get(f"/api/health-isf/drivers/{driver_id}/assigned-rides", headers=dispatcher_headers)
    assert all(str(row.get("id")) != ride_one for row in assigned_after.json())

    with SessionLocal() as db:
        driver = hs.get_driver_by_id(db, driver_id)
        assert driver is not None
        assert str(driver.availability_state) == "available"
        after_handoffs = db.query(HealthISFBillingHandoff).count()
        after_payments = db.query(HealthISFPaymentTransaction).count()
        after_payouts = db.query(HealthISFPayout).count()
        assert after_handoffs == before_handoffs + 1
        assert after_payments == before_payments + 1
        assert after_payouts == before_payouts + 1
        assert db.query(HealthISFBillingHandoff).filter(HealthISFBillingHandoff.ride_id == ride_one).count() == 1
        assert db.query(HealthISFPaymentTransaction).filter(HealthISFPaymentTransaction.ride_id == ride_one).count() == 1
        assert db.query(HealthISFTripFinancialRecord).filter(HealthISFTripFinancialRecord.ride_id == ride_one).count() == 1
        trip = db.query(HealthISFTrip).filter(HealthISFTrip.ride_id == ride_one).order_by(HealthISFTrip.created_at.desc()).first()
        assert trip is not None
        assert db.query(HealthISFPayout).filter(HealthISFPayout.trip_id == trip.id).count() == 1

    earnings_after = client.get(f"/api/health-isf/drivers/{driver_id}/earnings", headers=dispatcher_headers)
    assert earnings_after.json()["earnings_lifetime_usd"] > before_earnings

    completed = client.get(
        f"/api/health-isf/drivers/{driver_id}/completed-rides",
        headers=dispatcher_headers,
        params={"limit": 20},
    )
    assert sum(1 for row in completed.json() if str(row.get("id")) == ride_one) == 1

    ride_two = _create_and_assign(client, dispatcher_headers, rider_headers, driver_id)
    active_two = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
    assert active_two.json()["has_active_ride"] is True
    assert (active_two.json().get("ride") or {}).get("id") == ride_two

    audit = client.get("/api/health-isf/operations/assignment-state-audit", headers=admin_headers)
    assert audit.status_code == 200, audit.text


def test_dispatch_queue_includes_real_passenger_names(client: TestClient) -> None:
    """Passenger names used in release validation must not be hidden from dispatch."""
    org_id = _org_id_for("dispatcher@amicor.local")
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])
    driver_id = _prepare_driver(org_id, name="Maria Garcia")
    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Release Gate Wonokay {suffix}",
            "rider_phone": f"646-555-{phone_digits}",
            "pickup_address": "10 Release Ave, New York, NY 10001",
            "dropoff_address": "20 Release Rd, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    assert create.status_code == 201, create.text
    request_id = create.json()["id"]
    ride_id = create.json()["ride_id"]
    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=dispatcher_headers,
    )
    assert approve.status_code == 200, approve.text
    ride_before = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    assert ride_before.status_code == 200, ride_before.text
    if str(ride_before.json().get("driver_id") or "") != driver_id:
        assign = client.post(
            f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            headers=dispatcher_headers,
            json={"driver_id": driver_id},
        )
        assert assign.status_code == 200, assign.text

    queue = client.get("/api/health-isf/dispatch/queue", headers=dispatcher_headers, params={"limit": 200})
    assert queue.status_code == 200, queue.text
    queue_ids = {str(row.get("ride_id")) for row in queue.json()}
    assert ride_id in queue_ids

    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        assert hs._is_test_ride_row(ride) is False


def test_other_driver_ride_excluded_from_active_ride(client: TestClient) -> None:
    org_id = _org_id_for("dispatcher@amicor.local")
    driver_a = _prepare_driver(org_id, name="James Smith")
    with SessionLocal() as db:
        driver_b = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.name.ilike("Maria Garcia"))
            .first()
        )
        assert driver_b is not None
        driver_b_id = str(driver_b.id)
        now_ts = hs.now()
        for ride in db.query(HealthISFRide).filter(HealthISFRide.driver_id == driver_b.id).all():
            if str(ride.status) not in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value}:
                ride.status = RideStatus.COMPLETED.value
                ride.lifecycle_state = RideStatus.COMPLETED.value
                ride.completed_at = now_ts
        for assignment in db.query(HealthISFDispatchAssignment).filter(
            HealthISFDispatchAssignment.driver_id == driver_b.id
        ).all():
            assignment.assignment_state = DispatchAssignmentState.DROPOFF_COMPLETE.value
        driver_b.status = DriverStatus.AVAILABLE
        driver_b.availability_state = "available"
        driver_b.is_online = True
        driver_b.auth_state = "active"
        driver_b.last_seen_at = now_ts
        db.commit()
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])
    ride_id = _create_and_assign(client, dispatcher_headers, rider_headers, driver_b_id)

    active_a = client.get(f"/api/health-isf/drivers/{driver_a}/active-ride", headers=dispatcher_headers)
    assert active_a.status_code == 200, active_a.text
    payload = active_a.json()
    if payload.get("has_active_ride"):
        assert (payload.get("ride") or {}).get("id") != ride_id

    active_b = client.get(f"/api/health-isf/drivers/{driver_b_id}/active-ride", headers=dispatcher_headers)
    assert active_b.json()["has_active_ride"] is True
    assert (active_b.json().get("ride") or {}).get("id") == ride_id
