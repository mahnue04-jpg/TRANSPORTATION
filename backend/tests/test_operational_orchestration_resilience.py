from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import now, uuid4
from app.main import app
from app.modules.health_isf.models import (
    AutomationPolicyScope,
    DispatchAssignmentState,
    DriverStatus,
    HealthISFAutomationPolicy,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFDriverLocationPing,
    HealthISFGovernanceApproval,
    HealthISFOrganization,
    HealthISFProvider,
    HealthISFRide,
    HealthISFRideRoutePlan,
)
from app.modules.health_isf.operational_event_bus import get_operational_event_bus
from app.modules.health_isf.operational_orchestration_resilience import OperationalOrchestrationResilienceService
from app.modules.health_isf.realtime_service import OperationalAlertService


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        assert user.organization_id is not None
        return str(user.organization_id)


def _user_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        return str(user.id)


def _ensure_provider(organization_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if provider is not None:
            return str(provider.id)

        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Ops Orchestration Provider {uuid4()[:6]}",
            address="810 Resilience Way",
            phone="212-555-7711",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _ensure_driver(organization_id: str, *, suffix: str) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Orchestration Driver {suffix}",
            phone=f"646-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"ORC-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_pending_ride(client: TestClient, token: str, provider_id: str) -> str:
    response = client.post(
        "/api/health-isf/rides",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "passenger_name": f"Ops Rider {uuid4()[:6]}",
            "passenger_phone": "+1 212-555-8833",
            "pickup_address": "101 Orchestration Ave, New York, NY 10001",
            "dropoff_address": "202 Orchestration Ave, New York, NY 10002",
            "service_type": "medical_transport",
            "provider_id": provider_id,
            "priority_tag": "high",
        },
    )
    assert response.status_code == 201, response.text
    ride_id = str(response.json()["id"])

    with SessionLocal() as db:
        row = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
        assert row is not None
        row.requested_at = now() - timedelta(minutes=35)
        row.updated_at = now() - timedelta(minutes=35)
        db.commit()

    return ride_id


def _seed_route_and_location(organization_id: str, ride_id: str, driver_id: str) -> None:
    with SessionLocal() as db:
        route = (
            db.query(HealthISFRideRoutePlan)
            .filter(
                HealthISFRideRoutePlan.organization_id == organization_id,
                HealthISFRideRoutePlan.ride_id == ride_id,
            )
            .first()
        )
        if route is None:
            route = HealthISFRideRoutePlan(
                id=uuid4(),
                organization_id=organization_id,
                ride_id=ride_id,
                map_provider="synthetic",
                route_reference=f"route-{uuid4()[:8]}",
                origin_latitude=40.7580,
                origin_longitude=-73.9855,
                destination_latitude=40.7610,
                destination_longitude=-73.9810,
                estimated_distance_miles=2.4,
                estimated_duration_minutes=18,
                traffic_multiplier=1.0,
                deviation_threshold_meters=250.0,
                path_points_json="[]",
                created_at=now(),
                updated_at=now(),
            )
            db.add(route)

        loc = HealthISFDriverLocationPing(
            id=uuid4(),
            organization_id=organization_id,
            driver_id=driver_id,
            ride_id=None,
            latitude=40.7584,
            longitude=-73.9851,
            heading=None,
            speed_kph=None,
            accuracy_meters=8.0,
            source="test",
            device_id=f"test-device-{uuid4()[:6]}",
            heartbeat_at=now(),
            created_at=now(),
        )
        db.add(loc)
        db.commit()


def _seed_isolated_org(db) -> str:
    org_id = str(uuid4())
    db.add(
        HealthISFOrganization(
            id=org_id,
            name=f"Isolated Orchestration Org {uuid4()[:6]}",
            code=f"ISO-{uuid4()[:6]}",
            address="100 Isolation Ave",
            phone="212-555-0000",
            is_active=True,
            created_at=now(),
            updated_at=now(),
        )
    )
    db.commit()
    return org_id


def _seed_policy(
    db,
    organization_id: str,
    *,
    approval_required: bool = False,
    auto_escalation_enabled: bool = True,
    approval_required_decision_types: list[str] | None = None,
) -> str:
    decision_types = approval_required_decision_types if approval_required_decision_types is not None else ["automated_reassignment_execution"]
    policy = HealthISFAutomationPolicy(
        id=str(uuid4()),
        organization_id=organization_id,
        name=f"Autonomous Policy {uuid4()[:6]}",
        scope=AutomationPolicyScope.TENANT.value,
        is_enabled=True,
        approval_required=approval_required,
        auto_reassign_enabled=True,
        auto_escalation_enabled=auto_escalation_enabled,
        allow_replay=True,
        max_retry_attempts=3,
        stuck_ride_minutes=45,
        delayed_pickup_minutes=20,
        escalation_minutes=30,
        policy_rules=json.dumps(
            {
                "autonomous_decision_enabled": True,
                "autonomous_confidence_min": 0.6,
                "approval_required_decision_types": decision_types,
            },
            sort_keys=True,
        ),
        created_at=now(),
        updated_at=now(),
    )
    db.add(policy)
    db.commit()
    return str(policy.id)


def test_escalation_generation(db) -> None:
    org_id = _seed_isolated_org(db)
    escalations = OperationalOrchestrationResilienceService.generate_automated_escalations(
        db,
        organization_id=org_id,
        incidents=[
            {
                "incident_type": "sla_breach_monitoring",
                "incident_key": f"sla-test:{uuid4()}",
                "severity": "high",
                "message": "deterministic SLA breach escalation",
                "details": {},
                "role_targets": ["dispatcher", "supervisor"],
            }
        ],
        actor_user_id="test-escalation",
    )
    assert len(escalations) > 0
    assert any(str(item.get("escalation_type")) == "automatic_sla_escalation" for item in escalations)


def test_escalation_deduplication(db) -> None:
    org_id = _seed_isolated_org(db)
    incident = {
        "incident_type": "sla_breach_monitoring",
        "incident_key": f"sla-dedup:{uuid4()}",
        "severity": "high",
        "message": "dedup test incident",
        "details": {},
        "role_targets": ["dispatcher", "supervisor"],
    }

    first = OperationalOrchestrationResilienceService.generate_automated_escalations(
        db,
        organization_id=org_id,
        incidents=[incident],
        actor_user_id="test-dedup",
    )
    second = OperationalOrchestrationResilienceService.generate_automated_escalations(
        db,
        organization_id=org_id,
        incidents=[incident],
        actor_user_id="test-dedup",
    )

    first_count = len(first)
    second_count = len(second)
    assert second_count <= first_count


