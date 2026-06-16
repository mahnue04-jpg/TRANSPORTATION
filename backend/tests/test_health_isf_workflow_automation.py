from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import Base, SessionLocal
from app.db.models import User as PlatformUser
from app.helpers import now, uuid4
from app.main import app
from app.modules.health_isf import service
from app.modules.health_isf.models import (
    DriverStatus,
    DispatchDeadLetterEvent,
    DispatchEventRetry,
    HealthISFDriver,
    HealthISFOrganization,
    HealthISFProvider,
    HealthISFRide,
    HealthISFWorkflowExecution,
    HealthISFWorkflowIncident,
    HealthISFWorkflowEscalation,
    RideStatus,
)
from app.modules.health_isf.realtime import EventBroadcaster, EventEmitter, WebSocketConnection
from app.modules.health_isf.workflow_engine import WorkflowOrchestrationService
from app.modules.health_isf.realtime_service import RetryQueueService


@pytest.fixture
def db_session():
    import app.db.models  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _seed_bundle(db_session):
    org = HealthISFOrganization(
        id=uuid4(),
        name="Workflow Org",
        code=f"WF-{uuid4()[:8]}",
        is_active=True,
    )
    provider = HealthISFProvider(
        id=uuid4(),
        organization_id=org.id,
        name="Workflow Provider",
        address="100 Ops Ave",
        phone="555-1000",
        service_type="clinic",
        is_active=True,
    )
    driver = HealthISFDriver(
        id=uuid4(),
        organization_id=org.id,
        name="Workflow Driver",
        phone="555-1001",
        vehicle_type="van",
        vehicle_plate="WF-1001",
        status=DriverStatus.AVAILABLE,
        is_active=True,
        total_trips=1,
        rating=4.9,
    )
    db_session.add_all([org, provider, driver])
    db_session.commit()
    ride = service.create_ride(
        db=db_session,
        passenger_name="Workflow Passenger",
        passenger_phone="555-1002",
        pickup_address="1 Main St",
        dropoff_address="2 Main St",
        service_type="medical_transport",
        provider_id=provider.id,
        notes="workflow test",
        actor_user_id=None,
    )
    return org, provider, driver, ride


def _get_dispatcher_org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
        assert user is not None
        assert user.organization_id is not None
        return user.organization_id


def _seed_app_bundle(organization_id: str):
    with SessionLocal() as db:
        org = db.query(HealthISFOrganization).filter(HealthISFOrganization.id == organization_id).first()
        if org is None:
            org = HealthISFOrganization(
                id=organization_id,
                name="Amicor Health ISF",
                code=f"AMICOR-{organization_id[:8]}",
                is_active=True,
            )
            db.add(org)
            db.flush()

        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=org.id,
            name=f"Workflow Provider {uuid4()[:8]}",
            address="100 Ops Ave",
            phone="555-2000",
            service_type="clinic",
            is_active=True,
        )
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org.id,
            name=f"Workflow Driver {uuid4()[:8]}",
            phone=f"555-{uuid4()[:4]}",
            vehicle_type="van",
            vehicle_plate=f"WF-{uuid4()[:6].upper()}",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            total_trips=1,
            rating=4.8,
        )
        db.add_all([provider, driver])
        db.flush()
        ride = service.create_ride(
            db=db,
            passenger_name=f"Workflow Passenger {uuid4()[:8]}",
            passenger_phone="555-2002",
            pickup_address="1 Main St",
            dropoff_address="2 Main St",
            service_type="medical_transport",
            provider_id=provider.id,
            notes="workflow api test",
            actor_user_id=None,
        )
        db.commit()
        return org.id, provider.id, driver.id, ride.id


def test_workflow_reassign_executes_and_broadcasts(db_session):
    org, _, driver, ride = _seed_bundle(db_session)
    broadcaster = EventBroadcaster()
    connection = WebSocketConnection("wf-conn", "dispatcher-1", "dispatcher")
    connection.subscribe("workflow_events")

    async def _run():
        await broadcaster.register_connection(connection, org.id)
        with patch("app.modules.health_isf.workflow_engine.get_broadcaster", return_value=broadcaster):
            response = await WorkflowOrchestrationService.run_reassign(
                db_session,
                organization_id=org.id,
                ride_id=ride.id,
                actor_user_id=None,
                driver_id=driver.id,
                suggest_only=False,
            )

        assert response["execution"]["status"] == "succeeded"
        assert db_session.query(HealthISFWorkflowExecution).count() >= 1
        message = await asyncio.wait_for(connection.send_queue.get(), timeout=1.0)
        assert "workflow_reassignment_executed" in message

    asyncio.run(_run())


