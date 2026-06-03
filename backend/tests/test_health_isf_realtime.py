"""
Integration tests for real-time dispatch operations.
Tests WebSocket connections, event broadcasts, concurrent assignment protection, and dashboard synchronization.
"""

import asyncio
import json
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from typing import cast
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.modules.health_isf.models import (
    HealthISFRide, HealthISFDriver, RideStatus, DriverStatus,
    RealTimeEvent, DispatcherActivityLog, RideAssignmentLock,
    EventType, ActivityAction,
)
from app.modules.health_isf.realtime import (
    get_broadcaster, get_emitter, WebSocketConnection, EventBroadcaster, EventEmitter
)
from app.modules.health_isf.realtime_service import (
    RealTimeEventService, ActivityLogService, ConcurrentAssignmentService
)
from app.helpers import uuid4, now


class TestWebSocketConnection:
    """Test WebSocket connection management."""
    
    def test_connection_creation(self):
        """Test creating a WebSocket connection."""
        conn = WebSocketConnection("conn_1", "user_1", "dispatcher")
        assert conn.connection_id == "conn_1"
        assert conn.user_id == "user_1"
        assert conn.role == "dispatcher"
        assert len(conn.subscriptions) == 0
        assert conn.last_heartbeat is not None
    
    def test_subscribe_unsubscribe(self):
        """Test subscription management."""
        conn = WebSocketConnection("conn_1", "user_1", "dispatcher")
        
        conn.subscribe("dispatcher_board")
        assert "dispatcher_board" in conn.subscriptions
        
        conn.subscribe("ride_updates")
        assert len(conn.subscriptions) == 2
        
        conn.unsubscribe("dispatcher_board")
        assert "dispatcher_board" not in conn.subscriptions
        assert "ride_updates" in conn.subscriptions
    
    def test_is_stale(self):
        """Test stale connection detection."""
        conn = WebSocketConnection("conn_1", "user_1", "dispatcher")
        assert not conn.is_stale(timeout_seconds=300)
        
        # Manually set last_heartbeat to old time
        conn.last_heartbeat = datetime.utcnow() - timedelta(seconds=400)
        assert conn.is_stale(timeout_seconds=300)
    
    def test_update_heartbeat(self):
        """Test heartbeat update."""
        conn = WebSocketConnection("conn_1", "user_1", "dispatcher")
        old_heartbeat = conn.last_heartbeat
        
        asyncio.run(asyncio.sleep(0.01))  # Small delay
        conn.update_heartbeat()
        
        assert conn.last_heartbeat > old_heartbeat


@pytest.mark.asyncio
class TestEventBroadcaster:
    """Test event broadcaster functionality."""
    
    async def test_register_connection(self):
        """Test registering a connection."""
        broadcaster = EventBroadcaster()
        conn = WebSocketConnection("conn_1", "user_1", "dispatcher")
        
        await broadcaster.register_connection(conn, "org_1")
        
        assert "conn_1" in broadcaster.connections
        assert "org_1" in broadcaster.organization_connections
        assert "conn_1" in broadcaster.organization_connections["org_1"]
    
    async def test_unregister_connection(self):
        """Test unregistering a connection."""
        broadcaster = EventBroadcaster()
        conn = WebSocketConnection("conn_1", "user_1", "dispatcher")
        await broadcaster.register_connection(conn, "org_1")
        
        await broadcaster.unregister_connection("conn_1")
        
        assert "conn_1" not in broadcaster.connections
        assert "conn_1" not in broadcaster.organization_connections.get("org_1", set())
    
    async def test_broadcast_event(self):
        """Test broadcasting an event."""
        broadcaster = EventBroadcaster()
        conn1 = WebSocketConnection("conn_1", "user_1", "dispatcher")
        conn1.subscribe("dispatcher_board")
        conn2 = WebSocketConnection("conn_2", "user_2", "driver")
        conn2.subscribe("driver_dashboard")
        
        await broadcaster.register_connection(conn1, "org_1")
        await broadcaster.register_connection(conn2, "org_1")
        
        await broadcaster.broadcast_event(
            event_type="ride_assigned",
            payload={"ride_id": "ride_1", "driver_id": "driver_1"},
            organization_id="org_1",
            subscription_types=["dispatcher_board"],
        )
        
        # conn1 should receive the message
        message1 = await asyncio.wait_for(conn1.send_queue.get(), timeout=1.0)
        assert "ride_assigned" in message1
        
        # conn2 should not receive the message (different subscription)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(conn2.send_queue.get(), timeout=0.1)
    
    async def test_cleanup_stale_connections(self):
        """Test cleaning up stale connections."""
        broadcaster = EventBroadcaster()
        conn1 = WebSocketConnection("conn_1", "user_1", "dispatcher")
        conn2 = WebSocketConnection("conn_2", "user_2", "driver")
        
        await broadcaster.register_connection(conn1, "org_1")
        await broadcaster.register_connection(conn2, "org_1")
        
        # Make conn1 stale
        conn1.last_heartbeat = datetime.utcnow() - timedelta(seconds=400)
        
        await broadcaster.cleanup_stale_connections(timeout_seconds=300)
        
        assert "conn_1" not in broadcaster.connections
        assert "conn_2" in broadcaster.connections


