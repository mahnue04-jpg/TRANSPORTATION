"""Driver + dispatch production lifecycle: every driver action through completion."""
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
    HealthISFDriverSession,
    HealthISFRide,
    HealthISFProvider,
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
        assert user is not None
        assert user.organization_id is not None
        return str(user.organization_id)


def _reseed_james(organization_id: str) -> str:
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
        james_rides = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.driver_id == james.id)
            .all()
        )
        for ride in james_rides:
            if str(ride.status) not in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value}:
                ride.status = RideStatus.COMPLETED
                ride.lifecycle_state = RideStatus.COMPLETED.value
                ride.completed_at = now_ts
                ride.updated_at = now_ts
        assignment_ride_ids = {
            str(row.ride_id)
            for row in db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.driver_id == james.id)
            .all()
            if row.ride_id
        }
        for ride_id in assignment_ride_ids:
            ride = hs.get_ride_by_id(db, ride_id)
            if ride and str(ride.status) not in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value}:
                ride.status = RideStatus.COMPLETED
                ride.lifecycle_state = RideStatus.COMPLETED.value
                ride.completed_at = now_ts
                ride.updated_at = now_ts
        for assignment in db.query(HealthISFDispatchAssignment).filter(
            HealthISFDispatchAssignment.driver_id == james.id
        ).all():
            assignment.assignment_state = DispatchAssignmentState.DROPOFF_COMPLETE.value
            assignment.closed_reason = "test_reseed_cleanup"
            assignment.updated_at = now_ts
        james.status = DriverStatus.AVAILABLE
        james.availability_state = "available"
        james.is_active = True
        james.is_online = True
        james.auth_state = "active"
        james.last_seen_at = now_ts
        james.updated_at = now_ts
        db.commit()
        db.refresh(james)
        return str(james.id)


