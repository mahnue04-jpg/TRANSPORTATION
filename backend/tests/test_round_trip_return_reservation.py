"""Same-driver return reservation after outbound completion."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service
from app.modules.health_isf.advance_scheduling import (
    list_upcoming_schedule_for_driver,
    reserve_paired_return_leg_after_outbound_complete,
)
from app.modules.health_isf.models import DispatchAssignmentState, DriverStatus, HealthISFDriver, HealthISFRide, RideStatus


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None and user.organization_id is not None
        return str(user.organization_id)


def _ensure_driver(organization_id: str) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Return Reserve Driver {uuid4()[:6]}",
            phone=f"917555{uuid4()[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"RR-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            availability_state="available",
            is_active=True,
            is_online=True,
            auth_state="active",
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_round_trip(client: TestClient, headers: dict[str, str], suffix: str) -> tuple[str, str]:
    pickup = datetime.now(timezone.utc) + timedelta(days=5)
    pickup = pickup.replace(hour=10, minute=0, second=0, microsecond=0)
    arrival = pickup + timedelta(hours=1)
    return_pickup = arrival + timedelta(hours=2)
    created = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": f"return_reserve_{suffix}",
            "rider_phone": f"646557{''.join(ch for ch in suffix if ch.isdigit()).ljust(4, '0')[:4]}",
            "pickup_address": f"10 Return Reserve Pickup {suffix}, NY",
            "dropoff_address": f"20 Return Reserve Dropoff {suffix}, NY",
            "ride_type": "healthcare",
            "trip_type": "round_trip",
            "same_driver_preference": True,
            "service_date": pickup.date().isoformat(),
            "pickup_time": pickup.isoformat(),
            "arrival_time": arrival.isoformat(),
            "return_pickup_time": return_pickup.isoformat(),
            "return_pickup_type": "scheduled_time",
        },
    )
    assert created.status_code == 201, created.text
    linked = created.json().get("linked_ride_ids") or []
    assert len(linked) >= 2
    with SessionLocal() as db:
        rides = db.query(HealthISFRide).filter(HealthISFRide.id.in_(linked)).all()
        outbound = next(r for r in rides if str(r.trip_leg or "") == "outbound")
        return_leg = next(r for r in rides if str(r.trip_leg or "") == "return")
        return str(outbound.id), str(return_leg.id)


def test_outbound_complete_reserves_return_for_same_driver(client: TestClient) -> None:
    rider_auth = client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD})
    headers = {"Authorization": f"Bearer {rider_auth.json()['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    suffix = uuid4()[:8]
    driver_id = _ensure_driver(org_id)
    outbound_id, return_id = _create_round_trip(client, headers, suffix)

    with SessionLocal() as db:
        outbound = service.get_ride_by_id(db, outbound_id)
        return_leg = service.get_ride_by_id(db, return_id)
        assert outbound is not None and return_leg is not None
        outbound.driver_id = driver_id
        outbound.lifecycle_state = RideStatus.COMPLETED.value
        outbound.status = RideStatus.COMPLETED.value
        outbound.completed_at = datetime.now(timezone.utc)
        db.commit()

        result = reserve_paired_return_leg_after_outbound_complete(
            db,
            outbound_ride=outbound,
            driver_id=driver_id,
            actor_user_id=None,
        )
        assert result["mode"] in {"reserved", "existing"}
        assert result["return_ride_id"] == return_id
        assert result["assignment_state"] == DispatchAssignmentState.SCHEDULED_ACCEPTED.value

        upcoming = list_upcoming_schedule_for_driver(db, organization_id=org_id, driver_id=driver_id)
        assert any(str(row["ride_id"]) == return_id for row in upcoming)

        return_leg = service.get_ride_by_id(db, return_id)
        assert return_leg is not None
        assert str(return_leg.driver_id or "") == driver_id