@pytest.mark.asyncio
class TestEventEmitter:
    """Test event emitter functionality."""
    
    async def test_emit_ride_status_changed(self):
        """Test emitting ride status changed event."""
        broadcaster = EventBroadcaster()
        emitter = EventEmitter(broadcaster)
        conn = WebSocketConnection("conn_1", "user_1", "dispatcher")
        conn.subscribe("dispatcher_board")
        
        await broadcaster.register_connection(conn, "org_1")
        
        await emitter.emit_ride_status_changed(
            organization_id="org_1",
            ride_id="ride_1",
            from_status="pending",
            to_status="accepted",
            actor_user_id="user_1",
        )
        
        message = await asyncio.wait_for(conn.send_queue.get(), timeout=1.0)
        data = json.loads(message)
        assert data["event_type"] == "ride_status_changed"
        assert data["payload"]["ride_id"] == "ride_1"
        assert data["payload"]["to_status"] == "accepted"
    
    async def test_emit_ride_assigned(self):
        """Test emitting ride assigned event."""
        broadcaster = EventBroadcaster()
        emitter = EventEmitter(broadcaster)
        conn = WebSocketConnection("conn_1", "user_1", "dispatcher")
        conn.subscribe("dispatcher_board")
        
        await broadcaster.register_connection(conn, "org_1")
        
        await emitter.emit_ride_assigned(
            organization_id="org_1",
            ride_id="ride_1",
            driver_id="driver_1",
            driver_name="John Doe",
            actor_user_id="user_1",
        )
        
        message = await asyncio.wait_for(conn.send_queue.get(), timeout=1.0)
        data = json.loads(message)
        assert data["event_type"] == "ride_assigned"
        assert data["payload"]["ride_id"] == "ride_1"
        assert data["payload"]["driver_id"] == "driver_1"


class TestRealTimeEventService:
    """Test real-time event service."""
    
    def test_log_event(self, db: Session):
        """Test logging a real-time event."""
        event = RealTimeEventService.log_event(
            db,
            organization_id="org_1",
            event_type=EventType.RIDE_ASSIGNED,
            payload={"ride_id": "ride_1", "driver_id": "driver_1"},
            ride_id="ride_1",
            driver_id="driver_1",
        )
        
        assert event.id is not None
        assert event.event_type == EventType.RIDE_ASSIGNED
        assert event.ride_id == "ride_1"
        
        # Verify persisted
        persisted = db.query(RealTimeEvent).filter(
            RealTimeEvent.id == event.id
        ).first()
        assert persisted is not None
    
    def test_get_recent_events(self, db: Session):
        """Test retrieving recent events."""
        # Log multiple events
        for i in range(3):
            RealTimeEventService.log_event(
                db,
                organization_id="org_1",
                event_type=EventType.RIDE_STATUS_CHANGED,
                payload={"ride_id": f"ride_{i}"},
                ride_id=f"ride_{i}",
            )
        
        # Get recent events
        events = RealTimeEventService.get_recent_events(
            db, organization_id="org_1", limit=10, minutes=60
        )
        
        assert len(events) == 3


class TestActivityLogService:
    """Test activity log service."""
    
    def test_log_activity(self, db: Session):
        """Test logging dispatcher activity."""
        activity = ActivityLogService.log_activity(
            db,
            organization_id="org_1",
            action=ActivityAction.RIDE_ASSIGNED,
            description="Ride assigned to driver",
            ride_id="ride_1",
            driver_id="driver_1",
            actor_user_id="user_1",
        )
        
        assert activity.id is not None
        assert activity.action == ActivityAction.RIDE_ASSIGNED
        assert activity.ride_id == "ride_1"
        
        # Verify persisted
        persisted = db.query(DispatcherActivityLog).filter(
            DispatcherActivityLog.id == activity.id
        ).first()
        assert persisted is not None
    
    def test_get_activity_feed(self, db: Session):
        """Test retrieving activity feed."""
        # Log multiple activities
        for i in range(5):
            ActivityLogService.log_activity(
                db,
                organization_id="org_1",
                action=ActivityAction.RIDE_ASSIGNED,
                description=f"Activity {i}",
            )
        
        # Get feed
        activities, total = ActivityLogService.get_activity_feed(
            db, organization_id="org_1", limit=10, skip=0
        )
        
        assert len(activities) == 5
        assert total == 5


