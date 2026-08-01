"""
Deployment-readiness audit: full Health ISF ride lifecycle end-to-end.

Simulates the AI-first dispatch workflow through completion and verifies
API, database, dashboard, activity feed, billing, and driver availability
stay consistent at each step.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    DriverStatus,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFPayout,
    HealthISFProvider,
    HealthISFRide,
    HealthISFTrip,
    RideStatus,
)
from app.modules.health_isf import service as hs
from app.modules.health_isf.workflow_engine import WorkflowOrchestrationService


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(client: TestClient) -> dict[str, str]:
    auth = _login(client)
    return {"Authorization": f"Bearer {auth['access_token']}"}


def _org_id(email: str = "dispatcher@amicor.local") -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None and user.organization_id is not None
        return user.organization_id


def _ensure_provider(org_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == org_id, HealthISFProvider.is_active == True)
            .first()
        )
        if provider:
            return provider.id
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=org_id,
            name=f"Deploy Provider {uuid4()[:6]}",
            address="100 Deploy Ave",
            phone="212-555-9900",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return provider.id


def _ensure_available_driver(org_id: str, *, suffix: str = "") -> str:
    token = suffix or uuid4()[:6]
    phone_suffix = "".join(ch for ch in str(uuid4()) if ch.isdigit())[:4].ljust(4, "8")
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org_id,
            name=f"Deploy Driver {token}",
            phone=f"917-555-{phone_suffix}",
            vehicle_type="sedan",
            vehicle_plate=f"DP-{token[:4].upper()}-{phone_suffix}",
            status=DriverStatus.AVAILABLE,
            availability_state="available",
            is_online=True,
            auth_state="active",
            is_active=True,
            rating=4.8,
        )
        db.add(driver)
        db.commit()
        return driver.id


def _require_intake_dispatcher_approval(org_id: str) -> None:
    with SessionLocal() as db:
        policy = WorkflowOrchestrationService.ensure_policy(db, org_id)
        policy.approval_required = True
        policy.is_enabled = True
        db.commit()


def _isolate_driver_for_recommendation(org_id: str, driver_id: str) -> None:
    with SessionLocal() as db:
        dedicated = db.query(HealthISFDriver).filter(HealthISFDriver.id == driver_id).first()
        assert dedicated is not None
        dedicated.rating = 5.0
        dedicated.total_trips = 100
        dedicated.status = DriverStatus.AVAILABLE
        dedicated.availability_state = "available"
        dedicated.is_online = True
        dedicated.auth_state = "active"
        dedicated.is_active = True
        for row in db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == org_id,
            HealthISFDriver.id != driver_id,
            HealthISFDriver.is_active == True,
        ):
            row.status = DriverStatus.OFFLINE
            row.availability_state = "offline"
        db.commit()


def _queue_row(client: TestClient, headers: dict[str, str], ride_id: str) -> dict:
    response = client.get("/api/health-isf/dispatch/queue", headers=headers)
    assert response.status_code == 200, response.text
    row = next((item for item in response.json() if item.get("ride_id") == ride_id), None)
    assert row is not None, f"Ride {ride_id} missing from dispatch queue"
    return row


def _assignment_for_ride(ride_id: str) -> HealthISFDispatchAssignment | None:
    with SessionLocal() as db:
        return (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride_id)
            .order_by(HealthISFDispatchAssignment.created_at.desc())
            .first()
        )


def _ride(ride_id: str) -> HealthISFRide:
    with SessionLocal() as db:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
        assert ride is not None
        return ride


def _driver(driver_id: str) -> HealthISFDriver:
    with SessionLocal() as db:
        driver = db.query(HealthISFDriver).filter(HealthISFDriver.id == driver_id).first()
        assert driver is not None
        return driver


def _reset_org_assignments(org_id: str) -> None:
    with SessionLocal() as db:
        hs.repair_organization_assignment_state(db, organization_id=org_id, dry_run=False)
        for driver in db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org_id).all():
            driver.status = DriverStatus.AVAILABLE
            driver.availability_state = "available"
            driver.is_online = True
            driver.auth_state = "active"
            driver.updated_at = hs.now()
        db.commit()


def _response_ride_state(payload: dict) -> str:
    if payload.get("lifecycle_state"):
        return str(payload.get("lifecycle_state"))
    active = payload.get("active_ride") or {}
    return str(active.get("lifecycle_state") or active.get("status") or "")


class TestDeploymentReadinessRideLifecycle:
    def test_full_ai_first_lifecycle_with_metrics_and_billing(self, client: TestClient):
        headers = _headers(client)
        org_id = _org_id()
        _reset_org_assignments(org_id)
        _require_intake_dispatcher_approval(org_id)
        provider_id = _ensure_provider(org_id)
        driver_id = _ensure_available_driver(org_id, suffix="MAIN")
        _isolate_driver_for_recommendation(org_id, driver_id)

        dashboard_before = client.get("/api/health-isf/dashboard", headers=headers)
        assert dashboard_before.status_code == 200, dashboard_before.text
        completed_before = dashboard_before.json().get("completed_rides", 0)

        create = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": f"Deploy Audit Rider {uuid4()[:6]}",
                "passenger_phone": "917-555-7001",
                "service_type": "medical_transport",
                "pickup_address": "100 Audit Pickup St",
                "dropoff_address": "200 Audit Dropoff Ave",
                "estimated_distance_miles": 6.5,
            },
        )
        assert create.status_code in {200, 201}, create.text
        ride_id = create.json()["id"]
        assert create.json().get("lifecycle_state") == RideStatus.QUEUED.value

        queue_row = _queue_row(client, headers, ride_id)
        assignment_state = str(queue_row.get("assignment_state") or "")
        assert assignment_state in {
            DispatchAssignmentState.AWAITING_APPROVAL.value,
            DispatchAssignmentState.OFFERED.value,
        }, assignment_state
        assert queue_row.get("recommended_driver_id") == str(driver_id)
        assert queue_row.get("recommended_driver_name")
        assert queue_row.get("dispatcher_message")
        assert "none" not in str(queue_row.get("dispatcher_message", "")).lower()

        if assignment_state == DispatchAssignmentState.AWAITING_APPROVAL.value:
            awaiting_count = sum(
                1
                for item in client.get("/api/health-isf/dispatch/queue", headers=headers).json()
                if item.get("assignment_state") == DispatchAssignmentState.AWAITING_APPROVAL.value
            )
            assert awaiting_count >= 1

            approve = client.post(
                "/api/health-isf/dispatch/recommendations/approve",
                headers=headers,
                json={"ride_id": ride_id, "offer_timeout_seconds": 90},
            )
            assert approve.status_code == 200, approve.text
            assert approve.json().get("assignment_state") == DispatchAssignmentState.OFFERED.value
            assert approve.json().get("recommended_driver_id") == str(driver_id)
        else:
            approve = client.post(
                "/api/health-isf/dispatch/recommendations/approve",
                headers=headers,
                json={"ride_id": ride_id, "offer_timeout_seconds": 90},
            )
            assert approve.status_code in {200, 400}, approve.text

        assignment = _assignment_for_ride(ride_id)
        assert assignment is not None
        assert assignment.assignment_state == DispatchAssignmentState.OFFERED.value
        assert str(assignment.driver_id) == str(driver_id)
        assert str(_ride(ride_id).driver_id) == str(driver_id)

        accept = client.post(
            f"/api/health-isf/drivers/{driver_id}/accept-ride",
            headers=headers,
            json={"ride_id": ride_id},
        )
        assert accept.status_code == 200, accept.text
        assert accept.json().get("lifecycle_state") in {
            RideStatus.DRIVER_EN_ROUTE.value,
            RideStatus.ASSIGNED.value,
        }
        assignment = _assignment_for_ride(ride_id)
        assert assignment.assignment_state in {
            DispatchAssignmentState.ACCEPTED.value,
            DispatchAssignmentState.EN_ROUTE_PICKUP.value,
        }

        if accept.json().get("lifecycle_state") == RideStatus.ASSIGNED.value:
            en_route = client.post(
                f"/api/health-isf/drivers/{driver_id}/route-progress",
                headers=headers,
                json={"ride_id": ride_id, "target_state": "en_route_pickup"},
            )
            assert en_route.status_code == 200, en_route.text

        arrived = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=headers,
            json={"ride_id": ride_id, "target_state": "arrived_pickup"},
        )
        assert arrived.status_code == 200, arrived.text
        assert _response_ride_state(arrived.json()) == RideStatus.ARRIVED.value

        pickup = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=headers,
            json={"ride_id": ride_id, "target_state": "rider_loaded"},
        )
        assert pickup.status_code == 200, pickup.text
        trip_progress = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=headers,
            json={"ride_id": ride_id, "target_state": "trip_in_progress"},
        )
        assert trip_progress.status_code == 200, trip_progress.text
        assert _response_ride_state(trip_progress.json()) == RideStatus.IN_PROGRESS.value

        destination = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=headers,
            json={"ride_id": ride_id, "target_state": "arrived_destination"},
        )
        assert destination.status_code == 200, destination.text

        complete = client.post(
            f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
            headers=headers,
            json={"ride_id": ride_id},
        )
        assert complete.status_code == 200, complete.text
        assert complete.json().get("lifecycle_state") == RideStatus.COMPLETED.value
        assert complete.json().get("status") == RideStatus.COMPLETED.value

        handoff = client.get(f"/api/health-isf/rides/{ride_id}/completion-handoff", headers=headers)
        assert handoff.status_code == 200, handoff.text
        handoff_payload = handoff.json()
        assert handoff_payload.get("billing_queue_ready") is True
        assert handoff_payload.get("trip_id")
        assert handoff_payload.get("payout_id")

        with SessionLocal() as db:
            trip = db.query(HealthISFTrip).filter(HealthISFTrip.ride_id == ride_id).first()
            assert trip is not None
            payout = db.query(HealthISFPayout).filter(HealthISFPayout.trip_id == trip.id).first()
            assert payout is not None
            assert float(payout.amount_usd) > 0

        driver_after = _driver(driver_id)
        driver_status = driver_after.status.value if isinstance(driver_after.status, DriverStatus) else str(driver_after.status).lower()
        with SessionLocal() as db:
            workload = hs._driver_active_workload_count(db, driver_id)
        if driver_status == DriverStatus.ASSIGNED.value:
            active = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=headers)
            assert active.status_code == 200, active.text
            active_ride_id = (active.json().get("ride") or {}).get("id")
            assert active_ride_id != ride_id
            assert workload <= 1
        else:
            assert driver_status == DriverStatus.AVAILABLE.value
            assert workload == 0
        assert str(driver_after.availability_state).lower() in {"available", "offer_pending"}

        dashboard_after = client.get("/api/health-isf/dashboard", headers=headers)
        assert dashboard_after.status_code == 200, dashboard_after.text
        completed_after = dashboard_after.json().get("completed_rides", 0)
        assert completed_after >= completed_before + 1

        activity = client.get("/api/health-isf/activity-feed", headers=headers)
        assert activity.status_code == 200, activity.text
        feed_items = activity.json().get("activities") or []
        assert len(feed_items) > 0

        driver_workspace = client.get(
            f"/api/health-isf/drivers/{driver_id}/live-workspace",
            headers=headers,
        )
        assert driver_workspace.status_code == 200, driver_workspace.text

        customer_workspace = client.get(
            "/api/health-isf/customers/workspace/active?rider_phone=917-555-7001",
            headers=headers,
        )
        assert customer_workspace.status_code == 200, customer_workspace.text

    def test_cancel_reassign_and_escalate_paths(self, client: TestClient):
        headers = _headers(client)
        org_id = _org_id()
        _reset_org_assignments(org_id)
        provider_id = _ensure_provider(org_id)
        driver_a = _ensure_available_driver(org_id, suffix="CANA")
        driver_b = _ensure_available_driver(org_id, suffix="CANB")

        cancel_create = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": f"Cancel Rider {uuid4()[:6]}",
                "passenger_phone": "917-555-7002",
                "service_type": "medical_transport",
                "pickup_address": "10 Cancel St",
                "dropoff_address": "20 Cancel Ave",
            },
        )
        assert cancel_create.status_code in {200, 201}, cancel_create.text
        cancel_ride_id = cancel_create.json()["id"]

        cancel = client.patch(
            f"/api/health-isf/dispatcher/rides/{cancel_ride_id}/cancel?reason=deployment-audit-cancel",
            headers=headers,
        )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json().get("lifecycle_state") == RideStatus.CANCELLED.value

        reassign_create = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": f"Reassign Rider {uuid4()[:6]}",
                "passenger_phone": "917-555-7003",
                "service_type": "medical_transport",
                "pickup_address": "30 Reassign St",
                "dropoff_address": "40 Reassign Ave",
            },
        )
        assert reassign_create.status_code in {200, 201}, reassign_create.text
        reassign_ride_id = reassign_create.json()["id"]

        approve = client.post(
            "/api/health-isf/dispatch/recommendations/approve",
            headers=headers,
            json={"ride_id": reassign_ride_id, "offer_timeout_seconds": 90},
        )
        assert approve.status_code == 200, approve.text

        reassign = client.patch(
            f"/api/health-isf/dispatcher/rides/{reassign_ride_id}/reassign-driver",
            headers=headers,
            json={"driver_id": driver_b},
        )
        assert reassign.status_code == 200, reassign.text
        assert str(reassign.json().get("driver_id")) == str(driver_b)

        escalate_create = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": f"Escalate Rider {uuid4()[:6]}",
                "passenger_phone": "917-555-7004",
                "service_type": "medical_transport",
                "pickup_address": "50 Escalate St",
                "dropoff_address": "60 Escalate Ave",
            },
        )
        assert escalate_create.status_code in {200, 201}, escalate_create.text
        escalate_ride_id = escalate_create.json()["id"]

        approve_escalate = client.post(
            "/api/health-isf/dispatch/recommendations/approve",
            headers=headers,
            json={"ride_id": escalate_ride_id, "offer_timeout_seconds": 90},
        )
        assert approve_escalate.status_code == 200, approve_escalate.text

        escalate = client.post(
            f"/api/health-isf/dispatcher/rides/{escalate_ride_id}/escalate"
            f"?issue_type=delay&description=deployment-audit-escalation",
            headers=headers,
        )
        assert escalate.status_code == 200, escalate.text

        ops_metrics = client.get("/api/health-isf/ops/metrics", headers=headers)
        assert ops_metrics.status_code == 200, ops_metrics.text

        # Ensure no 401/404/500 on core read surfaces used by UI hydration.
        for path in (
            "/api/health-isf/dispatch/queue",
            "/api/health-isf/dispatch/active-assignments",
            "/api/health-isf/drivers",
            "/api/health-isf/rides",
            "/api/health-isf/intelligence/summary",
        ):
            response = client.get(path, headers=headers)
            assert response.status_code == 200, f"{path} -> {response.status_code}: {response.text}"

        assert str(_driver(driver_a).status.value if isinstance(_driver(driver_a).status, DriverStatus) else _driver(driver_a).status).lower() in {
            DriverStatus.AVAILABLE.value,
            DriverStatus.ASSIGNED.value,
            DriverStatus.OFFLINE.value,
        }