def test_workflow_recovery_creates_incident_and_escalation(db_session):
    org, _, _, ride = _seed_bundle(db_session)
    ride.status = RideStatus.ACCEPTED
    ride.updated_at = now() - timedelta(minutes=90)
    db_session.commit()

    async def _run():
        response = await WorkflowOrchestrationService.run_recovery(
            db_session,
            organization_id=org.id,
            ride_id=ride.id,
            actor_user_id=None,
            dry_run=True,
        )
        assert response["incidents"]
        assert response["escalations"]
        assert db_session.query(HealthISFWorkflowIncident).count() >= 1
        assert db_session.query(HealthISFWorkflowEscalation).count() >= 1

    asyncio.run(_run())


def test_workflow_replay_endpoint_processes_dead_letters(client, db_session):
    payload = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {payload['access_token']}"}
    org_id = _get_dispatcher_org_id()
    with SessionLocal() as app_db:
        app_db.query(DispatchDeadLetterEvent).filter(DispatchDeadLetterEvent.organization_id == org_id).delete(synchronize_session=False)
        app_db.query(DispatchEventRetry).filter(DispatchEventRetry.organization_id == org_id).delete(synchronize_session=False)
        app_db.commit()

        org = app_db.query(HealthISFOrganization).filter(HealthISFOrganization.id == org_id).first()
        assert org is not None
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=org.id,
            name=f"Workflow Provider {uuid4()[:8]}",
            address="100 Ops Ave",
            phone="555-2000",
            service_type="clinic",
            is_active=True,
        )
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org.id,
            name=f"Workflow Driver {uuid4()[:8]}",
            phone=f"555-{uuid4()[:4]}",
            vehicle_type="van",
            vehicle_plate=f"WF-{uuid4()[:6].upper()}",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            total_trips=1,
            rating=4.8,
        )
        app_db.add_all([provider, driver])
        app_db.flush()
        ride = service.create_ride(
            db=app_db,
            passenger_name=f"Workflow Passenger {uuid4()[:8]}",
            passenger_phone="555-2002",
            pickup_address="1 Main St",
            dropoff_address="2 Main St",
            service_type="medical_transport",
            provider_id=provider.id,
            notes="workflow replay test",
            actor_user_id=None,
        )
        retry_event = RetryQueueService.enqueue_failed_event(
            app_db,
            organization_id=org.id,
            event_type="ride_assigned",
            payload={"ride_id": ride.id, "driver_id": driver.id},
            error_message="dead letter for replay",
            idempotency_key=f"dead:{uuid4()}",
            max_attempts=2,
            ride_id=ride.id,
            driver_id=driver.id,
        )
        RetryQueueService.mark_retry_failure(app_db, retry_event.id, "first replay failure")
        RetryQueueService.mark_retry_failure(app_db, retry_event.id, "second replay failure")
        app_db.commit()

    response = client.post(
        "/api/health-isf/workflows/replay",
        headers=headers,
        json={"organization_id": org_id, "limit": 5},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["execution"]["status"] == "replayed"
    assert body["recommendations"]


def test_workflow_escalation_endpoint_routes_incident(client, db_session):
    payload = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {payload['access_token']}"}
    org_id = _get_dispatcher_org_id()
    _, _, _, ride_id = _seed_app_bundle(org_id)

    recovery_response = client.post(
        "/api/health-isf/workflows/recover",
        headers=headers,
        json={"organization_id": org_id, "ride_id": ride_id, "dry_run": True},
    )
    assert recovery_response.status_code == 200, recovery_response.text
    incident_id = recovery_response.json()["incidents"][0]["id"]

    response = client.post(
        "/api/health-isf/workflows/escalate",
        headers=headers,
        json={"organization_id": org_id, "incident_id": incident_id, "summary": "Dispatch review needed"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["execution"]["status"] == "escalated"
    assert body["escalations"]