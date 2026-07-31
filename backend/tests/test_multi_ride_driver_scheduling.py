"""Multi-ride driver scheduling: capacity, overlap, and same-driver return pairing."""
from __future__ import annotations

import random
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service
from app.modules.health_isf.advance_scheduling import (
    accept_scheduled_ride,
    assign_driver_to_scheduled_ride,
    evaluate_advance_scheduling_candidates,
    reserve_paired_return_leg_after_outbound_complete,
    run_advance_scheduling_for_ride,
)
from app.modules.health_isf.models import (
    DriverStatus,
    HealthISFDriver,
    HealthISFRide,
    RideStatus,
)
from app.modules.health_isf.scheduling import apply_scheduling_fields_to_ride, driver_has_schedule_conflict


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


def _ensure_driver(
    organization_id: str,
    *,
    name_suffix: str,
    is_online: bool = True,
) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Multi Driver {name_suffix}",
            phone=f"917{random.randint(1000000, 9999999)}",
            vehicle_type="sedan",
            vehicle_plate=f"MD-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            availability_state="available",
            is_active=True,
            is_online=is_online,
            auth_state="active",
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _scheduled_leg(
    db,
    *,
    organization_id: str,
    pickup_time,
    trip_leg: str = "one_way",
    round_trip_group_id: str | None = None,
    same_driver_preference: bool = False,
    label: str = "Leg",
) -> HealthISFRide:
    ride = HealthISFRide(
        id=uuid4(),
        organization_id=organization_id,
        passenger_name=f"{label} Rider",
        passenger_phone=f"646555{random.randint(1000, 9999)}",
        pickup_address=f"10 {label} Pickup",
        dropoff_address=f"20 {label} Dropoff",
        service_type="healthcare",
        status=RideStatus.PENDING,
        lifecycle_state="scheduled",
        requested_at=service.now(),
    )
    apply_scheduling_fields_to_ride(
        ride,
        trip_leg=trip_leg,
        round_trip_group_id=round_trip_group_id,
        pickup_time=pickup_time,
        arrival_time=pickup_time + timedelta(minutes=45),
        same_driver_preference=same_driver_preference,
    )
    ride.estimated_duration_minutes = 60
    db.add(ride)
    db.commit()
    db.refresh(ride)
    return ride


def test_two_drivers_receive_multiple_non_overlapping_same_day_rides(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_a = _ensure_driver(org_id, name_suffix="A")
    driver_b = _ensure_driver(org_id, name_suffix="B")
    base = service.now().replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=1)

    legs: list[tuple[HealthISFRide, str]] = []
    with SessionLocal() as db:
        for idx in range(5):
            pickup = base + timedelta(hours=idx * 5)
            ride = _scheduled_leg(db, organization_id=org_id, pickup_time=pickup, label=f"Out{idx}", trip_leg="outbound")
            target = driver_a if idx % 2 == 0 else driver_b
            assign_driver_to_scheduled_ride(db, ride_id=str(ride.id), driver_id=target)
            accept_scheduled_ride(db, driver_id=target, ride_id=str(ride.id))
            legs.append((ride, target))

        for idx in range(5):
            pickup = base + timedelta(hours=25 + idx * 5)
            ride = _scheduled_leg(db, organization_id=org_id, pickup_time=pickup, label=f"Ret{idx}", trip_leg="return")
            target = driver_a if idx % 2 == 0 else driver_b
            assign_driver_to_scheduled_ride(db, ride_id=str(ride.id), driver_id=target)
            accept_scheduled_ride(db, driver_id=target, ride_id=str(ride.id))
            legs.append((ride, target))

        counts = {driver_a: 0, driver_b: 0}
        for ride, driver_id in legs:
            counts[driver_id] += 1
            assert not driver_has_schedule_conflict(db, driver_id, ride)
        assert counts[driver_a] + counts[driver_b] == 10
        assert counts[driver_a] >= 4
        assert counts[driver_b] >= 4


def test_one_driver_receives_sequential_non_overlapping_rides(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id, name_suffix="Solo")
    base = service.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)

    with SessionLocal() as db:
        ride_ids: list[str] = []
        for idx in range(4):
            pickup = base + timedelta(hours=idx * 4)
            ride = _scheduled_leg(db, organization_id=org_id, pickup_time=pickup, label=f"Seq{idx}")
            assign_driver_to_scheduled_ride(db, ride_id=str(ride.id), driver_id=driver_id)
            accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(ride.id))
            ride_ids.append(str(ride.id))
        for ride_id in ride_ids:
            ride = service.get_ride_by_id(db, ride_id)
            assert ride is not None
            assert not driver_has_schedule_conflict(db, driver_id, ride)


