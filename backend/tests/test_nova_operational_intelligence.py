"""
Nova Operational Intelligence Tests
────────────────────────────────────────────────────────────────────────────────

Validates the NovaIntelligenceEngine:
  - deployment readiness scoring
  - operational health scoring
  - workflow bottleneck detection
  - stale ride detection
  - overloaded driver detection
  - provider imbalance detection
  - recommended actions
  - full intelligence report endpoint
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.intelligence import NovaIntelligenceEngine
from app.db.session import SessionLocal
from app.helpers import uuid4, now
from app.main import app
from app.modules.health_isf.models import (
    DriverStatus,
    HealthISFDriver,
    HealthISFOrganization,
    HealthISFProvider,
    HealthISFRide,
    RideStatus,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get_org_id() -> str:
    from app.db.models import User as PlatformUser
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(
            PlatformUser.email == "dispatcher@amicor.local"
        ).first()
        assert user is not None
        return user.organization_id


# ─── Unit tests (direct engine calls) ─────────────────────────────────────────

class TestDeploymentReadinessScoring:
    def test_score_returns_expected_keys(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            result = NovaIntelligenceEngine.score_deployment_readiness(db, org_id)

        assert "score" in result
        assert "label" in result
        assert "criteria" in result
        assert "blockers" in result
        assert "recommendation" in result

    def test_score_is_bounded_0_to_100(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            result = NovaIntelligenceEngine.score_deployment_readiness(db, org_id)

        assert 0 <= result["score"] <= 100

    def test_label_is_valid(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            result = NovaIntelligenceEngine.score_deployment_readiness(db, org_id)

        valid_labels = {"production_ready", "staging_ready", "development_only", "not_ready"}
        assert result["label"] in valid_labels

    def test_criteria_each_have_required_fields(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            result = NovaIntelligenceEngine.score_deployment_readiness(db, org_id)

        for criterion in result["criteria"]:
            assert "name" in criterion
            assert "passed" in criterion
            assert "weight" in criterion
            assert isinstance(criterion["passed"], bool)


class TestOperationalHealthScoring:
    def test_score_returns_expected_keys(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            result = NovaIntelligenceEngine.score_operational_health(db, org_id)

        assert "score" in result
        assert "label" in result
        assert "indicators" in result

    def test_score_is_bounded(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            result = NovaIntelligenceEngine.score_operational_health(db, org_id)

        assert 0 <= result["score"] <= 100

    def test_indicators_have_healthy_flag(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            result = NovaIntelligenceEngine.score_operational_health(db, org_id)

        for indicator in result["indicators"]:
            assert "healthy" in indicator
            assert isinstance(indicator["healthy"], bool)


class TestBottleneckDetection:
    def test_returns_list(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            bottlenecks = NovaIntelligenceEngine.detect_workflow_bottlenecks(db, org_id)

        assert isinstance(bottlenecks, list)

    def test_bottleneck_items_have_required_fields(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            bottlenecks = NovaIntelligenceEngine.detect_workflow_bottlenecks(db, org_id)

        for b in bottlenecks:
            assert "type" in b
            assert "severity" in b
            assert "action" in b
            assert b["severity"] in {"high", "medium", "low"}


class TestStaleRideDetection:
    def test_returns_list(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            stale = NovaIntelligenceEngine.detect_stale_rides(db, org_id)

        assert isinstance(stale, list)

    def test_stale_ride_items_have_ride_id(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            # Seed a stale ride
            from datetime import datetime, timezone, timedelta
            old_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
            provider = db.query(HealthISFProvider).filter(
                HealthISFProvider.organization_id == org_id
            ).first()
            if provider:
                ride = HealthISFRide(
                    id=uuid4(),
                    organization_id=org_id,
                    provider_id=provider.id,
                    passenger_name="Stale Patient",
                    passenger_phone="555-0000",
                    pickup_address="1 Stale St",
                    dropoff_address="2 Stale Ave",
                    service_type="medical_transport",
                    status=RideStatus.IN_TRANSIT,
                    requested_at=old_time,
                    updated_at=old_time,
                )
                db.add(ride)
                db.commit()

            stale = NovaIntelligenceEngine.detect_stale_rides(db, org_id, minutes=30)

        for item in stale:
            assert "ride_id" in item
            assert "status" in item
            assert "age_minutes" in item


class TestOverloadedDriverDetection:
    def test_returns_list(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            overloaded = NovaIntelligenceEngine.detect_overloaded_drivers(db, org_id)

        assert isinstance(overloaded, list)

    def test_overloaded_items_have_driver_id(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            overloaded = NovaIntelligenceEngine.detect_overloaded_drivers(db, org_id)

        for item in overloaded:
            assert "driver_id" in item
            assert "active_ride_count" in item


class TestProviderImbalanceDetection:
    def test_returns_list(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            imbalance = NovaIntelligenceEngine.detect_provider_imbalance(db, org_id)

        assert isinstance(imbalance, list)


class TestRecommendedActions:
    def test_returns_non_empty_list(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            actions = NovaIntelligenceEngine.build_recommended_actions(db, org_id)

        assert isinstance(actions, list)
        assert len(actions) >= 1

    def test_actions_have_required_fields(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            actions = NovaIntelligenceEngine.build_recommended_actions(db, org_id)

        for action in actions:
            assert "priority" in action
            assert "category" in action
            assert "action" in action
            assert "urgency" in action

    def test_actions_sorted_by_priority_descending(self):
        with SessionLocal() as db:
            org_id = _get_org_id()
            actions = NovaIntelligenceEngine.build_recommended_actions(db, org_id)

        priorities = [a["priority"] for a in actions]
        assert priorities == sorted(priorities, reverse=True)


# ─── API endpoint tests ────────────────────────────────────────────────────────

class TestNovaIntelligenceEndpoint:
    def test_intelligence_endpoint_returns_200(self, client: TestClient):
        auth = _login(client)
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/nova/intelligence", headers=headers)
        assert response.status_code == 200, response.text

    def test_intelligence_response_has_composite_score(self, client: TestClient):
        auth = _login(client)
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/nova/intelligence", headers=headers)
        payload = response.json()

        assert "composite_score" in payload
        assert "composite_label" in payload
        assert 0 <= payload["composite_score"] <= 100

    def test_intelligence_response_has_all_sections(self, client: TestClient):
        auth = _login(client)
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/nova/intelligence", headers=headers)
        payload = response.json()

        for key in [
            "deployment_readiness",
            "operational_health",
            "workflow_bottlenecks",
            "stale_rides",
            "overloaded_drivers",
            "provider_imbalance",
            "recommended_actions",
            "summary",
        ]:
            assert key in payload, f"Missing key: {key}"

    def test_intelligence_requires_auth(self, client: TestClient):
        response = client.get("/api/nova/intelligence")
        assert response.status_code in {401, 403}


class TestNovaDeploymentReadinessEndpoint:
    def test_deployment_readiness_endpoint_returns_report(self, client: TestClient):
        auth = _login(client)
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/nova/deployment-readiness", headers=headers)
        # Returns 200 regardless of readiness status (the status is in the payload)
        assert response.status_code == 200, response.text
        payload = response.json()

        assert "overall_status" in payload
        assert "score" in payload
        assert "environment" in payload
        assert "config_checks" in payload
        assert "recommendations" in payload

    def test_deployment_readiness_requires_auth(self, client: TestClient):
        response = client.get("/api/nova/deployment-readiness")
        assert response.status_code in {401, 403}
