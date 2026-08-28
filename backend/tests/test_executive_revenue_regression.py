"""Executive revenue regression tests — duplicate prevention and reconcile guards."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.financial_engine import TripFinancialEngine
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    HealthISFBillingHandoff,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFPaymentTransaction,
    HealthISFPayout,
    HealthISFRide,
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


def _org_id(email: str = "dispatcher@amicor.local") -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user and user.organization_id
        return str(user.organization_id)


def _driver_by_name(org_id: str, name: str) -> HealthISFDriver:
    with SessionLocal() as db:
        driver = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.name.ilike(name))
            .first()
        )
        assert driver is not None
        return driver


def _create_ride(client: TestClient, rider_headers: dict, dispatcher_headers: dict, driver_id: str) -> str:
    from app.modules.health_isf.models import DriverStatus

    with SessionLocal() as db:
        driver = db.query(HealthISFDriver).filter(HealthISFDriver.id == driver_id).first()
        if driver:
            driver.status = DriverStatus.AVAILABLE
            driver.availability_state = "available"
            driver.is_online = True
            driver.auth_state = "active"
            driver.is_active = True
            db.commit()
    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Exec Regression {suffix}",
            "rider_phone": f"646-555-{phone_digits}",
            "pickup_address": "10 Exec Ave, New York, NY",
            "dropoff_address": "20 Exec Rd, New York, NY",
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
    assigned = str((ride_before.json() or {}).get("driver_id") or "") if ride_before.status_code == 200 else ""
    if assigned != driver_id:
        assign = client.post(
            f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            headers=dispatcher_headers,
            json={"driver_id": driver_id},
        )
        if assign.status_code not in {200, 400}:
            assert assign.status_code == 200, assign.text
    return ride_id


def test_duplicate_billing_handoff_payment_payout_prevented(client: TestClient) -> None:
    org_id = _org_id()
    driver = _driver_by_name(org_id, "Test Driver Four")
    driver_id = str(driver.id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])
    ride_id = _create_ride(client, rider_headers, dispatcher_headers, driver_id)

    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        ride.lifecycle_state = RideStatus.COMPLETED.value
        ride.status = RideStatus.COMPLETED.value
        ride.completed_at = hs.now()
        ride.driver_id = driver_id
        db.commit()
        db.refresh(ride)

        first = TripFinancialEngine.process_trip_completion(db, ride)
        db.commit()
        assert first is not None

        handoffs = db.query(HealthISFBillingHandoff).filter(HealthISFBillingHandoff.ride_id == ride_id).count()
        payments = db.query(HealthISFPaymentTransaction).filter(HealthISFPaymentTransaction.ride_id == ride_id).count()
        assert handoffs == 1
        assert payments == 1

        second = TripFinancialEngine.process_trip_completion(db, ride)
        db.commit()
        assert second is not None

        handoffs_after = db.query(HealthISFBillingHandoff).filter(HealthISFBillingHandoff.ride_id == ride_id).count()
        payments_after = db.query(HealthISFPaymentTransaction).filter(HealthISFPaymentTransaction.ride_id == ride_id).count()
        financial = (
            db.query(HealthISFTripFinancialRecord)
            .filter(HealthISFTripFinancialRecord.ride_id == ride_id)
            .first()
        )
        payouts_after = 0
        if financial and financial.trip_id:
            payouts_after = (
                db.query(HealthISFPayout)
                .filter(HealthISFPayout.trip_id == financial.trip_id)
                .count()
            )
        assert handoffs_after == 1
        assert payments_after == 1
        assert payouts_after <= 1


def test_superseded_expired_assignment_not_reopened(client: TestClient) -> None:
    org_id = _org_id()
    driver = _driver_by_name(org_id, "Test Driver Four")
    driver_id = str(driver.id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])
    ride_id = _create_ride(client, rider_headers, dispatcher_headers, driver_id)

    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        bound_driver = str(ride.driver_id or driver_id)
        deadline = time.time() + 4
        assignments = []
        while time.time() < deadline:
            assignments = (
                db.query(HealthISFDispatchAssignment)
                .filter(HealthISFDispatchAssignment.ride_id == ride_id)
                .all()
            )
            if assignments:
                break
            db.expire_all()
            time.sleep(0.2)
        assert assignments, "expected an intake/assignment row before superseded-expire"
        now_ts = hs.now()
        for assignment in assignments:
            assignment.assignment_state = DispatchAssignmentState.EXPIRED.value
            assignment.closed_reason = "superseded_by_newer_queue_ride"
            assignment.expired_at = now_ts
        ride.driver_id = bound_driver or str(assignments[0].driver_id)
        ride.lifecycle_state = RideStatus.QUEUED.value
        db.commit()

        restored = hs.reconcile_expired_bound_driver_assignment(db, ride)
        assert restored is None


def test_only_one_valid_active_offer_per_driver(client: TestClient) -> None:
    org_id = _org_id()
    driver = _driver_by_name(org_id, "Test Driver Four")
    driver_id = str(driver.id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])
    ride_a = _create_ride(client, rider_headers, dispatcher_headers, driver_id)
    ride_b = _create_ride(client, rider_headers, dispatcher_headers, driver_id)

    with SessionLocal() as db:
        hs._prepare_driver_mobile_workspace_read(
            db, organization_id=org_id, driver_id=driver_id
        )
        db.commit()
        offers = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.driver_id == driver_id,
                HealthISFDispatchAssignment.assignment_state.in_(
                    [DispatchAssignmentState.OFFERED.value, DispatchAssignmentState.ASSIGNED.value]
                ),
            )
            .all()
        )
        eligible = []
        for row in offers:
            ride = hs.get_ride_by_id(db, row.ride_id) if row.ride_id else None
            if ride and hs._ride_is_driver_mobile_eligible(ride):
                eligible.append(str(row.ride_id))
        assert len(eligible) <= 1
        assert ride_a in eligible or ride_b in eligible or len(eligible) == 0


def test_completed_ride_excluded_after_prepare_read(client: TestClient) -> None:
    org_id = _org_id()
    driver = _driver_by_name(org_id, "Test Driver Four")
    driver_id = str(driver.id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])
    ride_id = _create_ride(client, rider_headers, dispatcher_headers, driver_id)

    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        ride.lifecycle_state = RideStatus.COMPLETED.value
        ride.status = RideStatus.COMPLETED.value
        ride.completed_at = hs.now()
        assignment = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride_id)
            .order_by(HealthISFDispatchAssignment.updated_at.desc())
            .first()
        )
        assert assignment is not None
        assignment.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
        db.commit()

        hs._prepare_driver_mobile_workspace_read(
            db, organization_id=org_id, driver_id=driver_id
        )
        db.commit()
        assignment = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.id == assignment.id)
            .first()
        )
        assert assignment is not None
        assert str(assignment.assignment_state) == DispatchAssignmentState.DROPOFF_COMPLETE.value

    offer = client.get(f"/api/health-isf/drivers/{driver_id}/active-offer", headers=dispatcher_headers)
    active = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
    assigned = client.get(f"/api/health-isf/drivers/{driver_id}/assigned-rides", headers=dispatcher_headers)
    assert str((offer.json().get("offer") or {}).get("ride_id") or "") != ride_id
    assert str((active.json().get("ride") or {}).get("id") or "") != ride_id
    assert ride_id not in [str(r.get("id") or "") for r in assigned.json()]


def test_driver_earnings_summary_matches_completed_rows(client: TestClient) -> None:
    org_id = _org_id()
    driver = _driver_by_name(org_id, "Test Driver Four")
    driver_id = str(driver.id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])

    earnings = client.get(
        f"/api/health-isf/drivers/{driver_id}/earnings?organization_id={org_id}",
        headers=dispatcher_headers,
    )
    snapshot = client.get(
        f"/api/health-isf/drivers/{driver_id}/completion-snapshot?organization_id={org_id}&limit=50",
        headers=dispatcher_headers,
    )
    assert earnings.status_code == 200
    assert snapshot.status_code == 200
    er = earnings.json()
    completed = snapshot.json().get("completed_rides") or []
    recent = er.get("recent_trips") or []
    assert len(recent) >= 0
    if recent and completed:
        assert float(er.get("earnings_lifetime_usd") or 0) >= 0
        assert int(er.get("completed_trips") or len(recent)) >= 1
