"""Driver mobile assignment sync: session-first reads, org scope, and full lifecycle."""
from __future__ import annotations

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


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None and user.organization_id is not None
        return str(user.organization_id)


def _drain_org_dispatch_queue(org_id: str) -> None:
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
                reason="assignment_sync_test_drain",
            )
        db.commit()


def _prepare_driver(org_id: str, phone: str = "917-555-1004") -> str:
    _drain_org_dispatch_queue(org_id)
    with SessionLocal() as db:
        hs.ensure_sample_driver_credentials(db, organization_id=org_id)
        driver = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.phone == phone)
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
            assignment.closed_reason = "assignment_sync_test_cleanup"
        for ride_id in active_ride_ids:
            ride = hs.get_ride_by_id(db, ride_id)
            if not ride or str(ride.status) in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value}:
                continue
            ride.status = RideStatus.COMPLETED.value
            ride.lifecycle_state = RideStatus.COMPLETED.value
            ride.completed_at = now_ts
            ride.updated_at = now_ts
        driver.status = DriverStatus.AVAILABLE
        driver.availability_state = "available"
        driver.is_online = True
        driver.auth_state = "active"
        driver.last_seen_at = now_ts
        db.commit()
        return str(driver.id)


def _driver_mobile_headers(client: TestClient, phone: str = "917-555-1004") -> tuple[str, dict[str, str]]:
    login = client.post("/api/health-isf/drivers/mobile-login", json={"phone": phone})
    assert login.status_code == 200, login.text
    body = login.json()
    driver_id = str(body["driver_id"])
    headers = {"X-Driver-Session-Token": str(body["session_token"])}
    return driver_id, headers


def _assert_driver_mobile_sync_surfaces(
    client: TestClient,
    *,
    driver_id: str,
    ride_id: str,
    driver_headers: dict[str, str],
    stale_org: str,
) -> None:
    assigned = client.get(
        f"/api/health-isf/drivers/{driver_id}/assigned-rides?organization_id={stale_org}",
        headers=driver_headers,
    )
    assert assigned.status_code == 200, assigned.text
    assigned_ids = {str(row.get("id")) for row in assigned.json()}

    workspace = client.get(
        f"/api/health-isf/drivers/{driver_id}/live-workspace?organization_id={stale_org}",
        headers=driver_headers,
    )
    assert workspace.status_code == 200, workspace.text
    workspace_body = workspace.json()
    workspace_ride = workspace_body.get("active_ride") or workspace_body.get("ride") or {}
    workspace_ride_id = str(workspace_ride.get("id") or "")

    active = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-ride?organization_id={stale_org}",
        headers=driver_headers,
    )
    assert active.status_code == 200, active.text
    active_body = active.json()
    assert active_body.get("has_active_ride") is True, active_body
    assert (active_body.get("ride") or {}).get("id") == ride_id
    assert str(active_body.get("assignment_state") or "").lower() in {
        "offered",
        "assigned",
        "accepted",
        "en_route_pickup",
    }

    assert ride_id in assigned_ids, {
        "assigned_ids": sorted(assigned_ids),
        "active": active_body,
        "workspace": workspace_body,
    }
    assert workspace_ride_id == ride_id, workspace_body


def test_driver_mobile_assignment_sync_endpoints(client: TestClient):
    driver_id, headers = _driver_mobile_headers(client)
    org_id = _org_id_for("dispatcher@amicor.local")

    active = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-ride?organization_id={org_id}",
        headers=headers,
    )
    assert active.status_code == 200, active.text

    assigned = client.get(
        f"/api/health-isf/drivers/{driver_id}/assigned-rides?organization_id={org_id}",
        headers=headers,
    )
    assert assigned.status_code == 200, assigned.text
    assert isinstance(assigned.json(), list)

    workspace = client.get(
        f"/api/health-isf/drivers/{driver_id}/live-workspace?organization_id={org_id}",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text

    stale_platform_org = "00000000-0000-0000-0000-000000000099"
    cross_org_active = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-ride?organization_id={stale_platform_org}",
        headers=headers,
    )
    assert cross_org_active.status_code == 200, cross_org_active.text