def _ensure_provider(organization_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if provider:
            if not provider.is_active:
                provider.is_active = True
                db.commit()
            return str(provider.id)
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Driver Lifecycle Provider {uuid4()[:6]}",
            address="500 Driver Lifecycle Avenue",
            phone="212-555-0700",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def test_full_driver_dispatch_lifecycle_all_actions(client: TestClient) -> None:
    org_id = _org_id_for("dispatcher@amicor.local")
    _ensure_provider(org_id)
    driver_id = _reseed_james(org_id)

    rider_auth = _login(client, "rider@amicor.local")
    rider_headers = _headers(rider_auth["access_token"])
    dispatcher_auth = _login(client, "dispatcher@amicor.local")
    dispatcher_headers = _headers(dispatcher_auth["access_token"])
    admin_auth = _login(client, "admin@amicor.local")
    admin_headers = _headers(admin_auth["access_token"])

    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    rider_phone = f"646-555-{phone_digits}"

    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Alex Rivera {suffix}",
            "rider_phone": rider_phone,
            "pickup_address": f"100 Clinic Ave {suffix}, New York, NY 10001",
            "dropoff_address": f"200 Hospital Rd {suffix}, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": "dialysis appointment transport",
        },
    )
    assert create.status_code == 201, create.text
    request_row = create.json()
    request_id = request_row["id"]
    ride_id = request_row["ride_id"]

    queue = client.get("/api/health-isf/dispatch/queue", headers=dispatcher_headers, params={"limit": 200})
    assert queue.status_code == 200
    assert any(row.get("ride_id") == ride_id for row in queue.json())

    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=dispatcher_headers,
    )
    assert approve.status_code == 200, approve.text

    ride_before_assign = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    assert ride_before_assign.status_code == 200, ride_before_assign.text
    if str(ride_before_assign.json().get("driver_id") or "") != driver_id:
        assign = client.post(
            f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            headers=dispatcher_headers,
            json={"driver_id": driver_id},
        )
        assert assign.status_code == 200, assign.text

    offer = client.get(f"/api/health-isf/drivers/{driver_id}/active-offer", headers=dispatcher_headers)
    assert offer.status_code == 200, offer.text
    offer_ride_id = (offer.json().get("offer") or {}).get("ride_id")
    if not offer_ride_id:
        # active-offer is optional when active-ride already surfaces the assignment
        pass
    else:
        assert offer_ride_id == ride_id

    active_ride = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
    assert active_ride.status_code == 200, active_ride.text
    active_payload = active_ride.json()
    assert active_payload.get("has_active_ride") is True
    assert (active_payload.get("ride") or {}).get("id") == ride_id

    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dispatcher_headers,
        json={"ride_id": ride_id},
    )
    assert accept.status_code == 200, accept.text

    duplicate_accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dispatcher_headers,
        json={"ride_id": ride_id},
    )
    assert duplicate_accept.status_code == 409, duplicate_accept.text

    contact = client.post(
        f"/api/health-isf/drivers/{driver_id}/contact-rider",
        headers=dispatcher_headers,
        json={"ride_id": ride_id, "channel": "sms"},
    )
    # SMS provider may be unavailable in local/test environments.
    assert contact.status_code in {200, 400}, contact.text

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
            json={"ride_id": ride_id, "target_state": target_state},
        )
        assert step.status_code == 200, f"{target_state}: {step.text}"

    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    assert ride.status_code == 200, ride.text
    ride_payload = ride.json()
    assert str(ride_payload.get("lifecycle_state") or ride_payload.get("status")).lower() == "completed"

    rider_history = client.get(
        "/api/health-isf/customers/workspace/history",
        headers=rider_headers,
        params={"rider_phone": rider_phone, "limit": 20},
    )
    assert rider_history.status_code == 200
    history_rows = rider_history.json().get("history", [])
    assert any(row.get("ride_id") == ride_id for row in history_rows)
    completed_history = next(row for row in history_rows if row.get("ride_id") == ride_id)
    assert str(completed_history.get("dispatch_status") or "").lower() == "completed"

    ride_timeline = client.get(f"/api/health-isf/rides/{ride_id}/history", headers=dispatcher_headers)
    assert ride_timeline.status_code == 200
    assert any(str(item.get("to_status") or "").lower() == "completed" for item in ride_timeline.json())

    active_assignments = client.get("/api/health-isf/dispatch/active-assignments", headers=dispatcher_headers, params={"limit": 200})
    assert active_assignments.status_code == 200
    assert not any(row.get("ride_id") == ride_id for row in active_assignments.json())

    dashboard_before = client.get("/api/health-isf/dashboard", headers=dispatcher_headers)
    assert dashboard_before.status_code == 200

    audit = client.get("/api/health-isf/dispatcher/audit-log", headers=admin_headers, params={"limit": 50})
    assert audit.status_code == 200, audit.text

    with SessionLocal() as db:
        persisted = hs.get_ride_by_id(db, ride_id)
        assert persisted is not None
        assert str(persisted.lifecycle_state or persisted.status).lower() == "completed"
        trip = (
            db.query(HealthISFTrip)
            .filter(HealthISFTrip.ride_id == ride_id)
            .order_by(HealthISFTrip.created_at.desc())
            .first()
        )
        assert trip is not None
        financial = client.get(f"/api/health-isf/rides/{ride_id}/financial-summary", headers=dispatcher_headers)
        assert financial.status_code == 200, financial.text
        financial_body = financial.json()
        assert financial_body["driver_pay_usd"] > 0
        assert financial_body["billing_handoff_id"]
        assert financial_body["billing_handoff_status"] == "ready"

        earnings = client.get(f"/api/health-isf/drivers/{driver_id}/earnings", headers=dispatcher_headers)
        assert earnings.status_code == 200, earnings.text
        assert earnings.json()["earnings_lifetime_usd"] >= financial_body["driver_pay_usd"]
        assert earnings.json()["trip_count"] >= 1

        completed_rides = client.get(
            f"/api/health-isf/drivers/{driver_id}/completed-rides",
            headers=dispatcher_headers,
            params={"limit": 10},
        )
        assert completed_rides.status_code == 200
        assert any(row["id"] == ride_id for row in completed_rides.json())

        billing_queue = client.get("/api/health-isf/operations/billing-handoffs", headers=dispatcher_headers, params={"limit": 20})
        assert billing_queue.status_code == 200
        assert any(row["ride_id"] == ride_id for row in billing_queue.json())

        admin_revenue = client.get("/api/health-isf/operations/admin-revenue", headers=dispatcher_headers)
        assert admin_revenue.status_code == 200
        assert admin_revenue.json()["completed_trip_count"] >= 1
        assert admin_revenue.json()["platform_revenue_total_usd"] > 0

        driver_row = hs.get_driver_by_id(db, driver_id)
        assert driver_row is not None
        assert int(driver_row.total_trips or 0) >= 1

        assert db.query(HealthISFTripFinancialRecord).filter(HealthISFTripFinancialRecord.ride_id == ride_id).count() == 1
        assert db.query(HealthISFBillingHandoff).filter(HealthISFBillingHandoff.ride_id == ride_id).count() == 1