def test_automated_reassignment_recommendation(db) -> None:
    org_id = _seed_isolated_org(db)
    driver_id = str(uuid4())
    ride_id = str(uuid4())

    db.add(
        HealthISFDriver(
            id=driver_id,
            organization_id=org_id,
            name="Deterministic Recommendation Driver",
            phone="646-555-0101",
            vehicle_type="sedan",
            vehicle_plate="ISO-REC-1",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            total_trips=12,
            rating=4.8,
            created_at=now(),
            updated_at=now(),
        )
    )
    db.add(
        HealthISFRide(
            id=ride_id,
            organization_id=org_id,
            provider_id=None,
            driver_id=None,
            created_by_user_id=None,
            assigned_by_user_id=None,
            last_status_changed_by_user_id=None,
            passenger_name="Deterministic Rider",
            passenger_phone="+1 212-555-1001",
            pickup_address="10 Test Pickup",
            dropoff_address="20 Test Dropoff",
            service_type="medical_transport",
            status="pending",
            lifecycle_state="requested",
            requested_at=now() - timedelta(minutes=22),
            created_at=now(),
            updated_at=now(),
            notes="recommendation test",
        )
    )
    db.add(
        HealthISFRideRoutePlan(
            id=str(uuid4()),
            organization_id=org_id,
            ride_id=ride_id,
            map_provider="synthetic",
            route_reference="iso-route-1",
            origin_latitude=40.7580,
            origin_longitude=-73.9855,
            destination_latitude=40.7610,
            destination_longitude=-73.9810,
            estimated_distance_miles=2.2,
            estimated_duration_minutes=17,
            traffic_multiplier=1.0,
            deviation_threshold_meters=250.0,
            path_points_json="[]",
            created_at=now(),
            updated_at=now(),
        )
    )
    db.add(
        HealthISFDriverLocationPing(
            id=str(uuid4()),
            organization_id=org_id,
            driver_id=driver_id,
            ride_id=None,
            latitude=40.7584,
            longitude=-73.9851,
            heading=None,
            speed_kph=None,
            accuracy_meters=8.0,
            source="test",
            device_id="iso-device",
            heartbeat_at=now(),
            created_at=now(),
        )
    )
    db.commit()

    recommendations = OperationalOrchestrationResilienceService.generate_dispatch_recommendations(
        db,
        organization_id=org_id,
        actor_user_id="test-recommendation",
        limit=20,
    )
    assert len(recommendations) > 0
    assert any(
        str(item.get("recommended_driver_id") or "") == driver_id
        or str(item.get("recommendation_type") or "") == "queue_pressure_reduction"
        for item in recommendations
    )


def test_resilience_state_transitions(client: TestClient) -> None:
    org_id = _org_id_for("admin@amicor.local")
    actor_user_id = _user_id_for("admin@amicor.local")
    with SessionLocal() as db:
        critical = OperationalOrchestrationResilienceService.resolve_resilience_state(
            db,
            organization_id=org_id,
            incidents=[{"incident_type": "critical_test", "severity": "critical"}],
            recovery_operations=[],
            actor_user_id=actor_user_id,
        )
        assert critical.get("state") in {"critical", "replay_repair", "synchronization_risk"}

        follow_up = OperationalOrchestrationResilienceService.resolve_resilience_state(
            db,
            organization_id=org_id,
            incidents=[],
            recovery_operations=[],
            actor_user_id=actor_user_id,
        )
        assert follow_up.get("previous_state") is not None
        assert str(follow_up.get("state") or "") in {
            "healthy",
            "degraded",
            "recovering",
            "critical",
            "replay_repair",
            "synchronization_risk",
        }


def test_degraded_websocket_recovery(db) -> None:
    org_id = _seed_isolated_org(db)
    OperationalAlertService.log_alert(
        db,
        organization_id=org_id,
        alert_type="websocket_disconnect_degradation_alert",
        severity="high",
        message="forced websocket degradation for resilience test",
        payload={"disconnects_last_5m": 12},
        incident_key=f"ws-recovery:{uuid4()}",
        target_roles=["dispatcher", "command-center"],
        notification_channels=["dispatcher_board"],
        deduplicate_open_incident=False,
    )

    recovery = OperationalOrchestrationResilienceService.run_automated_recovery(
        db,
        organization_id=org_id,
        actor_user_id="test-recovery",
    )
    assert any(str(item.get("operation_type")) == "degraded_websocket_recovery_mode" for item in recovery)


