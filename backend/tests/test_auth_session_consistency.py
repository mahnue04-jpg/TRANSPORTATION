"""Platform JWT and driver operational session consistency."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import DriverStatus, HealthISFDriver


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_platform_login_me_and_dispatch_share_org_scope() -> None:
    client = _client()
    headers = _login(client, "dispatcher@amicor.local")
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    org_id = me.json()["organization_id"]
    queue = client.get("/api/health-isf/dispatch/queue", headers=headers, params={"limit": 20})
    assert queue.status_code == 200, queue.text
    assert isinstance(queue.json(), list)
    assert me.json()["organization_id"] == org_id


def test_driver_login_clears_stale_on_trip_without_active_assignment() -> None:
    client = _client()
    headers = _login(client, "dispatcher@amicor.local")
    with SessionLocal() as db:
        maria = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.name.ilike("Maria Garcia"))
            .first()
        )
        assert maria is not None
        maria.availability_state = "on_trip"
        maria.status = DriverStatus.EN_ROUTE_PICKUP
        maria.auth_state = "active"
        maria.is_online = True
        db.commit()
        driver_id = str(maria.id)
        phone = str(maria.phone)

    login = client.post(
        "/api/health-isf/drivers/login",
        headers=headers,
        json={"driver_id": driver_id, "phone": phone},
    )
    assert login.status_code == 200, login.text

    with SessionLocal() as db:
        refreshed = db.query(HealthISFDriver).filter(HealthISFDriver.id == driver_id).first()
        assert refreshed is not None
        assert str(refreshed.availability_state) == "available"
        assert hs._coerce_driver_status(refreshed.status) == DriverStatus.AVAILABLE
        assert hs._driver_active_workload_count(db, driver_id) == 0
