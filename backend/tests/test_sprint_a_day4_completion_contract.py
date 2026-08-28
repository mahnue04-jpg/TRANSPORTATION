from fastapi.testclient import TestClient
import pytest

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import DriverStatus, HealthISFDriver, HealthISFProvider


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login_dispatcher(client: TestClient) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _dispatcher_org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
        assert user is not None
        assert user.organization_id is not None
        return str(user.organization_id)


def _ensure_provider(organization_id: str) -> str:
    with SessionLocal() as db:
        existing = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if existing:
            return str(existing.id)

        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Day4 Provider {uuid4()[:6]}",
            address="800 Day4 Ave",
            phone="212-555-6499",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _ensure_driver(organization_id: str) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Day4 Driver {uuid4()[:6]}",
            phone=f"212-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"D4-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            availability_state="available",
            is_online=True,
            auth_state="active",
            is_active=True,
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_customer_request(client: TestClient, headers: dict) -> dict:
    response = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": f"Day4 Rider {uuid4()[:6]}",
            "rider_phone": "+1 212-555-6410",
            "pickup_address": "100 Route Progress St",
            "dropoff_address": "200 Completion Ave",
            "ride_type": "healthcare",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _assign_trip(client: TestClient, headers: dict, request_id: str, driver_id: str, ride_id: str) -> str:
    from tests.health_isf_driver_test_helpers import ensure_ride_assigned_to_driver

    approve = client.post(f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve", headers=headers)
    assert approve.status_code == 200, approve.text
    ride_before = client.get(f"/api/health-isf/rides/{ride_id}", headers=headers)
    assert ride_before.status_code == 200, ride_before.text
    assigned = str(ride_before.json().get("driver_id") or "")
    if assigned != driver_id:
        if assigned:
            admin = client.post("/api/auth/login", json={"email": "admin@amicor.local", "password": SEED_PASSWORD})
            assert admin.status_code == 200, admin.text
            ensure_ride_assigned_to_driver(
                client,
                dispatcher_headers=headers,
                admin_headers={"Authorization": f"Bearer {admin.json()['access_token']}"},
                request_id=request_id,
                ride_id=ride_id,
                driver_id=driver_id,
            )
        else:
            assign = client.post(
                f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
                headers=headers,
                json={"driver_id": driver_id},
            )
            if assign.status_code != 200:
                raced = client.get(f"/api/health-isf/rides/{ride_id}", headers=headers)
                assigned_now = str((raced.json() or {}).get("driver_id") or "") if raced.status_code == 200 else ""
                assert assigned_now, assign.text
    ride_after = client.get(f"/api/health-isf/rides/{ride_id}", headers=headers)
    assert ride_after.status_code == 200, ride_after.text
    actual = str(ride_after.json().get("driver_id") or "")
    assert actual, "expected a bound driver after assign/auto-dispatch"
    return actual


def test_route_progress_rejects_arrived_destination_before_in_progress(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEALTH_ISF_AUTO_DISPATCH_ENABLED", "0")
    monkeypatch.setattr(
        "app.modules.health_isf.service._is_intake_auto_dispatch_enabled",
        lambda db, organization_id: False,
    )
    monkeypatch.setattr(
        "app.modules.health_isf.routes._schedule_customer_request_side_effects",
        lambda **kwargs: None,
    )
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    _ensure_provider(org_id)
    driver_id = _ensure_driver(org_id)

    req = _create_customer_request(client, headers)
    driver_id = _assign_trip(client, headers, req["id"], driver_id, req["ride_id"])

    illegal = client.post(
        f"/api/health-isf/drivers/{driver_id}/route-progress",
        headers=headers,
        json={"ride_id": req["ride_id"], "target_state": "arrived_destination"},
    )
    assert illegal.status_code == 409, illegal.text


def test_billing_completed_handoff_artifact_and_downstream_queue_readiness(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEALTH_ISF_AUTO_DISPATCH_ENABLED", "0")
    monkeypatch.setattr(
        "app.modules.health_isf.service._is_intake_auto_dispatch_enabled",
        lambda db, organization_id: False,
    )
    monkeypatch.setattr(
        "app.modules.health_isf.routes._schedule_customer_request_side_effects",
        lambda **kwargs: None,
    )
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    provider_id = _ensure_provider(org_id)
    driver_id = _ensure_driver(org_id)

    req = _create_customer_request(client, headers)
    driver_id = _assign_trip(client, headers, req["id"], driver_id, req["ride_id"])

    for state in ["en_route_pickup", "arrived_pickup", "rider_loaded", "trip_in_progress", "arrived_destination", "completed"]:
        step = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=headers,
            json={"ride_id": req["ride_id"], "target_state": state},
        )
        assert step.status_code == 200, step.text

    handoff = client.get(f"/api/health-isf/rides/{req['ride_id']}/completion-handoff", headers=headers)
    assert handoff.status_code == 200, handoff.text
    payload = handoff.json()
    assert payload["completed"] is True
    assert payload["completion_artifact_id"]
    assert payload["trip_id"]
    assert payload["payout_id"]
    assert payload["provider_queue_ready"] is True
    assert payload["billing_queue_ready"] is True

    ride = client.get(f"/api/health-isf/rides/{req['ride_id']}", headers=headers)
    assert ride.status_code == 200, ride.text
    provider_id = str(ride.json().get("provider_id") or provider_id)

    provider_queue = client.get(
        f"/api/health-isf/providers/{provider_id}/transport-queue",
        headers=headers,
        params={"include_completed": True},
    )
    assert provider_queue.status_code == 200, provider_queue.text
    items = provider_queue.json().get("items", [])
    assert any(str(item.get("ride_id")) == req["ride_id"] for item in items)