def test_replay_safe_automation_rebuild(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    org_id = _org_id_for("admin@amicor.local")

    response = client.get(
        "/api/health-isf/ops/command-center/orchestration",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
        params={"organization_id": org_id},
    )
    assert response.status_code == 200, response.text

    rebuild = response.json().get("automation", {}).get("replayable_automation_rebuild", {})
    assert rebuild.get("replay_safe") is True
    assert rebuild.get("reconstructable") is True
    assert rebuild.get("sequence_ordered") is True


def test_synchronization_safe_automation_replay(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    org_id = _org_id_for("admin@amicor.local")

    response = client.get(
        "/api/health-isf/ops/command-center/orchestration",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
        params={"organization_id": org_id},
    )
    assert response.status_code == 200, response.text

    events = response.json().get("automation", {}).get("replayable_automation_rebuild", {}).get("events", [])
    sequences = [int(item.get("replay_sequence", 0) or 0) for item in events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)


def test_multi_user_orchestration_consistency(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    dispatcher = _login(client, "dispatcher@amicor.local")
    org_id = _org_id_for("admin@amicor.local")

    admin_view = client.get(
        "/api/health-isf/ops/command-center/orchestration",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
        params={"organization_id": org_id},
    )
    dispatcher_view = client.get(
        "/api/health-isf/ops/command-center/orchestration",
        headers={"Authorization": f"Bearer {dispatcher['access_token']}"},
        params={"organization_id": org_id},
    )

    assert admin_view.status_code == 200, admin_view.text
    assert dispatcher_view.status_code == 200, dispatcher_view.text

    a = admin_view.json().get("automation", {})
    b = dispatcher_view.json().get("automation", {})

    assert str(a.get("resilience_state_machine", {}).get("state")) == str(b.get("resilience_state_machine", {}).get("state"))
    assert bool(a.get("cross_role_synchronized")) is True
    assert bool(b.get("cross_role_synchronized")) is True


def test_sla_prediction_generation(db) -> None:
    org_id = _seed_isolated_org(db)
    driver_id = str(uuid4())
    ride_id = str(uuid4())

    db.add(
        HealthISFDriver(
            id=driver_id,
            organization_id=org_id,
            name="Predictive SLA Driver",
            phone="646-555-2020",
            vehicle_type="sedan",
            vehicle_plate="ISO-PSLA-1",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            total_trips=21,
            rating=4.7,
            created_at=now(),
            updated_at=now(),
        )
    )
    db.add(
        HealthISFRide(
            id=ride_id,
            organization_id=org_id,
            provider_id=None,
            driver_id=driver_id,
            created_by_user_id=None,
            assigned_by_user_id=None,
            last_status_changed_by_user_id=None,
            passenger_name="Predictive SLA Rider",
            passenger_phone="+1 212-555-2001",
            pickup_address="100 Predictive Ave",
            dropoff_address="200 Predictive Ave",
            service_type="medical_transport",
            status="assigned",
            lifecycle_state="assigned",
            requested_at=now() - timedelta(minutes=33),
            accepted_at=now() - timedelta(minutes=30),
            created_at=now(),
            updated_at=now(),
            notes="predictive sla test",
        )
    )
    db.add(
        HealthISFRideRoutePlan(
            id=str(uuid4()),
            organization_id=org_id,
            ride_id=ride_id,
            map_provider="synthetic",
            route_reference="psla-route",
            origin_latitude=40.7580,
            origin_longitude=-73.9855,
            destination_latitude=40.7610,
            destination_longitude=-73.9810,
            estimated_distance_miles=2.4,
            estimated_duration_minutes=12,
            traffic_multiplier=1.8,
            deviation_threshold_meters=250.0,
            path_points_json="[]",
            created_at=now(),
            updated_at=now(),
        )
    )
    db.commit()

    forecasts = OperationalOrchestrationResilienceService.generate_predictive_sla_risk_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-predictive-sla",
        incidents=[{"incident_type": "sla_breach_monitoring", "severity": "high", "details": {}}],
    )
    assert len(forecasts) >= 6
    sla = [item for item in forecasts if str(item.get("prediction_type")) == "predicted_pickup_sla_breach"]
    assert sla
    assert float(sla[0].get("risk_score", 0.0) or 0.0) > 0.0


def test_prediction_replay_rebuild(db) -> None:
    org_id = _seed_isolated_org(db)
    ride_id = str(uuid4())
    db.add(
        HealthISFRide(
            id=ride_id,
            organization_id=org_id,
            provider_id=None,
            driver_id=None,
            created_by_user_id=None,
            assigned_by_user_id=None,
            last_status_changed_by_user_id=None,
            passenger_name="Replay Rider",
            passenger_phone="+1 212-555-3001",
            pickup_address="Replay Pickup",
            dropoff_address="Replay Dropoff",
            service_type="medical_transport",
            status="pending",
            lifecycle_state="requested",
            requested_at=now() - timedelta(minutes=28),
            created_at=now(),
            updated_at=now(),
            notes="replay test",
        )
    )
    db.commit()

    OperationalOrchestrationResilienceService.generate_predictive_sla_risk_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-predictive-replay",
        incidents=[],
    )
    replay = OperationalOrchestrationResilienceService.replayable_prediction_rebuild(
        db,
        organization_id=org_id,
        limit=300,
    )

    assert replay.get("replay_safe") is True
    assert replay.get("sequence_ordered") is True
    events = replay.get("events", [])
    sequences = [int(item.get("replay_sequence", 0) or 0) for item in events]
    assert sequences == sorted(sequences)


def test_congestion_forecasting(db) -> None:
    org_id = _seed_isolated_org(db)
    ride_a = str(uuid4())
    ride_b = str(uuid4())

    for ride_id in [ride_a, ride_b]:
        db.add(
            HealthISFRide(
                id=ride_id,
                organization_id=org_id,
                provider_id=None,
                driver_id=None,
                created_by_user_id=None,
                assigned_by_user_id=None,
                last_status_changed_by_user_id=None,
                passenger_name=f"Region Rider {ride_id[:6]}",
                passenger_phone=f"+1 212-555-{ride_id.replace('-', '')[:4]}",
                pickup_address="Congestion Core",
                dropoff_address="Congestion Exit",
                service_type="medical_transport",
                status="pending",
                lifecycle_state="requested",
                requested_at=now() - timedelta(minutes=20),
                created_at=now(),
                updated_at=now(),
                notes="regional test",
            )
        )
        db.add(
            HealthISFRideRoutePlan(
                id=str(uuid4()),
                organization_id=org_id,
                ride_id=ride_id,
                map_provider="synthetic",
                route_reference=f"region-{ride_id[:6]}",
                origin_latitude=40.7602,
                origin_longitude=-73.9831,
                destination_latitude=40.7710,
                destination_longitude=-73.9720,
                estimated_distance_miles=3.1,
                estimated_duration_minutes=24,
                traffic_multiplier=2.3,
                deviation_threshold_meters=250.0,
                path_points_json="[]",
                created_at=now(),
                updated_at=now(),
            )
        )
    db.commit()

    regional = OperationalOrchestrationResilienceService.generate_regional_mobility_intelligence(
        db,
        organization_id=org_id,
        actor_user_id="test-regional",
        incidents=[],
    )
    assert regional
    assert any(float(item.get("congestion_pressure_analysis", 0.0) or 0.0) > 0.0 for item in regional)


def test_driver_reliability_scoring_consistency(db) -> None:
    org_id = _seed_isolated_org(db)
    driver_id = str(uuid4())
    ride_ok = str(uuid4())
    ride_bad = str(uuid4())

    db.add(
        HealthISFDriver(
            id=driver_id,
            organization_id=org_id,
            name="Reliability Driver",
            phone="646-555-4100",
            vehicle_type="sedan",
            vehicle_plate="ISO-RLB-1",
            status=DriverStatus.ASSIGNED,
            is_active=True,
            total_trips=50,
            rating=4.6,
            created_at=now(),
            updated_at=now(),
        )
    )
    db.add_all(
        [
            HealthISFRide(
                id=ride_ok,
                organization_id=org_id,
                provider_id=None,
                driver_id=driver_id,
                created_by_user_id=None,
                assigned_by_user_id=None,
                last_status_changed_by_user_id=None,
                passenger_name="Reliability A",
                passenger_phone="+1 212-555-4101",
                pickup_address="A",
                dropoff_address="B",
                service_type="medical_transport",
                status="completed",
                lifecycle_state="completed",
                requested_at=now() - timedelta(minutes=40),
                accepted_at=now() - timedelta(minutes=35),
                completed_at=now() - timedelta(minutes=5),
                created_at=now(),
                updated_at=now(),
                notes="ok",
            ),
            HealthISFRide(
                id=ride_bad,
                organization_id=org_id,
                provider_id=None,
                driver_id=driver_id,
                created_by_user_id=None,
                assigned_by_user_id=None,
                last_status_changed_by_user_id=None,
                passenger_name="Reliability B",
                passenger_phone="+1 212-555-4102",
                pickup_address="A",
                dropoff_address="B",
                service_type="medical_transport",
                status="cancelled",
                lifecycle_state="cancelled",
                requested_at=now() - timedelta(minutes=60),
                accepted_at=now() - timedelta(minutes=55),
                created_at=now(),
                updated_at=now(),
                notes="bad",
            ),
        ]
    )
    db.add_all(
        [
            HealthISFDispatchAssignment(
                id=str(uuid4()),
                organization_id=org_id,
                ride_id=ride_ok,
                driver_id=driver_id,
                assignment_state=DispatchAssignmentState.ACCEPTED.value,
                attempt_index=1,
                offered_at=now() - timedelta(minutes=36),
                accepted_at=now() - timedelta(minutes=35),
                created_at=now(),
                updated_at=now(),
            ),
            HealthISFDispatchAssignment(
                id=str(uuid4()),
                organization_id=org_id,
                ride_id=ride_bad,
                driver_id=driver_id,
                assignment_state=DispatchAssignmentState.REJECTED.value,
                attempt_index=1,
                offered_at=now() - timedelta(minutes=56),
                rejected_at=now() - timedelta(minutes=55),
                created_at=now(),
                updated_at=now(),
            ),
        ]
    )
    db.add(
        HealthISFDriverLocationPing(
            id=str(uuid4()),
            organization_id=org_id,
            driver_id=driver_id,
            ride_id=None,
            latitude=40.7611,
            longitude=-73.9821,
            heading=None,
            speed_kph=None,
            accuracy_meters=10.0,
            source="test",
            device_id="driver-rel-test",
            heartbeat_at=now(),
            created_at=now(),
        )
    )
    db.commit()

    first = OperationalOrchestrationResilienceService.generate_driver_reliability_intelligence(
        db,
        organization_id=org_id,
        actor_user_id="test-driver-reliability",
    )
    second = OperationalOrchestrationResilienceService.generate_driver_reliability_intelligence(
        db,
        organization_id=org_id,
        actor_user_id="test-driver-reliability",
    )

    first_entry = next(item for item in first if str(item.get("driver_id")) == driver_id)
    second_entry = next(item for item in second if str(item.get("driver_id")) == driver_id)
    first_score = float(first_entry.get("reliability_score", 0.0) or 0.0)
    second_score = float(second_entry.get("reliability_score", 0.0) or 0.0)
    assert abs(first_score - second_score) < 0.01


def test_overload_forecasting(db) -> None:
    org_id = _seed_isolated_org(db)
    for idx in range(6):
        db.add(
            HealthISFRide(
                id=str(uuid4()),
                organization_id=org_id,
                provider_id=None,
                driver_id=None,
                created_by_user_id=None,
                assigned_by_user_id=None,
                last_status_changed_by_user_id=None,
                passenger_name=f"Overload Rider {idx}",
                passenger_phone=f"+1 212-555-51{idx:02d}",
                pickup_address="Queue In",
                dropoff_address="Queue Out",
                service_type="medical_transport",
                status="pending",
                lifecycle_state="requested",
                requested_at=now() - timedelta(minutes=26 + idx),
                created_at=now(),
                updated_at=now(),
                notes="overload",
            )
        )
    db.commit()

    forecasts = OperationalOrchestrationResilienceService.generate_predictive_sla_risk_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-overload",
        incidents=[],
    )
    overload = [item for item in forecasts if str(item.get("prediction_type")) == "projected_dispatcher_overload"]
    assert overload
    assert float(overload[0].get("risk_score", 0.0) or 0.0) >= 0.55


