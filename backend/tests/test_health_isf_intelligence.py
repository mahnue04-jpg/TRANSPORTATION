"""Operational intelligence tests for Health ISF."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import Base
from app.helpers import now, uuid4
from app.main import app
from app.modules.health_isf.intelligence import OperationalIntelligenceService
from app.modules.health_isf.models import (
    DriverStatus,
    HealthISFDriver,
    HealthISFOrganization,
    HealthISFProvider,
    HealthISFRide,
    RideStatus,
)
from app.modules.health_isf.realtime import EventBroadcaster, WebSocketConnection


@pytest.fixture
def db_session():

    engine = create_engine("sqlite:///:memory:")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _seed_org(db_session): # type: ignore
    org = HealthISFOrganization(
        id=uuid4(),
        name="Intelligence Org",
        code=f"INT-{uuid4()[:8]}",
        is_active=True,
    )
    db_session.add(org) # type: ignore
    db_session.commit() # type: ignore
    db_session.refresh(org) # type: ignore
    return org


def _seed_intelligence_data(db_session): # type: ignore
    org = _seed_org(db_session) # type: ignore
    provider = HealthISFProvider(
        id=uuid4(),
        organization_id=org.id,
        name="Alpha Provider",
        address="100 Market St, Boston, MA 02110",
        phone="555-1111",
        service_type="medical_transport",
        is_active=True,
    )
    driver = HealthISFDriver(
        id=uuid4(),
        organization_id=org.id,
        name="Driver Alpha",
        phone="555-2222",
        vehicle_type="van",
        vehicle_plate="AAA-111",
        status=DriverStatus.AVAILABLE,
        total_trips=42,
        rating=4.9,
    )
    ride = HealthISFRide(
        id=uuid4(),
        organization_id=org.id,
        provider_id=provider.id,
        passenger_name="Passenger Alpha",
        passenger_phone="555-3333",
        pickup_address="100 Market St, Boston, MA 02110",
        dropoff_address="200 State St, Boston, MA 02109",
        service_type="medical_transport",
        status=RideStatus.PENDING,
        requested_at=now() - timedelta(minutes=35),
        updated_at=now() - timedelta(minutes=35),
    )
    stuck_ride = HealthISFRide(
        id=uuid4(),
        organization_id=org.id,
        provider_id=provider.id,
        passenger_name="Passenger Stuck",
        passenger_phone="555-4444",
        pickup_address="300 Market St, Boston, MA 02110",
        dropoff_address="400 State St, Boston, MA 02109",
        service_type="medical_transport",
        status=RideStatus.ACCEPTED,
        requested_at=now() - timedelta(minutes=70),
        accepted_at=now() - timedelta(minutes=60),
        updated_at=now() - timedelta(minutes=60),
    )
    db_session.add_all([provider, driver, ride, stuck_ride]) # type: ignore
    for idx in range(10):
        db_session.add( # type: ignore
            HealthISFRide(
                id=uuid4(),
                organization_id=org.id,
                provider_id=provider.id,
                passenger_name=f"Cancelled {idx}",
                passenger_phone=f"555-6{idx:03d}",
                pickup_address="10 Market St, Boston, MA 02110",
                dropoff_address="20 State St, Boston, MA 02109",
                service_type="medical_transport",
                status=RideStatus.CANCELLED,
                requested_at=now() - timedelta(minutes=55),
                updated_at=now() - timedelta(minutes=2),
            )
        )
    db_session.commit() # type: ignore
    return org, provider, driver, ride


@pytest.fixture(scope="module")
def client():
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict: # type: ignore
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_recommendation_engine_scores_driver_and_provider(db_session): # type: ignore
    org, provider, driver, ride = _seed_intelligence_data(db_session) # type: ignore

    payload = OperationalIntelligenceService.build_recommendations(
        db_session, # type: ignore
        organization_id=org.id,
        ride_id=ride.id,
    )

    assert payload["organization_id"] == org.id
    assert payload["recommendations"]
    top = payload["recommendations"][0]
    assert top["score"] >= 0.0
    assert top["confidence"] >= 0.0
    assert top["explanation"]
    assert payload["dispatcher_recommendation_payloads"]
    assert payload["automated_actions"]


def test_anomaly_detection_and_risk_scoring(db_session): # type: ignore
    org, _, _, _ = _seed_intelligence_data(db_session) # type: ignore

    anomalies = OperationalIntelligenceService.detect_anomalies(db_session, organization_id=org.id) # type: ignore
    anomaly_types = {item["type"] for item in anomalies}
    assert "stuck_rides" in anomaly_types
    assert "delayed_pickups" in anomaly_types
    assert "cancellation_spike" in anomaly_types
    assert "delayed_route_progression" in anomaly_types
    assert "assignment_starvation" in anomaly_types

    risk = OperationalIntelligenceService.build_risk_profile(db_session, organization_id=org.id, anomalies=anomalies) # type: ignore
    assert risk["risk_score"] >= 0.0
    assert risk["operational_health_score"] <= 100.0
    assert risk["trend_explanations"]


def test_intelligence_websocket_broadcasts_payloads(db_session): # type: ignore
    org, _, _, ride = _seed_intelligence_data(db_session) # type: ignore
    broadcaster = EventBroadcaster()
    connection = WebSocketConnection("conn_1", "dispatcher_1", "dispatcher")
    connection.subscribe("dispatcher_board")

    async def _run():
        await broadcaster.register_connection(connection, org.id)
        summary = OperationalIntelligenceService.summarize(db_session, organization_id=org.id, ride_id=ride.id) # type: ignore
        anomalies = OperationalIntelligenceService.detect_anomalies(db_session, organization_id=org.id) # type: ignore
        recommendations = OperationalIntelligenceService.build_recommendations(db_session, organization_id=org.id, ride_id=ride.id) # type: ignore
        risk = OperationalIntelligenceService.build_risk_profile(db_session, organization_id=org.id, anomalies=anomalies) # type: ignore
        await OperationalIntelligenceService.broadcast_intelligence_snapshot(
            broadcaster,
            organization_id=org.id,
            summary=summary,
            anomalies=anomalies,
            recommendations=recommendations,
            risk=risk,
        )

        messages = []
        for _ in range(4):
            messages.append(await asyncio.wait_for(connection.send_queue.get(), timeout=1.0)) # type: ignore
        assert any("intelligence_summary" in message for message in messages) # type: ignore
        assert any("intelligence_anomalies" in message for message in messages) # type: ignore
        assert any("intelligence_recommendations" in message for message in messages) # type: ignore
        assert any("intelligence_risk" in message for message in messages) # type: ignore

    asyncio.run(_run())


def test_intelligence_api_endpoints_are_tenant_scoped(client): # type: ignore
    payload = _login(client, "dispatcher@amicor.local") # type: ignore
    headers = {"Authorization": f"Bearer {payload['access_token']}"}

    summary_response = client.get("/api/health-isf/intelligence/summary", headers=headers) # type: ignore
    assert summary_response.status_code == 200, summary_response.text # type: ignore
    summary_payload = summary_response.json() # type: ignore
    assert summary_payload["organization_id"]
    assert isinstance(summary_payload.get("operational_state_awareness", {}), dict)
    assert isinstance(summary_payload.get("operational_context_aggregation", {}), dict)
    assert isinstance(summary_payload.get("operational_correlations", {}), dict)
    assert isinstance(summary_payload.get("operational_anomaly_surface", {}), dict)
    verification = summary_payload.get("backend_state_verification", {})
    assert verification.get("backend_authoritative") is True
    assert verification.get("ui_derived_assumptions") is False

    anomalies_response = client.get("/api/health-isf/intelligence/anomalies", headers=headers) # type: ignore
    assert anomalies_response.status_code == 200, anomalies_response.text # type: ignore

    recommendations_response = client.get("/api/health-isf/intelligence/recommendations", headers=headers) # type: ignore
    assert recommendations_response.status_code == 200, recommendations_response.text # type: ignore

    risk_response = client.get("/api/health-isf/intelligence/risk", headers=headers) # type: ignore
    assert risk_response.status_code == 200, risk_response.text # type: ignore

    forbidden_response = client.get( # type: ignore
        "/api/health-isf/intelligence/summary?organization_id=org-unauthorized",
        headers=headers,
    )
    assert forbidden_response.status_code == 403, forbidden_response.text # type: ignore


def test_reanalyze_endpoint_broadcasts_and_persists(client): # type: ignore
    payload = _login(client, "dispatcher@amicor.local") # type: ignore
    headers = {"Authorization": f"Bearer {payload['access_token']}"}

    response = client.post( # type: ignore
        "/api/health-isf/intelligence/reanalyze",
        headers=headers,
        json={"broadcast": False},
    )
    assert response.status_code == 200, response.text # type: ignore
    body = response.json() # type: ignore
    assert body["summary"]["organization_id"]
    assert body["risk"]["risk_score"] >= 0.0
    assert body["summary"]["backend_state_verification"]["backend_authoritative"] is True
    assert "trip_lifecycle_events" in body["summary"]["operational_correlations"]
    assert "active_trip_state" in body["summary"]["operational_context_aggregation"]


def test_ai_dispatch_snapshot_contains_operational_cognition(client): # type: ignore
    payload = _login(client, "dispatcher@amicor.local") # type: ignore
    headers = {"Authorization": f"Bearer {payload['access_token']}"}

    response = client.get("/api/health-isf/ai-dispatch/snapshot", headers=headers) # type: ignore
    assert response.status_code == 200, response.text # type: ignore
    body = response.json() # type: ignore

    assert isinstance(body.get("operational_state_awareness"), dict)
    assert isinstance(body.get("operational_context_aggregation"), dict)
    assert isinstance(body.get("operational_correlations"), dict)
    assert isinstance(body.get("operational_anomaly_surface"), dict)
    verification = body.get("backend_state_verification", {})
    assert verification.get("backend_authoritative") is True
    assert verification.get("ui_derived_assumptions") is False
