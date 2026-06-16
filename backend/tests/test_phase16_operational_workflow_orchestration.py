from __future__ import annotations

from app.helpers import now, uuid4
from app.modules.health_isf.models import (
    DriverStatus,
    HealthISFDriver,
    HealthISFOrganization,
    HealthISFProvider,
    HealthISFRide,
    RideStatus,
)
from app.modules.health_isf.operational_workflow_orchestration import (
    build_assistant_operational_awareness,
    build_operational_workflow_overview,
    build_workflow_event_stream,
    publish_phase16_operational_event,
    record_phase16_workflow_event_audit,
)


def _seed_basic_operational_entities(db):
    org = HealthISFOrganization(
        id=uuid4(),
        name="Phase16 Org",
        code=f"phase16-{uuid4()[:8]}",
        is_active=True,
    )
    db.add(org)
    db.flush()

    provider = HealthISFProvider(
        id=uuid4(),
        organization_id=org.id,
        name="Provider One",
        address="100 Main",
        phone="+15550000001",
        service_type="clinic",
        is_active=True,
    )
    db.add(provider)

    driver = HealthISFDriver(
        id=uuid4(),
        organization_id=org.id,
        name="Driver One",
        phone="+15550000002",
        vehicle_type="sedan",
        vehicle_plate=f"P16-{uuid4()[:6]}",
        status=DriverStatus.AVAILABLE,
        is_active=True,
    )
    db.add(driver)
    db.flush()

    rides = [
        HealthISFRide(
            id=uuid4(),
            organization_id=org.id,
            provider_id=provider.id,
            driver_id=None,
            passenger_name="Passenger A",
            passenger_phone="+15550000003",
            pickup_address="A",
            dropoff_address="B",
            service_type="medical_transport",
            status=RideStatus.PENDING,
            lifecycle_state=RideStatus.QUEUED.value,
            requested_at=now(),
            updated_at=now(),
        ),
        HealthISFRide(
            id=uuid4(),
            organization_id=org.id,
            provider_id=provider.id,
            driver_id=driver.id,
            passenger_name="Passenger B",
            passenger_phone="+15550000004",
            pickup_address="C",
            dropoff_address="D",
            service_type="medical_transport",
            status=RideStatus.IN_TRANSIT,
            lifecycle_state=RideStatus.IN_PROGRESS.value,
            requested_at=now(),
            updated_at=now(),
        ),
    ]
    db.add_all(rides)
    db.commit()
    return org


def test_phase16_overview_preserves_execution_disabled_defaults(db):
    org = _seed_basic_operational_entities(db)

    overview = build_operational_workflow_overview(db, organization_id=org.id)

    safety = overview["unified_workflow_orchestration_layer"]
    assert safety["execution_disabled_by_default"] is True
    assert safety["autonomous_execution"] is False
    assert safety["automatic_dispatching"] is False
    assert safety["self_triggering_workflows"] is False

    lifecycle_counts = overview["ride_lifecycle_engine"]["state_counts"]
    assert lifecycle_counts["REQUESTED"] >= 1
    assert lifecycle_counts["IN_PROGRESS"] >= 1


def test_phase16_assistant_operational_awareness_active_rides(db):
    org = _seed_basic_operational_entities(db)

    awareness = build_assistant_operational_awareness(
        db,
        organization_id=org.id,
        prompt="Show active rides",
        role="admin",
    )

    assert awareness["preview_only"] is True
    assert awareness["read_only"] is True
    assert awareness["focus"]["query"] == "active_rides"
    assert awareness["focus"]["count"] >= 1


def test_phase16_event_stream_append_only_and_audit_linkage(db):
    org = _seed_basic_operational_entities(db)

    correlation_id = f"corr-{uuid4()}"
    publish_phase16_operational_event(
        organization_id=org.id,
        event_name="workflow_transition",
        payload={"ride_id": "r1", "transition": "REQUESTED->ASSIGNED"},
        correlation_id=correlation_id,
        role_scope=["dispatcher", "admin"],
    )
    record_phase16_workflow_event_audit(
        db,
        organization_id=org.id,
        event_name="workflow_transition",
        actor_user_id=None,
        correlation_id=correlation_id,
        payload={"ride_id": "r1"},
    )
    db.commit()

    stream = build_workflow_event_stream(db, organization_id=org.id, after_sequence=0, limit=50)

    assert stream["append_only"] is True
    assert stream["audit_chain_compatible"] is True
    assert stream["event_bus"]["latest_sequence"] >= 1
    assert stream["correlation_coverage"]["total"] >= 1