def test_predictive_reassignment_logic(db) -> None:
    org_id = _seed_isolated_org(db)
    driver_id = str(uuid4())
    ride_id = str(uuid4())
    db.add(
        HealthISFDriver(
            id=driver_id,
            organization_id=org_id,
            name="Predictive Reassign Driver",
            phone="646-555-6200",
            vehicle_type="sedan",
            vehicle_plate="ISO-PRD-1",
            status=DriverStatus.ASSIGNED,
            is_active=True,
            total_trips=120,
            rating=4.2,
            created_at=now(),
            updated_at=now(),
        )
    )
    db.add(
        HealthISFRide(
            id=ride_id,
            organization_id=org_id,
            provider_id=None,
            driver_id=driver_id,
            created_by_user_id=None,
            assigned_by_user_id=None,
            last_status_changed_by_user_id=None,
            passenger_name="Predictive Reassign Rider",
            passenger_phone="+1 212-555-6201",
            pickup_address="Reassign Pickup",
            dropoff_address="Reassign Dropoff",
            service_type="medical_transport",
            status="assigned",
            lifecycle_state="assigned",
            requested_at=now() - timedelta(minutes=40),
            accepted_at=now() - timedelta(minutes=35),
            created_at=now(),
            updated_at=now(),
            notes="predictive reassignment",
        )
    )
    db.add(
        HealthISFDispatchAssignment(
            id=str(uuid4()),
            organization_id=org_id,
            ride_id=ride_id,
            driver_id=driver_id,
            assignment_state=DispatchAssignmentState.REJECTED.value,
            attempt_index=1,
            offered_at=now() - timedelta(minutes=37),
            rejected_at=now() - timedelta(minutes=36),
            created_at=now(),
            updated_at=now(),
        )
    )
    db.commit()

    forecasts = OperationalOrchestrationResilienceService.generate_predictive_sla_risk_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-predictive-reassign",
        incidents=[{"incident_type": "sla_breach_monitoring", "severity": "high", "details": {}}],
    )
    reliability = OperationalOrchestrationResilienceService.generate_driver_reliability_intelligence(
        db,
        organization_id=org_id,
        actor_user_id="test-predictive-reassign",
    )
    regional = OperationalOrchestrationResilienceService.generate_regional_mobility_intelligence(
        db,
        organization_id=org_id,
        actor_user_id="test-predictive-reassign",
        incidents=[],
    )
    actions = OperationalOrchestrationResilienceService.generate_predictive_recovery_coordination(
        db,
        organization_id=org_id,
        actor_user_id="test-predictive-reassign",
        forecasts=forecasts,
        driver_reliability=reliability,
        regional_forecasts=regional,
    )

    assert any(str(item.get("operation_type")) == "preemptive_reassignment_recommendation" for item in actions)