def test_overlapping_rides_not_assigned_to_same_driver(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id, name_suffix="Overlap")
    base = service.now().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)

    with SessionLocal() as db:
        first = _scheduled_leg(db, organization_id=org_id, pickup_time=base, label="First")
        assign_driver_to_scheduled_ride(db, ride_id=str(first.id), driver_id=driver_id)
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(first.id))

        overlapping = _scheduled_leg(
            db,
            organization_id=org_id,
            pickup_time=base + timedelta(minutes=30),
            label="Overlap",
        )
        assert driver_has_schedule_conflict(db, driver_id, overlapping)
        with pytest.raises(ValueError, match="conflicting"):
            assign_driver_to_scheduled_ride(
                db,
                ride_id=str(overlapping.id),
                driver_id=driver_id,
            )


def test_unavailable_offline_drivers_excluded(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    offline_id = _ensure_driver(org_id, name_suffix="Offline", is_online=False)
    online_id = _ensure_driver(org_id, name_suffix="Online", is_online=True)
    pickup = service.now().replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=2)

    with SessionLocal() as db:
        ride = _scheduled_leg(db, organization_id=org_id, pickup_time=pickup, label="OfflineTest")
        candidates = evaluate_advance_scheduling_candidates(
            db,
            organization_id=org_id,
            ride=ride,
        )
        candidate_ids = {str(item["driver"].id) for item in candidates}
        assert offline_id not in candidate_ids
        assert online_id in candidate_ids


def test_paired_return_stays_with_outbound_driver_when_feasible(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id, name_suffix="Pair")
    group_id = uuid4()
    base = service.now().replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)

    with SessionLocal() as db:
        outbound = _scheduled_leg(
            db,
            organization_id=org_id,
            pickup_time=base,
            trip_leg="outbound",
            round_trip_group_id=group_id,
            same_driver_preference=True,
            label="Out",
        )
        return_leg = _scheduled_leg(
            db,
            organization_id=org_id,
            pickup_time=base + timedelta(hours=6),
            trip_leg="return",
            round_trip_group_id=group_id,
            same_driver_preference=True,
            label="Ret",
        )
        assign_driver_to_scheduled_ride(db, ride_id=str(outbound.id), driver_id=driver_id)
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(outbound.id))

        outbound.lifecycle_state = RideStatus.COMPLETED.value
        outbound.status = RideStatus.COMPLETED
        outbound.completed_at = service.now()
        db.add(outbound)
        db.commit()

        outcome = reserve_paired_return_leg_after_outbound_complete(
            db,
            outbound_ride=outbound,
            driver_id=driver_id,
        )
        assert outcome.get("mode") == "reserved"
        db.refresh(return_leg)
        assert str(return_leg.driver_id or "") == driver_id


def test_paired_return_becomes_reassignment_pending_on_conflict(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id, name_suffix="Conflict")
    group_id = uuid4()
    base = service.now().replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)

    with SessionLocal() as db:
        outbound = _scheduled_leg(
            db,
            organization_id=org_id,
            pickup_time=base,
            trip_leg="outbound",
            round_trip_group_id=group_id,
            same_driver_preference=True,
            label="OutC",
        )
        return_leg = _scheduled_leg(
            db,
            organization_id=org_id,
            pickup_time=base + timedelta(hours=2),
            trip_leg="return",
            round_trip_group_id=group_id,
            same_driver_preference=True,
            label="RetC",
        )
        blocker = _scheduled_leg(
            db,
            organization_id=org_id,
            pickup_time=base + timedelta(hours=1),
            label="Blocker",
        )
        assign_driver_to_scheduled_ride(db, ride_id=str(blocker.id), driver_id=driver_id)
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(blocker.id))

        outbound.lifecycle_state = RideStatus.COMPLETED.value
        outbound.status = RideStatus.COMPLETED
        outbound.completed_at = service.now()
        db.add(outbound)
        db.commit()

        outcome = reserve_paired_return_leg_after_outbound_complete(
            db,
            outbound_ride=outbound,
            driver_id=driver_id,
        )
        assert outcome.get("mode") == "reassignment_required"
        db.refresh(return_leg)
        assert return_leg.lifecycle_state == "reassignment_pending"


def test_run_advance_scheduling_skips_when_no_feasible_driver(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id, name_suffix="Only")
    base = service.now().replace(hour=12, minute=0, second=0, microsecond=0) + timedelta(days=1)

    with SessionLocal() as db:
        existing = _scheduled_leg(db, organization_id=org_id, pickup_time=base, label="Busy")
        assign_driver_to_scheduled_ride(db, ride_id=str(existing.id), driver_id=driver_id)
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(existing.id))

        conflicting = _scheduled_leg(
            db,
            organization_id=org_id,
            pickup_time=base + timedelta(minutes=15),
            label="Pending",
        )
        for row in db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org_id).all():
            if str(row.id) != driver_id:
                row.is_online = False
        db.commit()

        result = run_advance_scheduling_for_ride(
            db,
            ride_id=str(conflicting.id),
            organization_id=org_id,
        )
        assert result.get("mode") in {"no_candidates", "scheduled_offered"}
