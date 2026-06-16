from __future__ import annotations

from app.helpers import uuid4
from app.modules.health_isf.models import (
    DriverStatus,
    HealthISFDriver,
    HealthISFOrganization,
    HealthISFProvider,
    HealthISFRide,
    HealthISFVehicle,
    RideStatus,
)


def _seed_org_provider_driver_vehicle(db):
    org = HealthISFOrganization(
        id=uuid4(),
        name="Phase54 Org",
        code=f"PH54-{str(uuid4())[:8]}",
        is_active=True,
    )
    db.add(org)

    provider = HealthISFProvider(
        id=uuid4(),
        organization_id=org.id,
        name="Phase54 Provider",
        address="100 Phase54 Way",
        phone="212-555-0100",
        service_type="clinic",
        is_active=True,
    )
    db.add(provider)

    vehicle = HealthISFVehicle(
        id=uuid4(),
        organization_id=org.id,
        vehicle_type="van",
        vehicle_plate=f"P54-{str(uuid4())[:6].upper()}",
        capacity=6,
        is_active=True,
    )
    db.add(vehicle)

    driver = HealthISFDriver(
        id=uuid4(),
        organization_id=org.id,
        name="Phase54 Driver",
        phone="212-555-0101",
        vehicle_type="van",
        vehicle_plate=f"DRV-{str(uuid4())[:6].upper()}",
        status=DriverStatus.AVAILABLE,
        is_active=True,
        rating=4.9,
    )
    db.add(driver)

    db.commit()
    return org, provider, driver, vehicle


def test_phase54_ride_can_be_created_without_vehicle_and_assigned_later(db):
    org, provider, driver, vehicle = _seed_org_provider_driver_vehicle(db)

    ride = HealthISFRide(
        id=uuid4(),
        organization_id=org.id,
        provider_id=provider.id,
        driver_id=driver.id,
        passenger_name="Phase54 Rider",
        passenger_phone="212-555-0199",
        pickup_address="100 Pickup Ave",
        dropoff_address="200 Dropoff Ave",
        service_type="medical_transport",
        status=RideStatus.PENDING,
    )
    db.add(ride)
    db.commit()
    db.refresh(ride)

    assert ride.vehicle_id is None

    ride.vehicle_id = vehicle.id
    db.commit()
    db.refresh(ride)

    assert ride.vehicle_id == vehicle.id

    fetched = db.get(HealthISFRide, ride.id)
    assert fetched is not None
    assert fetched.vehicle_id == vehicle.id