def test_forecast_deduplication(db) -> None:
    org_id = _seed_isolated_org(db)
    ride_id = str(uuid4())
    db.add(
        HealthISFRide(
            id=ride_id,
            organization_id=org_id,
            provider_id=None,
            driver_id=None,
            created_by_user_id=None,
            assigned_by_user_id=None,
            last_status_changed_by_user_id=None,
            passenger_name="Dedup Forecast Rider",
            passenger_phone="+1 212-555-7001",
            pickup_address="Dedup Pickup",
            dropoff_address="Dedup Dropoff",
            service_type="medical_transport",
            status="pending",
            lifecycle_state="requested",
            requested_at=now() - timedelta(minutes=30),
            created_at=now(),
            updated_at=now(),
            notes="forecast dedup",
        )
    )
    db.commit()

    first = OperationalOrchestrationResilienceService.generate_predictive_sla_risk_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-forecast-dedup",
        incidents=[],
    )
    second = OperationalOrchestrationResilienceService.generate_predictive_sla_risk_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-forecast-dedup",
        incidents=[],
    )

    assert len(second) <= len(first)


def test_reconnect_safe_prediction_synchronization(db) -> None:
    org_id = _seed_isolated_org(db)
    db.add(
        HealthISFRide(
            id=str(uuid4()),
            organization_id=org_id,
            provider_id=None,
            driver_id=None,
            created_by_user_id=None,
            assigned_by_user_id=None,
            last_status_changed_by_user_id=None,
            passenger_name="Reconnect Predictive Rider",
            passenger_phone="+1 212-555-8101",
            pickup_address="Reconnect Pickup",
            dropoff_address="Reconnect Dropoff",
            service_type="medical_transport",
            status="pending",
            lifecycle_state="requested",
            requested_at=now() - timedelta(minutes=27),
            created_at=now(),
            updated_at=now(),
            notes="reconnect predictive sync",
        )
    )
    db.commit()

    OperationalOrchestrationResilienceService.execute_automation_cycle(
        db,
        organization_id=org_id,
        incidents=[],
        actor_user_id="test-reconnect-sync",
    )

    envelopes = get_operational_event_bus().replay(org_id, after_sequence=0, limit=300)
    predictive_events = [
        item
        for item in envelopes
        if bool((item.payload or {}).get("predictive"))
    ]
    assert predictive_events
    sequences = [int(item.sequence) for item in envelopes]
    assert sequences == sorted(sequences)


def test_policy_constrained_automation(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id, auto_escalation_enabled=False)

    result = OperationalOrchestrationResilienceService.execute_autonomous_decision_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-policy-gate",
        escalations=[{"escalation_id": str(uuid4()), "dedup_key": f"esc:{uuid4()}", "severity": "high"}],
        recommendations=[],
        recovery_operations=[],
        predictive_recovery=[],
        forecasts=[],
        resilience_state={"state": "healthy"},
    )

    assert result.get("denial_count", 0) >= 1
    assert any("auto_escalation_disabled" in (item.get("policy_reasons") or []) for item in result.get("denied", []))


def test_replay_safe_decision_rebuild(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)

    OperationalOrchestrationResilienceService.execute_automation_cycle(
        db,
        organization_id=org_id,
        incidents=[],
        actor_user_id="test-autonomous-replay",
    )

    rebuild = OperationalOrchestrationResilienceService.replayable_autonomous_decision_rebuild(
        db,
        organization_id=org_id,
        limit=400,
    )
    assert rebuild.get("replay_safe") is True
    assert rebuild.get("sequence_ordered") is True


def test_automation_rollback_integrity(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id, approval_required_decision_types=[])
    ride_id = str(uuid4())

    result = OperationalOrchestrationResilienceService.execute_autonomous_decision_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-rollback-integrity",
        escalations=[],
        recommendations=[
            {
                "recommendation_type": "recovery_reassignment_suggestion",
                "ride_id": ride_id,
                "recommended_driver_id": str(uuid4()),
                "score": 0.92,
                "dedup_key": f"rr:{ride_id}",
            }
        ],
        recovery_operations=[],
        predictive_recovery=[],
        forecasts=[],
        resilience_state={"state": "healthy"},
    )

    assert result.get("execution_count", 0) >= 1
    assert result.get("rollback_records")
    timeline = OperationalOrchestrationResilienceService.build_operational_intelligence_timeline(
        db,
        organization_id=org_id,
        limit=200,
    )
    assert timeline.get("rollback_events")


def test_autonomous_reassignment_safety_conflict_detection(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)
    ride_id = str(uuid4())

    result = OperationalOrchestrationResilienceService.execute_autonomous_decision_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-conflict",
        escalations=[],
        recommendations=[
            {
                "recommendation_type": "recovery_reassignment_suggestion",
                "ride_id": ride_id,
                "recommended_driver_id": str(uuid4()),
                "score": 0.9,
                "dedup_key": f"r1:{ride_id}",
            },
            {
                "recommendation_type": "recovery_reassignment_suggestion",
                "ride_id": ride_id,
                "recommended_driver_id": str(uuid4()),
                "score": 0.88,
                "dedup_key": f"r2:{ride_id}",
            },
        ],
        recovery_operations=[],
        predictive_recovery=[],
        forecasts=[],
        resilience_state={"state": "healthy"},
    )

    assert result.get("conflict_count", 0) >= 1