class TestConcurrentAssignmentService:
    """Test concurrent assignment protection."""
    
    def test_acquire_assignment_lock(self, db: Session):
        """Test acquiring an assignment lock."""
        lock = ConcurrentAssignmentService.acquire_assignment_lock(
            db,
            ride_id="ride_1",
            user_id="user_1",
            lock_duration_seconds=30,
        )
        
        assert lock is not None
        assert lock.ride_id == "ride_1"
        assert lock.locked_by_user_id == "user_1"
    
    def test_acquire_existing_lock_fails(self, db: Session):
        """Test that acquiring a second lock fails."""
        # Acquire first lock
        lock1 = ConcurrentAssignmentService.acquire_assignment_lock(
            db, ride_id="ride_1", user_id="user_1", lock_duration_seconds=30
        )
        assert lock1 is not None
        
        # Try to acquire second lock
        lock2 = ConcurrentAssignmentService.acquire_assignment_lock(
            db, ride_id="ride_1", user_id="user_2", lock_duration_seconds=30
        )
        assert lock2 is None
    
    def test_release_assignment_lock(self, db: Session):
        """Test releasing an assignment lock."""
        # Acquire lock
        ConcurrentAssignmentService.acquire_assignment_lock(
            db, ride_id="ride_1", user_id="user_1", lock_duration_seconds=30
        )
        
        # Release lock
        released = ConcurrentAssignmentService.release_assignment_lock(
            db, ride_id="ride_1"
        )
        assert released
        
        # Verify lock is gone
        has_lock = ConcurrentAssignmentService.has_assignment_lock(db, "ride_1")
        assert not has_lock
    
    def test_has_assignment_lock(self, db: Session):
        """Test checking for assignment lock."""
        ride_id = "ride_1"
        
        # Should be no lock
        assert not ConcurrentAssignmentService.has_assignment_lock(db, ride_id)
        
        # Acquire lock
        ConcurrentAssignmentService.acquire_assignment_lock(
            db, ride_id=ride_id, user_id="user_1", lock_duration_seconds=30
        )
        
        # Should have lock
        assert ConcurrentAssignmentService.has_assignment_lock(db, ride_id)
    
    def test_validate_ride_version(self, db: Session, sample_ride):
        """Test validating ride version."""
        ride_id = sample_ride.id
        version = sample_ride.version
        
        # Should match
        assert ConcurrentAssignmentService.validate_ride_version(
            db, ride_id, version
        )
        
        # Increment version
        ConcurrentAssignmentService.increment_ride_version(db, ride_id)
        
        # Old version should not match
        assert not ConcurrentAssignmentService.validate_ride_version(
            db, ride_id, version
        )
    
    def test_increment_ride_version(self, db: Session, sample_ride):
        """Test incrementing ride version."""
        ride_id = sample_ride.id
        old_version = sample_ride.version
        
        new_version = ConcurrentAssignmentService.increment_ride_version(
            db, ride_id
        )
        
        assert new_version == old_version + 1

    def test_cleanup_expired_locks_skips_during_cooldown(self, monkeypatch: pytest.MonkeyPatch):
        """Test repeated cleanup attempts are throttled to reduce writer contention."""

        class _FakeDB:
            def __init__(self):
                self.execute_calls = 0

            def execute(self, *_args, **_kwargs):
                self.execute_calls += 1
                return type("Result", (), {"rowcount": 0})()

            def commit(self):
                return None

            def rollback(self):
                return None

        monkeypatch.setattr(ConcurrentAssignmentService, "_cleanup_cooldown_seconds", 60.0)
        monkeypatch.setattr(ConcurrentAssignmentService, "_last_cleanup_attempt_monotonic", 0.0)

        fake_db = _FakeDB()
        first = ConcurrentAssignmentService.cleanup_expired_locks(cast(Session, fake_db))
        second = ConcurrentAssignmentService.cleanup_expired_locks(cast(Session, fake_db))

        assert first == 0
        assert second == 0
        assert fake_db.execute_calls == 1

    def test_cleanup_expired_locks_returns_zero_on_sqlite_lock(self, monkeypatch: pytest.MonkeyPatch):
        """Test cleanup failure stays isolated under SQLite write contention."""

        class _FakeDB:
            def __init__(self):
                self.rollback_calls = 0

            def execute(self, *_args, **_kwargs):
                raise OperationalError("DELETE FROM health_isf_assignment_locks", {}, Exception("database is locked"))

            def commit(self):
                return None

            def rollback(self):
                self.rollback_calls += 1

        monkeypatch.setattr(ConcurrentAssignmentService, "_cleanup_cooldown_seconds", 0.0)
        monkeypatch.setattr(ConcurrentAssignmentService, "_last_cleanup_attempt_monotonic", 0.0)

        fake_db = _FakeDB()
        cleaned = ConcurrentAssignmentService.cleanup_expired_locks(cast(Session, fake_db))

        assert cleaned == 0
        assert fake_db.rollback_calls == 1

    def test_force_cleanup_expired_locks_bypasses_cooldown(self, monkeypatch: pytest.MonkeyPatch):
        """Test manual maintenance cleanup still executes during cooldown."""

        class _FakeDB:
            def __init__(self):
                self.execute_calls = 0

            def execute(self, *_args, **_kwargs):
                self.execute_calls += 1
                return type("Result", (), {"rowcount": 2})()

            def commit(self):
                return None

            def rollback(self):
                return None

        monkeypatch.setattr(ConcurrentAssignmentService, "_cleanup_cooldown_seconds", 300.0)
        monkeypatch.setattr(ConcurrentAssignmentService, "_last_cleanup_attempt_monotonic", 0.0)

        fake_db = _FakeDB()
        assert ConcurrentAssignmentService.cleanup_expired_locks(cast(Session, fake_db)) == 2
        assert ConcurrentAssignmentService.force_cleanup_expired_locks(cast(Session, fake_db)) == 2
        assert fake_db.execute_calls == 2


