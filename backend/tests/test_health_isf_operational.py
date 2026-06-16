"""Operational intelligence and reliability tests for Health ISF."""

from __future__ import annotations

import asyncio
from datetime import timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.helpers import now, uuid4
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    DriverStatus,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFOrganization,
    HealthISFRide,
    HealthISFWorkflowEscalation,
    HealthISFWorkflowIncident,
    RideStatus,
)
from app.modules.health_isf.operations import (
    get_operational_metrics_registry,
    build_operational_metrics,
    evaluate_operational_alerts,
)
from app.modules.health_isf.operational_replay_service import OperationalReplayService
from app.modules.health_isf.service import assign_driver_to_ride, get_admin_dispatch_alerts_data
from app.modules.health_isf.realtime import EventBroadcaster, WebSocketConnection
from app.modules.health_isf.realtime_service import RetryQueueService, IdempotencyService


@pytest.fixture
def db_session():
    import app.db.models  # noqa: F401 - register platform tables for foreign keys

    engine = create_engine("sqlite:///:memory:")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _seed_org(db_session):
    org = HealthISFOrganization(
        id=uuid4(),
        name="Test Org",
        code=f"TEST-{uuid4()[:8]}",
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


def test_operational_metrics_core_fields(db_session):
    org = _seed_org(db_session)

    driver = HealthISFDriver(
        id=uuid4(),
        organization_id=org.id,
        name="Driver One",
        phone="555-0001",
        vehicle_type="sedan",
        vehicle_plate="PLATE-1",
        status=DriverStatus.ASSIGNED,
    )
    ride = HealthISFRide(
        id=uuid4(),
        organization_id=org.id,
        passenger_name="Passenger One",
        passenger_phone="555-0101",
        pickup_address="A",
        dropoff_address="B",
        service_type="medical_transport",
        status=RideStatus.IN_TRANSIT,
        lifecycle_state="in_progress",
        requested_at=now() - timedelta(minutes=10),
        accepted_at=now() - timedelta(minutes=8),
    )

    db_session.add(driver)
    db_session.add(ride)
    db_session.commit()

    registry = get_operational_metrics_registry()
    registry.increment("dispatch.events.failed", 2)
    registry.increment("websocket.connections.active", 3)
    registry.record_event_ts("dispatch_events")

    metrics = build_operational_metrics(db_session, organization_id=org.id)
    assert metrics["active_rides"] >= 1
    assert metrics["driver_utilization_percent"] > 0
    assert metrics["failed_event_count"] >= 2
    assert "dispatch_throughput_per_minute" in metrics


def test_retry_queue_dead_letter_flow(db_session):
    org = _seed_org(db_session)
    retry = RetryQueueService.enqueue_failed_event(
        db_session,
        organization_id=org.id,
        event_type="ride_assigned",
        payload={"ride_id": "r1"},
        max_attempts=2,
    )

    RetryQueueService.mark_retry_failure(db_session, retry.id, "first failure")
    RetryQueueService.mark_retry_failure(db_session, retry.id, "second failure")

    stats = RetryQueueService.get_queue_stats(db_session, organization_id=org.id)
    assert stats["dead_letter"] >= 1
    assert stats["dead_letters_total"] >= 1


def test_idempotency_reservation(db_session):
    first = IdempotencyService.reserve_key(
        db_session,
        idempotency_key="evt:ride:1",
        scope="dispatch_event",
        resource_id="ride_1",
    )
    second = IdempotencyService.reserve_key(
        db_session,
        idempotency_key="evt:ride:1",
        scope="dispatch_event",
        resource_id="ride_1",
    )

    assert first is True
    assert second is False


def test_websocket_connection_throttling():
    async def _run():
        broadcaster = EventBroadcaster()
        broadcaster.max_connections_per_user = 1

        first = WebSocketConnection("c1", "user_1", "dispatcher")
        second = WebSocketConnection("c2", "user_1", "dispatcher")

        await broadcaster.register_connection(first, "org_1")

        with pytest.raises(ValueError):
            await broadcaster.register_connection(second, "org_1")

    asyncio.run(_run())


def test_websocket_batch_broadcast():
    async def _run():
        broadcaster = EventBroadcaster()
        conn = WebSocketConnection("c1", "user_1", "dispatcher")
        conn.subscribe("dispatcher_board")
        await broadcaster.register_connection(conn, "org_1")

        count = await broadcaster.broadcast_event_batch(
            events=[
                {"event_type": "ride_assigned", "payload": {"ride_id": "r1"}},
                {"event_type": "ride_completed", "payload": {"ride_id": "r1"}},
            ],
            organization_id="org_1",
            subscription_types=["dispatcher_board"],
        )

        assert count == 1
        msg = await asyncio.wait_for(conn.send_queue.get(), timeout=1.0)
        assert "event_batch" in msg

    asyncio.run(_run())


def test_operational_alert_detection(db_session):
    org = _seed_org(db_session)
    stale_ride = HealthISFRide(
        id=uuid4(),
        organization_id=org.id,
        passenger_name="Passenger Alert",
        passenger_phone="555-0102",
        pickup_address="C",
        dropoff_address="D",
        service_type="dialysis",
        status=RideStatus.PENDING,
        requested_at=now() - timedelta(minutes=30),
        updated_at=now() - timedelta(minutes=30),
    )
    db_session.add(stale_ride)
    db_session.commit()

    alerts = evaluate_operational_alerts(
        db_session,
        queue_stats={"failed": 12},
        websocket_stats={"disconnects_last_5m": 30},
        organization_id=org.id,
    )

    alert_types = {item["type"] for item in alerts}
    assert "unassigned_rides" in alert_types
    assert "failed_dispatch_events" in alert_types
    assert "websocket_disconnect_spike" in alert_types


def test_admin_dispatch_alerts_include_expired_assignment_and_driver_overload(db_session):
    org = _seed_org(db_session)
    driver = HealthISFDriver(
        id=uuid4(),
        organization_id=org.id,
        name="Driver Overload",
        phone="555-9911",
        vehicle_type="van",
        vehicle_plate=f"PLATE-{uuid4()[:6]}",
        status=DriverStatus.ASSIGNED,
    )
    db_session.add(driver)

    rides = []
    for idx in range(3):
        ride = HealthISFRide(
            id=uuid4(),
            organization_id=org.id,
            passenger_name=f"Passenger {idx}",
            passenger_phone=f"555-22{idx}",
            pickup_address="A",
            dropoff_address="B",
            service_type="medical_transport",
            status=RideStatus.ACCEPTED,
            driver_id=driver.id,
            requested_at=now() - timedelta(minutes=20),
            updated_at=now() - timedelta(minutes=10),
        )
        rides.append(ride)
        db_session.add(ride)

    expired_assignment = HealthISFDispatchAssignment(
        id=uuid4(),
        organization_id=org.id,
        ride_id=rides[0].id,
        driver_id=driver.id,
        assignment_state=DispatchAssignmentState.OFFERED.value,
        offered_at=now() - timedelta(minutes=10),
        offer_expires_at=now() - timedelta(minutes=1),
        expired_at=now() - timedelta(seconds=30),
    )
    db_session.add(expired_assignment)
    db_session.commit()

    payload = get_admin_dispatch_alerts_data(db_session, organization_id=org.id)
    alert_types = {item.get("alert_type") for item in payload.get("alerts", [])}

    assert "expired_assignment" in alert_types
    assert "driver_overload" in alert_types
    assert int(payload.get("counters", {}).get("expired_assignment", 0) or 0) >= 1
    assert int(payload.get("counters", {}).get("driver_overload", 0) or 0) >= 1


def test_assign_driver_to_ride_creates_current_assignment_and_suppresses_duplicates(db_session):
    org = _seed_org(db_session)
    stale_driver = HealthISFDriver(
        id=uuid4(),
        organization_id=org.id,
        name="Stale Driver",
        phone="555-7701",
        vehicle_type="sedan",
        vehicle_plate=f"STALE-{uuid4()[:5]}",
        status=DriverStatus.AVAILABLE,
    )
    assigned_driver = HealthISFDriver(
        id=uuid4(),
        organization_id=org.id,
        name="Assigned Driver",
        phone="555-7702",
        vehicle_type="sedan",
        vehicle_plate=f"LIVE-{uuid4()[:5]}",
        status=DriverStatus.AVAILABLE,
    )
    ride = HealthISFRide(
        id=uuid4(),
        organization_id=org.id,
        passenger_name="Continuity Patient",
        passenger_phone="555-7703",
        pickup_address="100 Continuity Way",
        dropoff_address="200 Continuity Way",
        service_type="medical_transport",
        status=RideStatus.PENDING,
        requested_at=now() - timedelta(minutes=5),
    )
    duplicate_one = HealthISFDispatchAssignment(
        id=uuid4(),
        organization_id=org.id,
        ride_id=ride.id,
        driver_id=stale_driver.id,
        assignment_state=DispatchAssignmentState.OFFERED.value,
        attempt_index=1,
        offered_at=now() - timedelta(minutes=4),
        offer_expires_at=now() + timedelta(minutes=1),
    )
    duplicate_two = HealthISFDispatchAssignment(
        id=uuid4(),
        organization_id=org.id,
        ride_id=ride.id,
        driver_id=stale_driver.id,
        assignment_state=DispatchAssignmentState.ASSIGNED.value,
        attempt_index=2,
        assigned_at=now() - timedelta(minutes=2),
    )
    db_session.add_all([stale_driver, assigned_driver, ride, duplicate_one, duplicate_two])
    db_session.commit()

    assigned_ride = assign_driver_to_ride(db_session, ride.id, assigned_driver.id)

    assert assigned_ride is not None
    assert str(assigned_ride.driver_id) == str(assigned_driver.id)

    rows = (
        db_session.query(HealthISFDispatchAssignment)
        .filter(HealthISFDispatchAssignment.ride_id == ride.id)
        .order_by(HealthISFDispatchAssignment.attempt_index.asc())
        .all()
    )
    active_rows = [
        row for row in rows
        if str(row.assignment_state) in {
            DispatchAssignmentState.OFFERED.value,
            DispatchAssignmentState.ASSIGNED.value,
            DispatchAssignmentState.ACCEPTED.value,
            DispatchAssignmentState.EN_ROUTE_PICKUP.value,
            DispatchAssignmentState.PICKUP_COMPLETE.value,
        }
    ]
    assert len(active_rows) == 1
    assert str(active_rows[0].driver_id) == str(assigned_driver.id)
    assert str(active_rows[0].assignment_state) in {
        DispatchAssignmentState.ASSIGNED.value,
        DispatchAssignmentState.OFFERED.value,
    }
    assert all(
        str(row.assignment_state) == DispatchAssignmentState.REASSIGNMENT_PENDING.value
        for row in rows
        if str(row.id) != str(active_rows[0].id)
    )


def test_admin_dispatch_alerts_detect_continuity_and_escalation_gaps(db_session):
    org = _seed_org(db_session)
    orphan_driver = HealthISFDriver(
        id=uuid4(),
        organization_id=org.id,
        name="Orphan Driver",
        phone="555-8801",
        vehicle_type="sedan",
        vehicle_plate=f"ORPH-{uuid4()[:5]}",
        status=DriverStatus.ASSIGNED,
    )
    duplicate_driver = HealthISFDriver(
        id=uuid4(),
        organization_id=org.id,
        name="Duplicate Driver",
        phone="555-8802",
        vehicle_type="van",
        vehicle_plate=f"DUP-{uuid4()[:5]}",
        status=DriverStatus.ASSIGNED,
    )
    ack_driver = HealthISFDriver(
        id=uuid4(),
        organization_id=org.id,
        name="Ack Driver",
        phone="555-8803",
        vehicle_type="sedan",
        vehicle_plate=f"ACK-{uuid4()[:5]}",
        status=DriverStatus.AVAILABLE,
    )
    orphaned_ride = HealthISFRide(
        id=uuid4(),
        organization_id=org.id,
        passenger_name="Orphaned Ride",
        passenger_phone="555-8804",
        pickup_address="10 Orphan St",
        dropoff_address="20 Orphan St",
        service_type="medical_transport",
        status=RideStatus.ASSIGNED,
        lifecycle_state=RideStatus.ASSIGNED.value,
        driver_id=orphan_driver.id,
        requested_at=now() - timedelta(minutes=25),
        updated_at=now() - timedelta(minutes=10),
    )
    duplicate_ride = HealthISFRide(
        id=uuid4(),
        organization_id=org.id,
        passenger_name="Duplicate Ride",
        passenger_phone="555-8805",
        pickup_address="30 Duplicate St",
        dropoff_address="40 Duplicate St",
        service_type="medical_transport",
        status=RideStatus.ACCEPTED,
        lifecycle_state=RideStatus.ASSIGNED.value,
        driver_id=duplicate_driver.id,
        requested_at=now() - timedelta(minutes=20),
        updated_at=now() - timedelta(minutes=5),
    )
    ack_timeout_ride = HealthISFRide(
        id=uuid4(),
        organization_id=org.id,
        passenger_name="Ack Timeout Ride",
        passenger_phone="555-8806",
        pickup_address="50 Ack St",
        dropoff_address="60 Ack St",
        service_type="medical_transport",
        status=RideStatus.PENDING,
        requested_at=now() - timedelta(minutes=15),
        updated_at=now() - timedelta(minutes=6),
    )
    accepted_without_continuity_ride = HealthISFRide(
        id=uuid4(),
        organization_id=org.id,
        passenger_name="Accepted Continuity Gap Ride",
        passenger_phone="555-8807",
        pickup_address="70 Gap St",
        dropoff_address="80 Gap St",
        service_type="medical_transport",
        status=RideStatus.ACCEPTED,
        lifecycle_state=RideStatus.ACCEPTED.value,
        accepted_at=now() - timedelta(minutes=18),
        requested_at=now() - timedelta(minutes=25),
        updated_at=now() - timedelta(minutes=12),
    )
    stalled_pickup_ride = HealthISFRide(
        id=uuid4(),
        organization_id=org.id,
        passenger_name="Stalled Pickup Ride",
        passenger_phone="555-8808",
        pickup_address="90 Stall St",
        dropoff_address="100 Stall St",
        service_type="medical_transport",
        status=RideStatus.ACCEPTED,
        lifecycle_state=RideStatus.DRIVER_EN_ROUTE.value,
        driver_id=ack_driver.id,
        accepted_at=now() - timedelta(minutes=35),
        requested_at=now() - timedelta(minutes=45),
        updated_at=now() - timedelta(minutes=30),
    )
    incident = HealthISFWorkflowIncident(
        id=uuid4(),
        organization_id=org.id,
        ride_id=duplicate_ride.id,
        incident_type="dispatch_loop",
        severity="high",
        summary="Escalation loop detected",
        created_at=now() - timedelta(minutes=25),
        updated_at=now() - timedelta(minutes=5),
    )
    db_session.add_all(
        [
            orphan_driver,
            duplicate_driver,
            ack_driver,
            orphaned_ride,
            duplicate_ride,
            ack_timeout_ride,
            accepted_without_continuity_ride,
            stalled_pickup_ride,
            incident,
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            HealthISFDispatchAssignment(
                id=uuid4(),
                organization_id=org.id,
                ride_id=duplicate_ride.id,
                driver_id=duplicate_driver.id,
                assignment_state=DispatchAssignmentState.OFFERED.value,
                attempt_index=1,
                offered_at=now() - timedelta(minutes=8),
                offer_expires_at=now() + timedelta(minutes=2),
                updated_at=now() - timedelta(minutes=8),
            ),
            HealthISFDispatchAssignment(
                id=uuid4(),
                organization_id=org.id,
                ride_id=duplicate_ride.id,
                driver_id=duplicate_driver.id,
                assignment_state=DispatchAssignmentState.ACCEPTED.value,
                attempt_index=2,
                accepted_at=now() - timedelta(minutes=7),
                updated_at=now() - timedelta(minutes=7),
            ),
            HealthISFDispatchAssignment(
                id=uuid4(),
                organization_id=org.id,
                ride_id=ack_timeout_ride.id,
                driver_id=ack_driver.id,
                assignment_state=DispatchAssignmentState.OFFERED.value,
                attempt_index=1,
                timeout_seconds=60,
                offered_at=now() - timedelta(minutes=4),
                offer_expires_at=now() + timedelta(minutes=4),
                updated_at=now() - timedelta(minutes=4),
            ),
            HealthISFDispatchAssignment(
                id=uuid4(),
                organization_id=org.id,
                ride_id=ack_timeout_ride.id,
                driver_id=ack_driver.id,
                assignment_state=DispatchAssignmentState.REASSIGNMENT_PENDING.value,
                attempt_index=2,
                reassignment_pending_at=now() - timedelta(minutes=22),
                updated_at=now() - timedelta(minutes=22),
            ),
            HealthISFDispatchAssignment(
                id=uuid4(),
                organization_id=org.id,
                ride_id=stalled_pickup_ride.id,
                driver_id=ack_driver.id,
                assignment_state=DispatchAssignmentState.ACCEPTED.value,
                attempt_index=1,
                assigned_at=now() - timedelta(minutes=32),
                accepted_at=now() - timedelta(minutes=30),
                updated_at=now() - timedelta(minutes=30),
            ),
            HealthISFWorkflowEscalation(
                id=uuid4(),
                organization_id=org.id,
                incident_id=incident.id,
                escalation_level=1,
                target_queue="dispatch-supervisor",
                target_role="supervisor",
                status="queued",
                summary="Initial escalation",
                created_at=now() - timedelta(minutes=20),
            ),
            HealthISFWorkflowEscalation(
                id=uuid4(),
                organization_id=org.id,
                incident_id=incident.id,
                escalation_level=2,
                target_queue="dispatch-supervisor",
                target_role="supervisor",
                status="queued",
                summary="Repeated escalation",
                created_at=now() - timedelta(minutes=10),
            ),
        ]
    )
    db_session.commit()

    payload = get_admin_dispatch_alerts_data(db_session, organization_id=org.id)
    alert_types = {item.get("alert_type") for item in payload.get("alerts", [])}

    assert "orphaned_ride" in alert_types
    assert "duplicate_active_assignment" in alert_types
    assert "driver_ack_timeout" in alert_types
    assert "assignment_pending_timeout" in alert_types
    assert "accepted_without_dispatch_continuity" in alert_types
    assert "stalled_pickup_transition" in alert_types
    assert "unresolved_escalation_loop" in alert_types
    assert int(payload.get("counters", {}).get("orphaned_ride", 0) or 0) >= 1
    assert int(payload.get("counters", {}).get("duplicate_active_assignment", 0) or 0) >= 1
    assert int(payload.get("counters", {}).get("driver_ack_timeout", 0) or 0) >= 1
    assert int(payload.get("counters", {}).get("assignment_pending_timeout", 0) or 0) >= 1
    assert int(payload.get("counters", {}).get("accepted_without_dispatch_continuity", 0) or 0) >= 1
    assert int(payload.get("counters", {}).get("stalled_pickup_transition", 0) or 0) >= 1
    assert int(payload.get("counters", {}).get("unresolved_escalation_loop", 0) or 0) >= 1
    assert all(getattr(item.get("created_at"), "tzinfo", None) is not None for item in payload.get("alerts", []))
    assert all(bool(item.get("replay_safe", False)) for item in payload.get("alerts", []))
    assert all(bool(item.get("replay_safe_key")) for item in payload.get("alerts", []))


def test_operational_replay_cursor_generated_at_is_utc_normalized():
    org_id = f"org-replay-utc-{uuid4()}"
    replay = OperationalReplayService.replay(organization_id=org_id, after_sequence=0, role="dispatcher")
    generated_at = str((replay.get("cursor") or {}).get("generated_at") or "")
    assert generated_at.endswith("+00:00")


def test_websocket_reconnect_resilience():
    async def _run():
        broadcaster = EventBroadcaster()
        conn = WebSocketConnection("c1", "user_1", "dispatcher")
        await broadcaster.register_connection(conn, "org_1")
        await broadcaster.unregister_connection("c1")

        reconnect = WebSocketConnection("c2", "user_1", "dispatcher")
        await broadcaster.register_connection(reconnect, "org_1")

        stats = broadcaster.get_websocket_health_stats("org_1")
        assert stats["active_connections"] == 1
        assert stats["disconnects_last_5m"] >= 1

    asyncio.run(_run())


def test_high_volume_dispatch_simulation():
    async def _run():
        broadcaster = EventBroadcaster()
        conn = WebSocketConnection("c1", "dispatcher_1", "dispatcher")
        conn.subscribe("dispatcher_board")
        await broadcaster.register_connection(conn, "org_1")

        total_events = 250
        for idx in range(total_events):
            await broadcaster.broadcast_event(
                event_type="ride_status_changed",
                payload={"ride_id": f"ride_{idx}", "to_status": "accepted"},
                organization_id="org_1",
                subscription_types=["dispatcher_board"],
            )

        queued = conn.send_queue.qsize()
        assert queued == total_events

    asyncio.run(_run())