def test_reassignment_pending_coherence_surfaces_active_ride(client: TestClient) -> None:
    """Split-brain: ride.driver_id set while assignment is reassignment_pending must still load in driver app."""
    org_id = _org_id_for("dispatcher@amicor.local")
    _ensure_provider(org_id)
    driver_id = _reseed_james(org_id)

    rider_auth = _login(client, "rider@amicor.local")
    rider_headers = _headers(rider_auth["access_token"])
    dispatcher_auth = _login(client, "dispatcher@amicor.local")
    dispatcher_headers = _headers(dispatcher_auth["access_token"])

    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    rider_phone = f"646-555-{phone_digits}"

    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Split Brain Rider {suffix}",
            "rider_phone": rider_phone,
            "pickup_address": f"10 Split Ave {suffix}, New York, NY 10001",
            "dropoff_address": f"20 Hospital Rd {suffix}, New York, NY 10002",
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

    ride_before_assign = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    assert ride_before_assign.status_code == 200, ride_before_assign.text
    if str(ride_before_assign.json().get("driver_id") or "") != driver_id:
        assign = client.post(
            f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            headers=dispatcher_headers,
            json={"driver_id": driver_id},
        )
        assert assign.status_code == 200, assign.text

    active_before = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-ride",
        headers=dispatcher_headers,
    )
    assert active_before.status_code == 200, active_before.text
    assert active_before.json().get("has_active_ride") is True

    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        assignment = hs._latest_driver_assignment_for_ride(db, ride_id=ride_id, driver_id=driver_id)
        assert assignment is not None
        assignment.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
        assignment.reassignment_pending_at = hs.now()
        assignment.updated_at = hs.now()
        db.commit()

    active_ride = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-ride",
        headers=dispatcher_headers,
    )
    assert active_ride.status_code == 200, active_ride.text
    payload = active_ride.json()
    assert payload.get("has_active_ride") is True
    assert (payload.get("ride") or {}).get("id") == ride_id
    assert payload.get("assignment_state") in {
        DispatchAssignmentState.OFFERED.value,
        DispatchAssignmentState.ACCEPTED.value,
        DispatchAssignmentState.ASSIGNED.value,
    }

    queue = client.get("/api/health-isf/dispatch/queue", headers=dispatcher_headers, params={"limit": 200})
    assert queue.status_code == 200
    queue_row = next((row for row in queue.json() if row.get("ride_id") == ride_id), None)
    assert queue_row is not None
    assert queue_row.get("assignment_state") not in {
        DispatchAssignmentState.REASSIGNMENT_PENDING.value,
        "pending_assignment",
    }

    active_assignments = client.get(
        "/api/health-isf/dispatch/active-assignments",
        headers=dispatcher_headers,
        params={"limit": 200},
    )
    assert active_assignments.status_code == 200
    active_row = next((row for row in active_assignments.json() if row.get("ride_id") == ride_id), None)
    assert active_row is not None
    assert active_row.get("driver_id") == driver_id
    assert active_row.get("assignment_state") in {
        DispatchAssignmentState.OFFERED.value,
        DispatchAssignmentState.ACCEPTED.value,
        DispatchAssignmentState.ASSIGNED.value,
    }


def test_driver_dropoff_complete_from_in_progress_matches_ui(client: TestClient) -> None:
    """UI Complete Trip uses dropoff-complete after in_progress; backend must finish billing and release driver."""
    org_id = _org_id_for("dispatcher@amicor.local")
    _ensure_provider(org_id)
    driver_id = _reseed_james(org_id)

    rider_auth = _login(client, "rider@amicor.local")
    rider_headers = _headers(rider_auth["access_token"])
    dispatcher_auth = _login(client, "dispatcher@amicor.local")
    dispatcher_headers = _headers(dispatcher_auth["access_token"])

    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    rider_phone = f"646-555-{phone_digits}"

    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"UI Complete Rider {suffix}",
            "rider_phone": rider_phone,
            "pickup_address": f"300 UI Lane {suffix}, New York, NY 10001",
            "dropoff_address": f"400 Clinic Rd {suffix}, New York, NY 10002",
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

    ride_before_assign = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    assert ride_before_assign.status_code == 200, ride_before_assign.text
    if str(ride_before_assign.json().get("driver_id") or "") != driver_id:
        assign = client.post(
            f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            headers=dispatcher_headers,
            json={"driver_id": driver_id},
        )
        assert assign.status_code == 200, assign.text

    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dispatcher_headers,
        json={"ride_id": ride_id},
    )
    assert accept.status_code == 200, accept.text

    for target_state in ("en_route_pickup", "arrived_pickup", "rider_loaded", "trip_in_progress"):
        step = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=dispatcher_headers,
            json={"ride_id": ride_id, "target_state": target_state},
        )
        assert step.status_code == 200, f"{target_state}: {step.text}"

    dropoff = client.post(
        f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
        headers=dispatcher_headers,
        json={"ride_id": ride_id},
    )
    assert dropoff.status_code == 200, dropoff.text
    completed_payload = dropoff.json()
    assert str(completed_payload.get("lifecycle_state") or completed_payload.get("status")).lower() == "completed"

    handoff = client.get(
        f"/api/health-isf/rides/{ride_id}/completion-handoff",
        headers=dispatcher_headers,
    )
    assert handoff.status_code == 200, handoff.text
    assert handoff.json().get("billing_handoff_id")
    assert float(handoff.json().get("driver_pay_usd") or 0) > 0

    active_assignments = client.get(
        "/api/health-isf/dispatch/active-assignments",
        headers=dispatcher_headers,
        params={"limit": 200},
    )
    assert active_assignments.status_code == 200
    assert not any(row.get("ride_id") == ride_id for row in active_assignments.json())

    earnings = client.get(f"/api/health-isf/drivers/{driver_id}/earnings", headers=dispatcher_headers)
    assert earnings.status_code == 200, earnings.text
    assert earnings.json()["trip_count"] >= 1

    with SessionLocal() as db:
        driver = hs.get_driver_by_id(db, driver_id)
        assert driver is not None
        assert hs._coerce_driver_status(driver.status) == DriverStatus.AVAILABLE
        assert db.query(HealthISFBillingHandoff).filter(HealthISFBillingHandoff.ride_id == ride_id).count() == 1
