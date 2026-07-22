"""Assignment invariant audit/repair and second-ride dispatch after completion."""
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
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFRide,
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
        assert user is not None
        assert user.organization_id is not None
        return str(user.organization_id)


def _prepare_james(organization_id: str) -> str:
    with SessionLocal() as db:
        hs.ensure_sample_driver_credentials(db, organization_id=organization_id)
        james = (
            db.query(HealthISFDriver)
            .filter(
                HealthISFDriver.organization_id == organization_id,
                HealthISFDriver.name.ilike("James Smith"),
            )
            .order_by(HealthISFDriver.updated_at.desc())
            .first()
        )
        assert james is not None
        now_ts = hs.now()
        for ride in db.query(HealthISFRide).filter(HealthISFRide.driver_id == james.id).all():
            ride.status = RideStatus.COMPLETED
            ride.lifecycle_state = RideStatus.COMPLETED.value
            ride.completed_at = now_ts
            ride.updated_at = now_ts
        for assignment in db.query(HealthISFDispatchAssignment).filter(
            HealthISFDispatchAssignment.driver_id == james.id
        ).all():
            assignment.assignment_state = DispatchAssignmentState.DROPOFF_COMPLETE.value
            assignment.updated_at = now_ts
        james.status = DriverStatus.AVAILABLE
        james.availability_state = "available"
        james.is_online = True
        james.auth_state = "active"
        james.updated_at = now_ts
        db.commit()
        return str(james.id)


def _create_and_assign(client: TestClient, dispatcher_headers: dict[str, str], rider_headers: dict[str, str], driver_id: str) -> tuple[str, str]:
    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Clean State Rider {suffix}",
            "rider_phone": f"646-555-{phone_digits}",
            "pickup_address": f"100 Clean Ave {suffix}, New York, NY 10001",
            "dropoff_address": f"200 Clinic Rd {suffix}, New York, NY 10002",
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
    if str(ride_before.json().get("driver_id") or "") != driver_id:
        assign = client.post(
            f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            headers=dispatcher_headers,
            json={"driver_id": driver_id},
        )
        if assign.status_code == 400 and "already has an assigned driver" in assign.text:
            reassign = client.patch(
                f"/api/health-isf/dispatcher/rides/{ride_id}/reassign-driver",
                headers=dispatcher_headers,
                json={"driver_id": driver_id},
            )
            assert reassign.status_code == 200, reassign.text
        else:
            assert assign.status_code == 200, assign.text
    return request_id, ride_id


def test_assignment_reconcile_closes_stale_terminal_assignment(client: TestClient) -> None:
    org_id = _org_id_for("admin@amicor.local")
    driver_id = _prepare_james(org_id)
    admin_auth = _login(client, "admin@amicor.local")
    admin_headers = _headers(admin_auth["access_token"])
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])

    _, stale_ride_id = _create_and_assign(client, dispatcher_headers, rider_headers, driver_id)
    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dispatcher_headers,
        json={"ride_id": stale_ride_id},
    )
    assert accept.status_code == 200, accept.text
    for target_state in ("en_route_pickup", "arrived_pickup", "rider_loaded", "trip_in_progress", "arrived_destination"):
        step = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=dispatcher_headers,
            json={"ride_id": stale_ride_id, "target_state": target_state},
        )
        assert step.status_code == 200, step.text
    complete = client.post(
        f"/api/health-isf/drivers/{driver_id}/route-progress",
        headers=dispatcher_headers,
        json={"ride_id": stale_ride_id, "target_state": "completed"},
    )
    assert complete.status_code == 200, complete.text

    with SessionLocal() as db:
        assignment = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == stale_ride_id)
            .order_by(HealthISFDispatchAssignment.updated_at.desc())
            .first()
        )
        assert assignment is not None
        assignment.assignment_state = DispatchAssignmentState.ACCEPTED.value
        assignment.closed_reason = None
        assignment.updated_at = hs.now()
        db.commit()

    audit = client.get("/api/health-isf/operations/assignment-state-audit", headers=admin_headers)
    assert audit.status_code == 200, audit.text
    assert audit.json()["stale_ride_count"] >= 1

    repair = client.post(
        "/api/health-isf/operations/assignment-state-reconcile",
        headers=admin_headers,
        params={"dry_run": "false", "ride_id": stale_ride_id},
    )
    assert repair.status_code == 200, repair.text
    assert repair.json()["repairs_applied"] >= 1

    with SessionLocal() as db:
        row = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == stale_ride_id)
            .order_by(HealthISFDispatchAssignment.updated_at.desc())
            .first()
        )
        assert row is not None
        assert str(row.assignment_state) == DispatchAssignmentState.DROPOFF_COMPLETE.value


