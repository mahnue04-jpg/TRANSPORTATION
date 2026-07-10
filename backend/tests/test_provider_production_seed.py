from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.health_isf import service as health_isf_service
from app.modules.health_isf.models import HealthISFProvider


def test_list_providers_self_heals_when_missing(client: TestClient | None = None) -> None:
    ensure_auth_schema()
    seed_default_users()
    test_client = client or TestClient(app)

    auth = test_client.post(
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
        db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == org_id).delete()
        db.commit()

    response = test_client.get(f"/api/health-isf/providers?organization_id={org_id}", headers=headers)
    assert response.status_code == 200, response.text
    providers = response.json()
    assert isinstance(providers, list)
    assert len(providers) >= 4
    names = {item["name"] for item in providers}
    assert "Fairview Hospital" in names

    with SessionLocal() as db:
        summary = health_isf_service.ensure_sample_providers(db, organization_id=org_id)
        assert summary["total"] >= 3