def test_overload_mitigation_coordination(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)
    overload_forecast = {
        "prediction_type": "projected_dispatcher_overload",
        "risk_score": 0.86,
        "threshold_exceeded": True,
        "projected_value": 3.4,
        "dedup_key": f"overload:{uuid4()}",
        "confidence": 0.82,
    }

    predictive = OperationalOrchestrationResilienceService.generate_predictive_recovery_coordination(
        db,
        organization_id=org_id,
        actor_user_id="test-overload-coordination",
        forecasts=[overload_forecast],
        driver_reliability=[],
        regional_forecasts=[],
    )
    assert any(str(item.get("operation_type")) == "projected_overload_mitigation" for item in predictive)


def test_degraded_state_recovery_execution(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)

    chain = OperationalOrchestrationResilienceService.execute_autonomous_recovery_coordinator(
        db,
        organization_id=org_id,
        actor_user_id="test-degraded-recovery",
        resilience_state={"state": "degraded"},
        recovery_operations=[{"operation_type": "degraded_websocket_recovery_mode", "dedup_key": f"d:{uuid4()}"}],
        predictive_recovery=[{"operation_type": "resilience_preparation_before_degradation_state", "dedup_key": f"p:{uuid4()}"}],
    )

    assert any(str(item.get("operation_type")) == "autonomous_recovery_stabilization_chain" for item in chain)


def test_orchestration_denial_handling(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)

    result = OperationalOrchestrationResilienceService.execute_autonomous_decision_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-denial",
        escalations=[],
        recommendations=[
            {
                "recommendation_type": "queue_pressure_reduction",
                "ride_id": None,
                "recommended_driver_id": None,
                "score": 0.1,
                "confidence": 0.2,
                "dedup_key": f"low:{uuid4()}",
            }
        ],
        recovery_operations=[],
        predictive_recovery=[],
        forecasts=[],
        resilience_state={"state": "healthy"},
    )
    assert result.get("denial_count", 0) >= 1
    assert any(str(item.get("reason") or "") == "policy_constrained_automation_denial" for item in result.get("denied", []))


def test_operator_override_synchronization(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id, approval_required=True)
    ride_id = str(uuid4())

    result = OperationalOrchestrationResilienceService.execute_autonomous_decision_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-oversight",
        escalations=[],
        recommendations=[
            {
                "recommendation_type": "recovery_reassignment_suggestion",
                "ride_id": ride_id,
                "recommended_driver_id": str(uuid4()),
                "score": 0.91,
                "dedup_key": f"approval:{ride_id}",
            }
        ],
        recovery_operations=[],
        predictive_recovery=[],
        forecasts=[],
        resilience_state={"state": "healthy"},
    )

    assert result.get("approval_count", 0) >= 1
    approval_rows = db.query(HealthISFGovernanceApproval).filter(HealthISFGovernanceApproval.organization_id == org_id).all()
    assert approval_rows
    envelopes = get_operational_event_bus().replay(org_id, after_sequence=0, limit=200)
    assert any(bool((item.payload or {}).get("supervisor_intervention_required")) for item in envelopes)


def test_multi_agent_synchronization(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id, approval_required_decision_types=[])

    result = OperationalOrchestrationResilienceService.execute_automation_cycle(
        db,
        organization_id=org_id,
        incidents=[
            {
                "incident_type": "dispatch_queue_congestion",
                "incident_key": f"sync:{uuid4()}",
                "severity": "high",
                "message": "coordination sync test",
                "details": {},
                "role_targets": ["dispatcher", "supervisor"],
            }
        ],
        actor_user_id="test-multi-agent-sync",
    )

    coordination = result.get("multi_agent_operational_coordination") or {}
    assert coordination
    assert (coordination.get("agent_consensus") or {}).get("consensus_deterministic") is True


def test_consensus_determinism(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id, approval_required_decision_types=[])
    resilience = {"state": "healthy"}
    layer = OperationalOrchestrationResilienceService.build_multi_agent_operational_coordination_layer(
        db,
        organization_id=org_id,
        actor_user_id="test-consensus-determinism",
        escalations=[],
        recommendations=[
            {
                "recommendation_type": "recovery_reassignment_suggestion",
                "ride_id": str(uuid4()),
                "score": 0.9,
                "dedup_key": f"d:{uuid4()}",
            }
        ],
        recovery_operations=[],
        proactive_recovery=[],
        forecasts=[],
        driver_reliability=[],
        regional_forecasts=[],
        resilience_state=resilience,
    )

    first = OperationalOrchestrationResilienceService.execute_agent_consensus_infrastructure(
        db,
        organization_id=org_id,
        actor_user_id="test-consensus-determinism",
        coordination_layer=layer,
        resilience_state=resilience,
    )
    second = OperationalOrchestrationResilienceService.execute_agent_consensus_infrastructure(
        db,
        organization_id=org_id,
        actor_user_id="test-consensus-determinism",
        coordination_layer=layer,
        resilience_state=resilience,
    )

    assert first.get("execution_count", 0) >= second.get("execution_count", 0)
    assert second.get("denial_count", 0) >= 0


def test_recovery_conflict_prevention(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id, approval_required_decision_types=[])
    ride_id = str(uuid4())
    layer = {
        "agent_recommendations": [
            {
                "recommendation_id": str(uuid4()),
                "agent_id": "dispatch_intelligence_agent",
                "decision_type": "dispatch_orchestration",
                "action_key": f"dispatch:{ride_id}:a",
                "confidence": 0.9,
                "priority_score": 0.9,
                "risk_score": 0.9,
                "ride_id": ride_id,
                "payload": {"mode": "a"},
            },
            {
                "recommendation_id": str(uuid4()),
                "agent_id": "recovery_coordination_agent",
                "decision_type": "recovery_coordination",
                "action_key": f"recovery:{ride_id}:b",
                "confidence": 0.89,
                "priority_score": 0.89,
                "risk_score": 0.89,
                "ride_id": ride_id,
                "payload": {"mode": "b"},
            },
        ]
    }
    consensus = OperationalOrchestrationResilienceService.execute_agent_consensus_infrastructure(
        db,
        organization_id=org_id,
        actor_user_id="test-conflict-prevention",
        coordination_layer=layer,
        resilience_state={"state": "healthy"},
    )
    assert consensus.get("conflict_count", 0) >= 1