def test_assigned_ride_visible_on_driver_mobile_after_dispatcher_assign(client: TestClient) -> None:
    """Rider request -> dispatcher assign -> driver mobile sync -> rider tracking -> full trip -> billing."""
    org_id = _org_id_for("dispatcher@amicor.local")
    driver_id = _prepare_driver(org_id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])

    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    rider_phone = f"646-555-{phone_digits}"

    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Driver App Sync {suffix}",
            "rider_phone": rider_phone,
            "pickup_address": "100 Sync Ave, New York, NY 10001",
            "dropoff_address": "200 Sync Rd, New York, NY 10002",
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

    assert approve.status_code == 200, approve.text

    from tests.health_isf_driver_test_helpers import ensure_ride_assigned_to_driver

    admin_headers = _headers(_login(client, "admin@amicor.local")["access_token"])
    ensure_ride_assigned_to_driver(
        client,
        dispatcher_headers=dispatcher_headers,
        admin_headers=admin_headers,
        request_id=request_id,
        ride_id=ride_id,
        driver_id=driver_id,
    )

    _, driver_headers = _driver_mobile_headers(client)
    stale_org = "00000000-0000-0000-0000-000000000099"
    _assert_driver_mobile_sync_surfaces(
        client,
        driver_id=driver_id,
        ride_id=ride_id,
        driver_headers=driver_headers,
        stale_org=stale_org,
    )

    rider_active = client.get(
        "/api/health-isf/customers/workspace/active",
        headers=rider_headers,
        params={"rider_phone": rider_phone},
    )
    assert rider_active.status_code == 200, rider_active.text
    active_ride = (rider_active.json().get("active_ride") or {})
    assert str(active_ride.get("id") or "") == ride_id
    assert str(active_ride.get("driver_id") or "") == driver_id

    rider_tracking = client.get(
        "/api/health-isf/customers/workspace/live-tracking",
        headers=rider_headers,
        params={"rider_phone": rider_phone, "limit": 40},
    )
    assert rider_tracking.status_code == 200, rider_tracking.text
    tracking_body = rider_tracking.json()
    tracking_ride = tracking_body.get("active_ride") or {}
    assert str(tracking_ride.get("id") or "") == ride_id
    assert str(tracking_ride.get("status") or tracking_ride.get("lifecycle_state") or "").lower() in {
        "assigned",
        "accepted",
        "offered",
        "pending",
        "in_progress",
        "driver_en_route",
    }

    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=driver_headers,
        json={"ride_id": ride_id},
    )
    assert accept.status_code == 200, accept.text

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
            headers=driver_headers,
            json={"ride_id": ride_id, "target_state": target_state},
        )
        assert step.status_code == 200, f"{target_state}: {step.text}"

    completed_ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    assert completed_ride.status_code == 200, completed_ride.text
    assert str(completed_ride.json().get("lifecycle_state") or completed_ride.json().get("status")).lower() == "completed"

    rider_history = client.get(
        "/api/health-isf/customers/workspace/history",
        headers=rider_headers,
        params={"rider_phone": rider_phone, "limit": 20},
    )
    assert rider_history.status_code == 200, rider_history.text
    history_row = next(row for row in rider_history.json().get("history", []) if row.get("ride_id") == ride_id)
    assert str(history_row.get("dispatch_status") or "").lower() == "completed"

    post_complete_active = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-ride?organization_id={stale_org}",
        headers=driver_headers,
    )
    assert post_complete_active.status_code == 200, post_complete_active.text
    assert post_complete_active.json().get("has_active_ride") is False

    financial = client.get(
        f"/api/health-isf/rides/{ride_id}/financial-summary",
        headers=dispatcher_headers,
    )
    assert financial.status_code == 200, financial.text
    financial_body = financial.json()
    assert financial_body["driver_pay_usd"] > 0
    assert financial_body["billing_handoff_id"]
    assert financial_body["billing_handoff_status"] == "ready"

    earnings = client.get(
        f"/api/health-isf/drivers/{driver_id}/earnings",
        headers=dispatcher_headers,
    )
    assert earnings.status_code == 200, earnings.text
    assert earnings.json()["earnings_lifetime_usd"] >= financial_body["driver_pay_usd"]
    assert earnings.json()["trip_count"] >= 1

    billing_queue = client.get(
        "/api/health-isf/operations/billing-handoffs",
        headers=dispatcher_headers,
        params={"limit": 20},
    )
    assert billing_queue.status_code == 200, billing_queue.text
    assert any(row["ride_id"] == ride_id for row in billing_queue.json())

    with SessionLocal() as db:
        assert db.query(HealthISFTripFinancialRecord).filter(HealthISFTripFinancialRecord.ride_id == ride_id).count() == 1
        assert db.query(HealthISFBillingHandoff).filter(HealthISFBillingHandoff.ride_id == ride_id).count() == 1
        driver_row = hs.get_driver_by_id(db, driver_id)
        assert driver_row is not None
        assert int(driver_row.total_trips or 0) >= 1


def test_active_ride_uses_session_driver_when_path_driver_id_mismatches(client: TestClient) -> None:
    org_id = _org_id_for("dispatcher@amicor.local")
    driver_id = _prepare_driver(org_id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])

    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    rider_phone = f"646-555-{phone_digits}"

    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Path Mismatch Sync {suffix}",
            "rider_phone": rider_phone,
            "pickup_address": "101 Sync Ave, New York, NY 10001",
            "dropoff_address": "201 Sync Rd, New York, NY 10002",
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

    assert approve.status_code == 200, approve.text

    from tests.health_isf_driver_test_helpers import ensure_ride_assigned_to_driver

    admin_headers = _headers(_login(client, "admin@amicor.local")["access_token"])
    ensure_ride_assigned_to_driver(
        client,
        dispatcher_headers=dispatcher_headers,
        admin_headers=admin_headers,
        request_id=request_id,
        ride_id=ride_id,
        driver_id=driver_id,
    )

    _, driver_headers = _driver_mobile_headers(client)
    wrong_path_driver_id = "00000000-0000-0000-0000-000000000099"
    active = client.get(
        f"/api/health-isf/drivers/{wrong_path_driver_id}/active-ride?organization_id={org_id}",
        headers=driver_headers,
    )
    assert active.status_code == 200, active.text
    body = active.json()
    assert body["driver_id"] == driver_id
    assert body["has_active_ride"] is True, body
    assert (body.get("ride") or {}).get("id") == ride_id
