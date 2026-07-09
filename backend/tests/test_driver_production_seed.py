from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.health_isf import service as health_isf_service
from app.modules.health_isf.models import HealthISFDriver


def test_list_drivers_self_heals_when_missing() -> None:
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    auth = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    )
    assert auth.status_code == 200, auth.text
    token = auth.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
        assert user is not None
        org_id = user.organization_id
        assert org_id is not None
        db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org_id).delete()
        db.commit()

    response = client.get(f"/api/health-isf/drivers?organization_id={org_id}", headers=headers)
    assert response.status_code == 200, response.text
    drivers = response.json()
    assert isinstance(drivers, list)
    assert len(drivers) >= 3
    names = {item["name"] for item in drivers}
    assert {"James Smith", "Maria Garcia", "David Chen"}.issubset(names)

    with SessionLocal() as db:
        summary = health_isf_service.ensure_sample_drivers(db, organization_id=org_id)
        assert summary["total"] >= 3