def test_orchestration_storm_suppression(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id, approval_required_decision_types=[])
    recommendations = []
    for idx in range(20):
        recommendations.append(
            {
                "recommendation_id": str(uuid4()),
                "agent_id": "dispatch_intelligence_agent",
                "decision_type": "dispatch_orchestration",
                "action_key": f"dispatch:storm:{idx}",
                "confidence": 0.92,
                "priority_score": 0.92,
                "risk_score": 0.92,
                "ride_id": None,
                "payload": {"idx": idx},
            }
        )
    consensus = OperationalOrchestrationResilienceService.execute_agent_consensus_infrastructure(
        db,
        organization_id=org_id,
        actor_user_id="test-storm-suppression",
        coordination_layer={"agent_recommendations": recommendations},
        resilience_state={"state": "healthy"},
    )
    assert consensus.get("execution_count", 0) <= 8
    assert any(str(item.get("reason") or "") == "orchestration_storm_suppression" for item in consensus.get("denied", []))


def test_simulation_consistency(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)
    forecasts = [
        {
            "prediction_type": "projected_dispatcher_overload",
            "projected_value": 3.2,
            "risk_score": 0.82,
        },
        {
            "prediction_type": "projected_sla_breach",
            "projected_value": 2.1,
            "risk_score": 0.74,
        },
    ]
    first = OperationalOrchestrationResilienceService.run_operational_simulation_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-sim-consistency",
        incidents=[],
        forecasts=forecasts,
        resilience_state={"state": "healthy"},
        recommendations=[],
    )
    second = OperationalOrchestrationResilienceService.run_operational_simulation_engine(
        db,
        organization_id=org_id,
        actor_user_id="test-sim-consistency",
        incidents=[],
        forecasts=forecasts,
        resilience_state={"state": "healthy"},
        recommendations=[],
    )
    assert first.get("simulations") == second.get("simulations")


def test_negotiation_stability(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id, approval_required_decision_types=[])
    layer = OperationalOrchestrationResilienceService.build_multi_agent_operational_coordination_layer(
        db,
        organization_id=org_id,
        actor_user_id="test-negotiation",
        escalations=[],
        recommendations=[
            {
                "recommendation_type": "recovery_reassignment_suggestion",
                "ride_id": str(uuid4()),
                "score": 0.92,
                "dedup_key": f"neg:{uuid4()}",
            }
        ],
        recovery_operations=[{"operation_type": "orphaned_ride_recovery", "ride_id": str(uuid4())}],
        proactive_recovery=[],
        forecasts=[],
        driver_reliability=[],
        regional_forecasts=[],
        resilience_state={"state": "healthy"},
    )
    consensus = OperationalOrchestrationResilienceService.execute_agent_consensus_infrastructure(
        db,
        organization_id=org_id,
        actor_user_id="test-negotiation",
        coordination_layer=layer,
        resilience_state={"state": "healthy"},
    )
    negotiation = OperationalOrchestrationResilienceService.execute_autonomous_negotiation_framework(
        db,
        organization_id=org_id,
        actor_user_id="test-negotiation",
        coordination_layer=layer,
        consensus=consensus,
    )
    assert negotiation.get("negotiation_count", 0) >= 1
    assert str(negotiation.get("stability") or "") in {"coordinated", "stable"}


def test_distributed_coordination_rebuild(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id, approval_required_decision_types=[])
    OperationalOrchestrationResilienceService.execute_automation_cycle(
        db,
        organization_id=org_id,
        incidents=[],
        actor_user_id="test-distributed-rebuild",
    )
    rebuild = OperationalOrchestrationResilienceService.replayable_distributed_coordination_rebuild(
        db,
        organization_id=org_id,
        limit=400,
    )
    assert rebuild.get("replay_safe") is True
    assert rebuild.get("sequence_ordered") is True


def test_degraded_state_consensus_recovery(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id, approval_required_decision_types=[])
    layer = OperationalOrchestrationResilienceService.build_multi_agent_operational_coordination_layer(
        db,
        organization_id=org_id,
        actor_user_id="test-degraded-consensus",
        escalations=[],
        recommendations=[],
        recovery_operations=[{"operation_type": "degraded_websocket_recovery_mode", "dedup_key": f"d:{uuid4()}"}],
        proactive_recovery=[{"operation_type": "resilience_preparation_before_degradation_state", "dedup_key": f"p:{uuid4()}"}],
        forecasts=[
            {
                "prediction_type": "projected_reconnect_instability",
                "risk_score": 0.78,
                "projected_value": 1.9,
                "threshold_exceeded": True,
            }
        ],
        driver_reliability=[],
        regional_forecasts=[],
        resilience_state={"state": "degraded"},
    )
    consensus = OperationalOrchestrationResilienceService.execute_agent_consensus_infrastructure(
        db,
        organization_id=org_id,
        actor_user_id="test-degraded-consensus",
        coordination_layer=layer,
        resilience_state={"state": "degraded"},
    )
    negotiation = OperationalOrchestrationResilienceService.execute_autonomous_negotiation_framework(
        db,
        organization_id=org_id,
        actor_user_id="test-degraded-consensus",
        coordination_layer=layer,
        consensus=consensus,
    )
    coordinated = OperationalOrchestrationResilienceService.execute_cross_agent_recovery_coordination(
        db,
        organization_id=org_id,
        actor_user_id="test-degraded-consensus",
        resilience_state={"state": "degraded"},
        autonomous_recovery_chain=[{"operation_type": "autonomous_recovery_stabilization_chain"}],
        consensus=consensus,
        negotiation=negotiation,
    )
    assert coordinated.get("coordinated_degraded_state_response") is True


def test_authenticated_orchestration_session(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)
    session = OperationalOrchestrationResilienceService.issue_authenticated_operational_session(
        db,
        organization_id=org_id,
        actor_user_id="authority-user",
        role="recovery_coordinator",
        requested_capabilities=["recovery.execute", "orchestration.activate", "snapshot.hydrate"],
    )
    validation = OperationalOrchestrationResilienceService.validate_authenticated_operational_session(
        db,
        organization_id=org_id,
        session_payload=session,
        required_capability="orchestration.activate",
    )
    assert validation.get("valid") is True