def test_clean_state_complete_then_assign_next_ride(client: TestClient) -> None:
    org_id = _org_id_for("dispatcher@amicor.local")
    _ = org_id
    driver_id = _prepare_james(_org_id_for("dispatcher@amicor.local"))
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    admin_headers = _headers(_login(client, "admin@amicor.local")["access_token"])

    _, ride_one = _create_and_assign(client, dispatcher_headers, rider_headers, driver_id)
    queue_one = client.get("/api/health-isf/dispatch/queue", headers=dispatcher_headers, params={"limit": 200})
    assert queue_one.status_code == 200, queue_one.text
    assert sum(1 for row in queue_one.json() if row.get("ride_id") == ride_one) == 1

    active_one = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
    assert active_one.status_code == 200, active_one.text
    assert active_one.json().get("has_active_ride") is True
    assert (active_one.json().get("ride") or {}).get("id") == ride_one

    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dispatcher_headers,
        json={"ride_id": ride_one},
    )
    assert accept.status_code == 200, accept.text
    duplicate = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dispatcher_headers,
        json={"ride_id": ride_one},
    )
    assert duplicate.status_code == 200, duplicate.text

    for target_state in (
        "en_route_pickup",
        "arrived_pickup",
        "rider_loaded",
        "trip_in_progress",
        "arrived_destination",
        "completed",
    ):
        step = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=dispatcher_headers,
            json={"ride_id": ride_one, "target_state": target_state},
        )
        assert step.status_code == 200, f"{target_state}: {step.text}"

    active_after = client.get(
        "/api/health-isf/dispatch/active-assignments",
        headers=dispatcher_headers,
        params={"limit": 200},
    )
    assert active_after.status_code == 200, active_after.text
    assert not any(row.get("ride_id") == ride_one for row in active_after.json())

    live_ops = client.get("/api/health-isf/admin/live-operations", headers=admin_headers)
    assert live_ops.status_code == 200, live_ops.text
    live_payload = live_ops.json()
    active_ride_ids = {str(row.get("ride_id")) for row in live_payload.get("active_rides") or []}
    assert ride_one not in active_ride_ids

    with SessionLocal() as db:
        driver = hs.get_driver_by_id(db, driver_id)
        assert driver is not None
        assert hs._coerce_driver_status(driver.status) == DriverStatus.AVAILABLE

    _, ride_two = _create_and_assign(client, dispatcher_headers, rider_headers, driver_id)
    active_two = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
    assert active_two.status_code == 200, active_two.text
    assert active_two.json().get("has_active_ride") is True
    assert (active_two.json().get("ride") or {}).get("id") == ride_two
    assert (active_two.json().get("ride") or {}).get("id") != ride_one


def test_driver_app_prefers_newest_in_trip_ride(client: TestClient) -> None:
    org_id = _org_id_for("dispatcher@amicor.local")
    driver_id = _prepare_james(org_id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])

    _, old_ride_id = _create_and_assign(client, dispatcher_headers, rider_headers, driver_id)
    accept_old = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dispatcher_headers,
        json={"ride_id": old_ride_id},
    )
    assert accept_old.status_code == 200, accept_old.text
    for target_state in ("en_route_pickup", "arrived_pickup", "rider_loaded", "trip_in_progress"):
        step = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=dispatcher_headers,
            json={"ride_id": old_ride_id, "target_state": target_state},
        )
        assert step.status_code == 200, step.text

    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    create_new = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Queued While In Trip {suffix}",
            "rider_phone": f"646-555-{phone_digits}",
            "pickup_address": "30 New Ave, New York, NY 10001",
            "dropoff_address": "40 New Rd, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    assert create_new.status_code == 201, create_new.text
    new_ride_id = create_new.json()["ride_id"]
    approve_new = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{create_new.json()['id']}/approve",
        headers=dispatcher_headers,
    )
    assert approve_new.status_code == 200, approve_new.text

    active = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
    assert active.status_code == 200, active.text
    assert (active.json().get("ride") or {}).get("id") == old_ride_id
    assert (active.json().get("ride") or {}).get("id") != new_ride_id


def test_stale_prod_verify_offer_does_not_block_new_queue_offer(client: TestClient) -> None:
    org_id = _org_id_for("dispatcher@amicor.local")
    driver_id = _prepare_james(org_id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])

    _, stale_ride_id = _create_and_assign(client, dispatcher_headers, rider_headers, driver_id)
    with SessionLocal() as db:
        stale = db.query(HealthISFRide).filter(HealthISFRide.id == stale_ride_id).first()
        assert stale is not None
        stale.passenger_name = "Prod Verify API"
        stale.pickup_address = "100 Verify Ave"
        stale.dropoff_address = "200 Clinic Rd"
        stale.accepted_at = hs.now() - timedelta(days=3)
        stale.updated_at = hs.now()
        assignment = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.ride_id == stale_ride_id,
                HealthISFDispatchAssignment.driver_id == driver_id,
            )
            .order_by(HealthISFDispatchAssignment.updated_at.desc())
            .first()
        )
        assert assignment is not None
        assignment.assignment_state = DispatchAssignmentState.OFFERED.value
        assignment.accepted_at = None
        assignment.offer_expires_at = None
        assignment.queued_at = hs.now() - timedelta(days=3)
        assignment.updated_at = hs.now()
        db.commit()

    mobile_login = client.post(
        "/api/health-isf/drivers/mobile-login",
        json={"phone": "917-555-1001", "driver_id": driver_id},
    )
    assert mobile_login.status_code == 200, mobile_login.text
    mobile_headers = {"X-Driver-Session-Token": mobile_login.json()["session_token"]}
    warmup = client.get(
        f"/api/health-isf/drivers/{driver_id}/assigned-rides",
        headers=mobile_headers,
        params={"organization_id": org_id},
    )
    assert warmup.status_code == 200, warmup.text
    assert stale_ride_id not in {str(row.get("id") or "") for row in warmup.json()}

    _, fresh_ride_id = _create_and_assign(client, dispatcher_headers, rider_headers, driver_id)

    assigned = client.get(
        f"/api/health-isf/drivers/{driver_id}/assigned-rides",
        headers=mobile_headers,
        params={"organization_id": org_id},
    )
    assert assigned.status_code == 200, assigned.text
    assigned_ids = {str(row.get("id") or "") for row in assigned.json()}
    assert stale_ride_id not in assigned_ids
    assert fresh_ride_id in assigned_ids

    with SessionLocal() as db:
        stale = db.query(HealthISFRide).filter(HealthISFRide.id == stale_ride_id).first()
        assert stale is not None
        assert hs.RideLifecycleManager.normalize_state(stale.lifecycle_state or stale.status) == RideStatus.CANCELLED.value
        assert stale.driver_id is None