class TestDashboardSynchronization:
    """Test dashboard real-time synchronization."""
    
    @pytest.mark.asyncio
    async def test_dispatcher_board_sync(self):
        """Test dispatcher board real-time synchronization."""
        broadcaster = EventBroadcaster()
        emitter = EventEmitter(broadcaster)
        
        # Connect dispatcher
        dispatcher_conn = WebSocketConnection("disp_1", "disp_user", "dispatcher")
        dispatcher_conn.subscribe("dispatcher_board")
        await broadcaster.register_connection(dispatcher_conn, "org_1")
        
        # Connect another dispatcher
        dispatcher_conn2 = WebSocketConnection("disp_2", "disp_user2", "dispatcher")
        dispatcher_conn2.subscribe("dispatcher_board")
        await broadcaster.register_connection(dispatcher_conn2, "org_1")
        
        # Emit ride status change
        await emitter.emit_ride_status_changed(
            organization_id="org_1",
            ride_id="ride_1",
            from_status="pending",
            to_status="assigned",
        )
        
        # Both dispatchers should receive event
        msg1 = await asyncio.wait_for(dispatcher_conn.send_queue.get(), timeout=1.0)
        msg2 = await asyncio.wait_for(dispatcher_conn2.send_queue.get(), timeout=1.0)
        
        assert "ride_status_changed" in msg1
        assert "ride_status_changed" in msg2
    
    @pytest.mark.asyncio
    async def test_driver_dashboard_sync(self):
        """Test driver dashboard real-time synchronization."""
        broadcaster = EventBroadcaster()
        emitter = EventEmitter(broadcaster)
        
        # Connect driver
        driver_conn = WebSocketConnection("driver_1", "driver_user", "driver")
        driver_conn.subscribe("driver_dashboard")
        await broadcaster.register_connection(driver_conn, "org_1")
        
        # Emit driver status change
        await emitter.emit_driver_status_changed(
            organization_id="org_1",
            driver_id="driver_1",
            from_status="available",
            to_status="assigned",
        )
        
        # Driver should receive event
        msg = await asyncio.wait_for(driver_conn.send_queue.get(), timeout=1.0)
        data = json.loads(msg)
        assert data["event_type"] == "driver_status_changed"


# Fixtures for integration tests

@pytest.fixture
def sample_ride(db: Session, sample_organization):
    """Create a sample ride for testing."""
    ride = HealthISFRide(
        id=uuid4(),
        organization_id=sample_organization.id,
        passenger_name="Test Passenger",
        passenger_phone="555-0100",
        pickup_address="123 Main St",
        dropoff_address="456 Oak Ave",
        service_type="medical_transport",
        status=RideStatus.PENDING,
        version=0,
    )
    db.add(ride)
    db.commit()
    db.refresh(ride)
    return ride


@pytest.fixture
def sample_driver(db: Session, sample_organization):
    """Create a sample driver for testing."""
    driver = HealthISFDriver(
        id=uuid4(),
        organization_id=sample_organization.id,
        name="Test Driver",
        phone="555-0101",
        vehicle_type="sedan",
        vehicle_plate="TEST-001",
        status=DriverStatus.AVAILABLE,
        version=0,
    )
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


@pytest.fixture
def sample_organization(db: Session):
    """Create a sample organization for testing."""
    from app.modules.health_isf.models import HealthISFOrganization
    
    org = HealthISFOrganization(
        id=uuid4(),
        name="Test Organization",
        code="TEST-ORG",
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org