def test_supervised_execution_flow(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)
    session = OperationalOrchestrationResilienceService.issue_authenticated_operational_session(
        db,
        organization_id=org_id,
        actor_user_id="supervised-user",
        role="admin",
        requested_capabilities=["recovery.execute", "orchestration.activate", "rollback.execute"],
    )
    activation = OperationalOrchestrationResilienceService.activate_supervised_execution(
        db,
        organization_id=org_id,
        authority_session=session,
        action_type="recovery.execute",
        action_payload={"operation_type": "degraded_websocket_recovery_mode"},
        required_capability="recovery.execute",
        actor_user_id="supervised-user",
        risk_score=0.5,
        rollback_required=True,
    )
    assert activation.get("activated") is True
    assert activation.get("rollback_link")


def test_replay_safe_authority_validation(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)
    session = OperationalOrchestrationResilienceService.issue_authenticated_operational_session(
        db,
        organization_id=org_id,
        actor_user_id="replay-auth-user",
        role="admin",
        requested_capabilities=["orchestration.activate"],
    )
    session["signature"] = "tampered"
    validation = OperationalOrchestrationResilienceService.validate_authenticated_operational_session(
        db,
        organization_id=org_id,
        session_payload=session,
        required_capability="orchestration.activate",
    )
    assert validation.get("valid") is False
    assert "session_signature_invalid" in list(validation.get("reasons") or [])


def test_rollback_reconstruction(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)
    session = OperationalOrchestrationResilienceService.issue_authenticated_operational_session(
        db,
        organization_id=org_id,
        actor_user_id="rollback-user",
        role="admin",
        requested_capabilities=["recovery.execute", "orchestration.activate", "rollback.execute"],
    )
    OperationalOrchestrationResilienceService.activate_supervised_execution(
        db,
        organization_id=org_id,
        authority_session=session,
        action_type="recovery.execute",
        action_payload={"operation_type": "stale_workflow_repair"},
        required_capability="recovery.execute",
        actor_user_id="rollback-user",
        risk_score=0.4,
        rollback_required=True,
    )
    rebuild = OperationalOrchestrationResilienceService.replayable_authority_rebuild(
        db,
        organization_id=org_id,
        limit=200,
    )
    assert any(str(item.get("event_type") or "") == "orchestration.authority.execution.rollback_linked" for item in rebuild.get("events", []))


def test_operational_recovery_determinism(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)
    session = OperationalOrchestrationResilienceService.issue_authenticated_operational_session(
        db,
        organization_id=org_id,
        actor_user_id="determinism-user",
        role="recovery_coordinator",
        requested_capabilities=["recovery.execute", "orchestration.activate", "rollback.execute"],
    )
    actions = [{"decision_type": "recovery_coordination", "risk_score": 0.5, "payload": {"x": 1}}]
    first = OperationalOrchestrationResilienceService.execute_controlled_recovery_execution(
        db,
        organization_id=org_id,
        actor_user_id="determinism-user",
        authority_session=session,
        recovery_actions=actions,
    )
    second = OperationalOrchestrationResilienceService.execute_controlled_recovery_execution(
        db,
        organization_id=org_id,
        actor_user_id="determinism-user",
        authority_session=session,
        recovery_actions=actions,
    )
    assert first.get("execution_count") == second.get("execution_count")


def test_policy_enforcement_consistency(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)
    dispatcher_session = OperationalOrchestrationResilienceService.issue_authenticated_operational_session(
        db,
        organization_id=org_id,
        actor_user_id="dispatcher-user",
        role="dispatcher",
        requested_capabilities=["dispatch.execute"],
    )
    activation = OperationalOrchestrationResilienceService.activate_supervised_execution(
        db,
        organization_id=org_id,
        authority_session=dispatcher_session,
        action_type="recovery.execute",
        action_payload={"operation_type": "orphaned_ride_recovery"},
        required_capability="recovery.execute",
        actor_user_id="dispatcher-user",
        risk_score=0.3,
        rollback_required=True,
    )
    assert activation.get("activated") is False
    denied = activation.get("denied") or {}
    assert str(denied.get("reason") or "") == "authority_validation_failed"


def test_degraded_reconnect_authenticated_hydration_restoration(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)
    cycle = OperationalOrchestrationResilienceService.execute_automation_cycle(
        db,
        organization_id=org_id,
        incidents=[
            {
                "incident_type": "websocket_disconnect_degradation_alert",
                "incident_key": f"hydration:{uuid4()}",
                "severity": "high",
                "message": "degraded reconnect",
                "details": {},
                "role_targets": ["command-center"],
            }
        ],
        actor_user_id="hydration-user",
    )
    authority = (cycle.get("controlled_authenticated_operational_authority") or {}).get("authenticated_orchestration_session") or {}
    hydration = OperationalOrchestrationResilienceService.run_authenticated_hydration_recovery(
        db,
        organization_id=org_id,
        actor_user_id="hydration-user",
        authority_session=authority,
    )
    assert hydration.get("hydrated") is True
    assert hydration.get("replay_safe") is True


def test_execution_audit_integrity(db) -> None:
    org_id = _seed_isolated_org(db)
    _seed_policy(db, org_id)
    cycle = OperationalOrchestrationResilienceService.execute_automation_cycle(
        db,
        organization_id=org_id,
        incidents=[],
        actor_user_id="audit-integrity-user",
    )
    authority = (cycle.get("controlled_authenticated_operational_authority") or {}).get("authenticated_orchestration_session") or {}
    distributed = cycle.get("replayable_distributed_coordination_rebuild") or {}
    integrity = OperationalOrchestrationResilienceService.validate_runtime_integrity_protection(
        db,
        organization_id=org_id,
        actor_user_id="audit-integrity-user",
        authority_session=authority,
        distributed_rebuild=distributed,
    )
    assert integrity.get("deterministic") is True
    rebuild = OperationalOrchestrationResilienceService.replayable_authority_rebuild(
        db,
        organization_id=org_id,
        limit=400,
    )
    assert rebuild.get("append_only") is True
    assert rebuild.get("sequence_ordered") is True
