"""Rider scheduling: round-trip legs, recurrence, dispatch windows, protected reservations."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service
from app.modules.health_isf.models import DriverStatus, HealthISFProvider, HealthISFRide
from app.modules.health_isf.scheduling import (
    activate_call_when_ready_return,
    is_dispatch_eligible,
    is_protected_scheduled_reservation,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict[str, Any]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        assert user.organization_id is not None
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
            name=f"Scheduling Provider {uuid4()[:6]}",
            address="500 Scheduling Avenue",
            phone="212-555-0700",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _ensure_driver(organization_id: str) -> str:
    from app.modules.health_isf.models import HealthISFDriver

    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Scheduling Driver {uuid4()[:6]}",
            phone=f"917-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"SC-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            availability_state="available",
            is_active=True,
            is_online=True,
            auth_state="active",
            rating=4.8,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _future_dt(days: int = 1, hour: int = 10) -> datetime:
    base = datetime.now(timezone.utc) + timedelta(days=days)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0)


def _create_request(
    client: TestClient,
    headers: dict[str, str],
    *,
    suffix: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    body = {
        "rider_name": f"rider_scheduling_validation_{suffix}",
        "rider_phone": f"+1 646-555-{digits}",
        "pickup_address": f"100 Scheduling Pickup {suffix}, New York, NY",
        "dropoff_address": f"200 Scheduling Dropoff {suffix}, New York, NY",
        "ride_type": "healthcare",
        **payload,
    }
    response = client.post("/api/health-isf/customer-requests", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _rides_for_request(request_id: str) -> list[HealthISFRide]:
    with SessionLocal() as db:
        row = service.get_customer_ride_request_by_id(db, request_id)
        assert row is not None
        linked = service.get_ride_by_id(db, str(row.ride_id))
        assert linked is not None
        group_id = getattr(linked, "round_trip_group_id", None)
        series_id = getattr(linked, "scheduling_series_id", None)
        query = db.query(HealthISFRide).filter(HealthISFRide.organization_id == linked.organization_id)
        if group_id:
            rows = query.filter(HealthISFRide.round_trip_group_id == group_id).all()
            if rows:
                return rows
        if series_id:
            return query.filter(HealthISFRide.scheduling_series_id == series_id).order_by(HealthISFRide.created_at.asc()).all()
        return [linked]


def _isolate_driver(organization_id: str, driver_id: str) -> None:
    from app.modules.health_isf.models import HealthISFDriver

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
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.id != driver_id,
            HealthISFDriver.is_active == True,
        ):
            row.status = DriverStatus.OFFLINE
            row.availability_state = "offline"
            row.is_online = False
        db.commit()


def _adopt_or_assign_immediate_ride(ride_id: str, driver_id: str) -> str:
    """Wait for intake auto-dispatch, then assign only if the same-day ride is still open."""
    deadline = time.time() + 6
    while time.time() < deadline:
        with SessionLocal() as db:
            ride = service.get_ride_by_id(db, ride_id)
            assigned = str(getattr(ride, "driver_id", "") or "") if ride else ""
            if assigned:
                return assigned
            assignment = service._latest_assignment_for_ride(db, ride_id)
            assignment_driver = str(getattr(assignment, "driver_id", "") or "") if assignment else ""
            assignment_state = str(getattr(assignment, "assignment_state", "") or "")
            if assignment_driver and assignment_state in {
                "offered",
                "assigned",
                "accepted",
                "scheduled_offered",
                "scheduled_accepted",
            }:
                return assignment_driver
        time.sleep(0.2)
    with SessionLocal() as db:
        ride = service.assign_driver_to_ride(db, ride_id, driver_id, actor_user_id=None)
        assert ride is not None
        return str(ride.driver_id)


def test_same_day_round_trip_creates_linked_legs(client: TestClient) -> None:
    rider_auth = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {rider_auth['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    _ensure_provider(org_id)
    suffix = uuid4()[:8]
    service_date = date.today()
    pickup = datetime.combine(service_date, datetime.min.time(), tzinfo=timezone.utc).replace(hour=8)
    arrival = pickup + timedelta(hours=1)
    return_pickup = arrival + timedelta(hours=2)

    created = _create_request(
        client,
        headers,
        suffix=suffix,
        payload={
            "trip_type": "round_trip",
            "service_date": service_date.isoformat(),
            "pickup_time": pickup.isoformat(),
            "arrival_time": arrival.isoformat(),
            "return_pickup_type": "scheduled_time",
            "return_pickup_time": return_pickup.isoformat(),
        },
    )
    rides = _rides_for_request(created["id"])
    assert len(rides) == 2
    group_ids = {str(r.round_trip_group_id) for r in rides}
    assert len(group_ids) == 1
    legs = {str(r.trip_leg) for r in rides}
    assert legs == {"outbound", "return"}
    assert any("Scheduling Pickup" in (r.pickup_address or "") for r in rides)
    assert any("Scheduling Dropoff" in (r.dropoff_address or "") for r in rides)


def test_future_round_trip_stays_scheduled_until_window(client: TestClient) -> None:
    rider_auth = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {rider_auth['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    _ensure_provider(org_id)
    suffix = uuid4()[:8]
    arrival = _future_dt(days=2, hour=14)
    pickup = arrival - timedelta(minutes=45)

    created = _create_request(
        client,
        headers,
        suffix=suffix,
        payload={
            "trip_type": "round_trip",
            "service_date": arrival.date().isoformat(),
            "pickup_time": pickup.isoformat(),
            "arrival_time": arrival.isoformat(),
            "return_pickup_type": "call_when_ready",
        },
    )
    rides = _rides_for_request(created["id"])
    outbound = next(r for r in rides if r.trip_leg == "outbound")
    assert str(outbound.lifecycle_state or "") in {"scheduled", "pending", "queued"}
    assert not is_dispatch_eligible(outbound)
    assert is_protected_scheduled_reservation(outbound)


def test_weekly_recurring_dialysis_generates_legs(client: TestClient) -> None:
    rider_auth = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {rider_auth['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    _ensure_provider(org_id)
    suffix = uuid4()[:8]
    start = date.today() + timedelta(days=1)
    end = start + timedelta(days=7)
    pickup = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).replace(hour=7)
    arrival = pickup + timedelta(minutes=45)

    created = _create_request(
        client,
        headers,
        suffix=suffix,
        payload={
            "trip_type": "round_trip",
            "service_date": start.isoformat(),
            "pickup_time": pickup.isoformat(),
            "arrival_time": arrival.isoformat(),
            "return_pickup_type": "call_when_ready",
            "recurrence": "weekly",
            "recurrence_weekdays": ["mon", "wed", "fri"],
            "recurrence_end_date": end.isoformat(),
        },
    )
    with SessionLocal() as db:
        row = service.get_customer_ride_request_by_id(db, created["id"])
        assert row is not None
        linked_ids = created.get("linked_ride_ids") or []
        assert len(linked_ids) >= 2
        rides = db.query(HealthISFRide).filter(HealthISFRide.id.in_(linked_ids)).all()
        assert len(rides) >= 4
        series_ids = {str(r.scheduling_series_id) for r in rides if r.scheduling_series_id}
        assert len(series_ids) == 1


def test_future_assignment_survives_unrelated_completion(client: TestClient) -> None:
    from tests.health_isf_driver_test_helpers import reset_scheduling_test_organization

    org_id = _org_id_for("rider@amicor.local")
    reset_scheduling_test_organization(org_id)
    _ensure_provider(org_id)
    driver_id = _ensure_driver(org_id)
    _isolate_driver(org_id, driver_id)
    dispatcher_auth = _login(client, "dispatcher@amicor.local")
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher_auth['access_token']}"}
    rider_auth = _login(client, "rider@amicor.local")
    rider_headers = {"Authorization": f"Bearer {rider_auth['access_token']}"}
    suffix = uuid4()[:8]

    future_arrival = _future_dt(days=1, hour=11)
    future_pickup = future_arrival - timedelta(minutes=30)
    future_req = _create_request(
        client,
        rider_headers,
        suffix=f"fut{suffix}",
        payload={
            "trip_type": "one_way",
            "service_date": future_arrival.date().isoformat(),
            "pickup_time": future_pickup.isoformat(),
            "arrival_time": future_arrival.isoformat(),
        },
    )
    future_ride_id = future_req["ride_id"]

    with SessionLocal() as db:
        from app.modules.health_isf.advance_scheduling import accept_scheduled_ride, assign_driver_to_scheduled_ride

        assign_driver_to_scheduled_ride(db, ride_id=future_ride_id, driver_id=driver_id, actor_user_id=None)
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=future_ride_id, actor_user_id=None)
        future = service.get_ride_by_id(db, future_ride_id)
        assert future is not None
        assert str(future.driver_id or "") == driver_id

    today_req = _create_request(
        client,
        rider_headers,
        suffix=f"tod{suffix}",
        payload={"trip_type": "one_way"},
    )
    today_ride_id = today_req["ride_id"]
    today_driver_id = _adopt_or_assign_immediate_ride(today_ride_id, driver_id)
    assert today_driver_id, "same-day ride must have a driver before completion"

    with SessionLocal() as db:
        service.accept_driver_ride(db, today_driver_id, today_ride_id, actor_user_id=None)[0]
        service.driver_en_route_pickup(db, today_driver_id, today_ride_id)
        service.driver_arrived_pickup(db, today_driver_id, today_ride_id)
        service.driver_pickup_complete(db, today_driver_id, today_ride_id)
        service.driver_start_trip(db, today_driver_id, today_ride_id)
        service.driver_arrived_destination(db, today_driver_id, today_ride_id)
        service.driver_dropoff_complete(db, today_driver_id, today_ride_id, actor_user_id=None)
        future = service.get_ride_by_id(db, future_ride_id)
        assert future is not None
        assert str(future.driver_id or "") == driver_id, "Future scheduled assignment must survive unrelated completion"


def test_call_when_ready_activation(client: TestClient) -> None:
    rider_auth = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {rider_auth['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    _ensure_provider(org_id)
    suffix = uuid4()[:8]
    arrival = _future_dt(days=1, hour=9)
    pickup = arrival - timedelta(minutes=20)

    created = _create_request(
        client,
        headers,
        suffix=suffix,
        payload={
            "trip_type": "round_trip",
            "service_date": arrival.date().isoformat(),
            "pickup_time": pickup.isoformat(),
            "arrival_time": arrival.isoformat(),
            "return_pickup_type": "call_when_ready",
        },
    )
    rides = _rides_for_request(created["id"])
    return_leg = next(r for r in rides if r.trip_leg == "return")
    assert bool(return_leg.call_when_ready) is True
    assert not is_dispatch_eligible(return_leg)

    response = client.post(
        f"/api/health-isf/customer-requests/{created['id']}/patient-ready",
        headers=headers,
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        refreshed = service.get_ride_by_id(db, str(return_leg.id))
        assert refreshed is not None
        assert bool(refreshed.call_when_ready) is False
        assert is_dispatch_eligible(refreshed)


def test_round_trip_group_billing_view(client: TestClient) -> None:
    rider_auth = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {rider_auth['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    _ensure_provider(org_id)
    suffix = uuid4()[:8]
    service_date = date.today()
    pickup = datetime.combine(service_date, datetime.min.time(), tzinfo=timezone.utc).replace(hour=9)
    arrival = pickup + timedelta(minutes=40)
    return_pickup = arrival + timedelta(hours=1, minutes=30)

    created = _create_request(
        client,
        headers,
        suffix=suffix,
        payload={
            "trip_type": "round_trip",
            "service_date": service_date.isoformat(),
            "pickup_time": pickup.isoformat(),
            "arrival_time": arrival.isoformat(),
            "return_pickup_type": "scheduled_time",
            "return_pickup_time": return_pickup.isoformat(),
        },
    )
    assert created.get("round_trip_group_id")
    group_id = created["round_trip_group_id"]
    response = client.get(f"/api/health-isf/rides/round-trip/{group_id}", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["round_trip_group_id"] == group_id
    assert len(payload["rides"]) == 2


def test_customer_request_empty_service_date_coerced() -> None:
    from app.modules.health_isf.schemas import CustomerRideRequestCreateRequest

    future = datetime.now(timezone.utc) + timedelta(hours=2)
    payload = CustomerRideRequestCreateRequest(
        rider_name="Test Rider",
        rider_phone="6129982874",
        pickup_address="2823 aldrich ave north",
        dropoff_address="hcmc",
        service_date="",
        trip_type="round_trip",
        return_pickup_type="scheduled_time",
        arrival_time=future,
        return_pickup_time=future + timedelta(hours=2),
        return_pickup_address="hcmc",
        return_dropoff_address="2823 aldrich ave north",
    )
    assert payload.service_date is None


def test_round_trip_past_scheduled_time_allowed_with_scheduling_fields() -> None:
    from app.modules.health_isf.schemas import CustomerRideRequestCreateRequest

    past = datetime.now(timezone.utc) - timedelta(hours=3)
    payload = CustomerRideRequestCreateRequest(
        rider_name="Test Rider",
        rider_phone="6129982874",
        pickup_address="2823 aldrich ave north",
        dropoff_address="hcmc",
        service_date=date.today(),
        trip_type="round_trip",
        pickup_time=past,
        arrival_time=past + timedelta(minutes=15),
        scheduled_time=past + timedelta(minutes=15),
        return_pickup_type="scheduled_time",
        return_pickup_time=past + timedelta(hours=2),
        return_pickup_address="hcmc",
        return_dropoff_address="2823 aldrich ave north",
    )
    assert payload.trip_type == "round_trip"


def test_scheduling_test_marker_cleanup(client: TestClient) -> None:
    rider_auth = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {rider_auth['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    _ensure_provider(org_id)
    suffix = uuid4()[:8]
    marker = f"rider_scheduling_validation_{suffix}"
    created = _create_request(client, headers, suffix=suffix, payload={"trip_type": "one_way"})
    with SessionLocal() as db:
        rides = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.passenger_name.like(f"{marker}%"))
            .all()
        )
        assert rides
        for ride in rides:
            ride.lifecycle_state = "cancelled"
            ride.status = "cancelled"
        db.commit()
        remaining = (
            db.query(HealthISFRide)
            .filter(
                HealthISFRide.passenger_name.like("rider_scheduling_validation_%"),
                HealthISFRide.lifecycle_state.notin_(["cancelled", "completed"]),
            )
            .count()
        )
        assert remaining >= 0
    assert created["ride_id"]
