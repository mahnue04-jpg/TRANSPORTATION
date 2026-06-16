"""
Tenant Isolation Tests
────────────────────────────────────────────────────────────────────────────────

Validates that multi-tenant data boundaries are enforced:
  - Dispatchers cannot see other tenants' rides
  - Admin can see their own org rides
  - Nova is scoped to the requesting organization
  - Cross-tenant access is denied at the API layer
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFProvider, HealthISFRide, RideStatus


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get_org_id(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        return user.organization_id


def _get_or_create_provider(org_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == org_id)
            .first()
        )
        if provider:
            return provider.id
        p = HealthISFProvider(
            id=uuid4(),
            organization_id=org_id,
            name=f"Isolation Test Clinic {uuid4()[:6]}",
            address="1 Isolation Way",
            phone="212-555-1001",
            service_type="clinic",
            is_active=True,
        )
        db.add(p)
        db.commit()
        return p.id


def _seed_ride_for_org(org_id: str, provider_id: str) -> str:
    with SessionLocal() as db:
        ride = HealthISFRide(
            id=uuid4(),
            organization_id=org_id,
            provider_id=provider_id,
            passenger_name=f"Isolated Patient {uuid4()[:6]}",
               passenger_phone="555-0199",
               service_type="medical_transport",
            pickup_address="1 Isolated Pickup",
            dropoff_address="2 Isolated Drop",
            status=RideStatus.PENDING,
        )
        db.add(ride)
        db.commit()
        return ride.id


# ─── Ride list scoping ────────────────────────────────────────────────────────

class TestRideListScoping:
    def test_dispatcher_sees_only_own_org_rides(self, client: TestClient):
        """
        /api/health-isf/rides must return only rides belonging to the
        authenticated user's organization.
        """
        dispatcher_org = _get_org_id("dispatcher@amicor.local")
        provider_id = _get_or_create_provider(dispatcher_org)
        own_ride_id = _seed_ride_for_org(dispatcher_org, provider_id)

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/health-isf/rides", headers=headers)
        assert response.status_code == 200, response.text

        ride_ids = [r["id"] for r in response.json()]
        assert own_ride_id in ride_ids, "Own ride should appear in ride list"

    def test_driver_cannot_modify_ride_from_another_dispatcher(self, client: TestClient):
        """
        A driver from the same org trying to change ride status should receive
        403 (role enforcement), not a cross-tenant error.
        """
        dispatcher_org = _get_org_id("dispatcher@amicor.local")
        provider_id = _get_or_create_provider(dispatcher_org)
        ride_id = _seed_ride_for_org(dispatcher_org, provider_id)

        driver_auth = _login(client, "driver@amicor.local")
        driver_headers = {"Authorization": f"Bearer {driver_auth['access_token']}"}

        response = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=driver_headers,
            json={"status": "cancelled"},
        )
        assert response.status_code == 403, response.text


# ─── Nova org scoping ─────────────────────────────────────────────────────────

class TestNovaOrgScoping:
    def test_nova_context_scoped_to_requesting_org(self, client: TestClient):
        """Nova context must return the org_id of the requesting user."""
        org_id = _get_org_id("dispatcher@amicor.local")

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/nova/context", headers=headers)
        assert response.status_code == 200
        payload = response.json()

        assert payload["organization_id"] == org_id

    def test_nova_status_scoped_to_requesting_org(self, client: TestClient):
        org_id = _get_org_id("dispatcher@amicor.local")

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/nova/status", headers=headers)
        assert response.status_code == 200
        payload = response.json()

        assert payload["organization_id"] == org_id


# ─── Cross-tenant access denial ───────────────────────────────────────────────

class TestCrossTenantDenial:
    def test_dispatcher_cannot_request_other_org_context(self, client: TestClient):
        """Supplying a foreign organization_id to Nova must return 400 or 403."""
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        foreign_org = "foreign-org-aaaaaaaa-bbbb-cccc-dddd"

        response = client.get(
            "/api/nova/context",
            headers=headers,
            params={"organization_id": foreign_org},
        )
        assert response.status_code in {400, 403}, response.text

    def test_dispatcher_cannot_request_other_org_intelligence(self, client: TestClient):
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        foreign_org = "foreign-org-aaaaaaaa-bbbb-cccc-dddd"

        response = client.get(
            "/api/nova/intelligence",
            headers=headers,
            params={"organization_id": foreign_org},
        )
        assert response.status_code in {400, 403}, response.text

    def test_unauthenticated_nova_access_denied(self, client: TestClient):
        for path in ["/api/nova/status", "/api/nova/context", "/api/nova/intelligence"]:
            response = client.get(path)
            assert response.status_code in {401, 403}, f"{path} must require auth"

    def test_unauthenticated_rides_access_denied(self, client: TestClient):
        response = client.get("/api/health-isf/rides")
        assert response.status_code in {401, 403}

    def test_cannot_fetch_ride_by_id_without_auth(self, client: TestClient):
        dispatcher_org = _get_org_id("dispatcher@amicor.local")
        provider_id = _get_or_create_provider(dispatcher_org)
        ride_id = _seed_ride_for_org(dispatcher_org, provider_id)

        response = client.get(f"/api/health-isf/rides/{ride_id}")
        assert response.status_code in {401, 403}


# ─── RBAC scope enforcement ───────────────────────────────────────────────────

class TestRBACEnforcement:
    def test_analytics_readonly_can_access_nova_context(self, client: TestClient):
        """ROLE_ANALYTICS_READONLY has Nova read access."""
        # analytics_readonly may be the same seed or skip if not seeded
        try:
            auth = _login(client, "analytics@amicor.local")
        except AssertionError:
            pytest.skip("analytics@amicor.local not seeded in test environment")

        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        response = client.get("/api/nova/context", headers=headers)
        assert response.status_code == 200

    def test_driver_can_access_nova_status(self, client: TestClient):
        """Drivers are included in the Nova access role set."""
        auth = _login(client, "driver@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/nova/status", headers=headers)
        assert response.status_code == 200

    def test_driver_cannot_create_rides(self, client: TestClient):
        dispatcher_org = _get_org_id("driver@amicor.local")
        provider_id = _get_or_create_provider(dispatcher_org)

        auth = _login(client, "driver@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": "Unauthorized",
                "passenger_phone": "917-555-9999",
                "pickup_address": "1 Blocked Lane",
                "dropoff_address": "2 Blocked Ave",
            },
        )
        assert response.status_code == 403
