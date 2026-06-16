"""Validation tests for operational intelligence expansion phase."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.helpers import uuid4
from app.modules.health_isf.dispatch_intelligence import DispatchIntelligenceEngine
from app.modules.health_isf.distributed_operations import DistributedOperationsService
from app.modules.health_isf.graph_correlation_service import GraphCorrelationService
from app.modules.health_isf.identity_registry import get_operational_identity_registry
from app.modules.health_isf.live_client_contracts import build_live_client_contracts
from app.modules.health_isf.models import DriverStatus, HealthISFDriver, HealthISFOrganization, HealthISFRide, RideStatus
from app.modules.health_isf.operational_identity_engine import OperationalIdentityEngine
from app.modules.health_isf.operational_map_service import OperationalMapService


def _make_db():
    import app.db.models  # noqa: F401 - ensure platform tables are present

    engine = create_engine("sqlite:///:memory:")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal()


def _seed_org(db):
    org = HealthISFOrganization(
        id=uuid4(),
        name="Expansion Org",
        code=f"EXP-{uuid4()[:8]}",
        is_active=True,
    )
    db.add(org)
    db.commit()
    return org


def test_operational_identity_continuity_and_reconnect():
    org_id = "org-expansion-1"
    identity_id = "dispatcher-1"

    OperationalIdentityEngine.register_identity(
        organization_id=org_id,
        identity_id=identity_id,
        identity_type="dispatcher",
        role="dispatcher",
        display_name="Dispatcher One",
    )
    session = OperationalIdentityEngine.open_session(
        organization_id=org_id,
        identity_id=identity_id,
        websocket_connection_id="conn-a",
        session_id="session-a",
    )
    OperationalIdentityEngine.reconnect(
        organization_id=org_id,
        session_id=session.session_id,
        connection_id="conn-b",
    )

    snapshot = OperationalIdentityEngine.continuity_snapshot(org_id)
    assert snapshot["tenant_continuity"]["enforced"] is True
    assert snapshot["operational_session_continuity"]["active_sessions"] >= 1
    assert any(item["event_type"] == "session_reconnected" for item in snapshot["events"])


def test_geospatial_state_synchronized_and_replay_safe():
    org_id = "org-geo-1"
    OperationalMapService.update_provider_zone(
        organization_id=org_id,
        provider_id="provider-1",
        center_lat=40.7128,
        center_lng=-74.0060,
        radius_km=4.5,
    )
    OperationalMapService.update_driver_position(
        organization_id=org_id,
        driver_id="driver-1",
        lat=40.7130,
        lng=-74.0050,
        status="available",
    )
    OperationalMapService.update_incident_signal(
        organization_id=org_id,
        incident_id="incident-1",
        lat=40.7129,
        lng=-74.0059,
        severity="high",
        category="medical",
    )

    state = OperationalMapService.get_map_state(organization_id=org_id)
    replay = OperationalMapService.replay(organization_id=org_id, cursor=3)

    assert state["tenant_isolated"] is True
    assert state["websocket_synchronized"] is True
    assert len(state["live_operational_map_state"]["incident_clustering"]) >= 1
    assert replay["replay_cursor"] >= 3


def test_dispatch_intelligence_recommendation_only_and_confidence_scored():
    db = _make_db()
    try:
        org = _seed_org(db)
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org.id,
            name="Driver Dispatch",
            phone="555-0191",
            vehicle_type="van",
            vehicle_plate="D-111",
            status=DriverStatus.AVAILABLE,
            rating=4.8,
            total_trips=40,
        )
        ride = HealthISFRide(
            id=uuid4(),
            organization_id=org.id,
            passenger_name="Passenger Dispatch",
            passenger_phone="555-0100",
            pickup_address="Origin",
            dropoff_address="Destination",
            service_type="medical_transport",
            status=RideStatus.PENDING,
            is_emergency=True,
        )
        db.add(driver)
        db.add(ride)
        db.commit()

        bundle = DispatchIntelligenceEngine.build_bundle(db, org.id)
        assert bundle["recommendation_only"] is True
        assert bundle["approval_required"] is True
        assert bundle["unrestricted_execution"] is False
        assert bundle["summary"]["confidence_scored"] is True
        assert bundle["summary"]["explainable"] is True
        assert len(bundle["recommendations"]) >= 1
    finally:
        db.close()


def test_diaspora_network_and_graph_are_append_only_and_tenant_scoped():
    org_id = "org-network-1"
    DistributedOperationsService.upsert_regional_cluster(
        organization_id=org_id,
        cluster_id="cluster-east",
        region_code="us-east",
        tenant_ids=["tenant-a", "tenant-b"],
        provider_ids=["provider-a"],
    )
    DistributedOperationsService.append_coordination_signal(
        organization_id=org_id,
        signal_type="load_shift",
        region_code="us-east",
        payload={"from": "tenant-a", "to": "tenant-b", "reason": "capacity"},
    )

    graph = GraphCorrelationService.correlate(
        organization_id=org_id,
        source={"id": "incident:1", "type": "incident", "label": "Incident 1"},
        target={"id": "provider:1", "type": "provider", "label": "Provider 1"},
        relationship_type="handled_by",
        confidence=0.9,
        explanation="Operational linkage from dispatch activity.",
    )

    network_snapshot = DistributedOperationsService.get_snapshot(organization_id=org_id)
    assert network_snapshot["tenant_isolated"] is True
    assert network_snapshot["governed"] is True
    assert graph["append_only_relationships"] is True
    assert graph["tenant_isolated"] is True


def test_live_client_contracts_are_stable_and_role_scoped():
    contracts = build_live_client_contracts("org-contract-1")
    assert contracts["shared_operational_contracts"]["stable_websocket_payloads"] is True
    assert contracts["shared_operational_contracts"]["role_scoped_visibility"] is True
    assert contracts["shared_operational_contracts"]["approval_governed_actions"] is True
    assert contracts["shared_operational_contracts"]["no_unrestricted_autonomy"] is True


def test_registry_events_remain_append_only():
    org_id = "org-append-only-1"
    registry = get_operational_identity_registry()
    OperationalIdentityEngine.register_identity(
        organization_id=org_id,
        identity_id="staff-1",
        identity_type="staff",
        role="staff",
        display_name="Staff",
    )
    OperationalIdentityEngine.open_session(
        organization_id=org_id,
        identity_id="staff-1",
        websocket_connection_id=None,
        session_id="s-1",
    )
    events = registry.list_events(org_id, limit=10)
    assert len(events) >= 2
    assert all(item.get("append_only") is True for item in events)
