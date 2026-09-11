"""Helpers for isolated Lifesaver Care Cloud tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, hash_password
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.modules.lifesaver.constants import CONSENT_TYPES
from app.modules.lifesaver.models import ensure_lifesaver_schema


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    return headers(login(client, email)["access_token"])


def grant_consents(client: TestClient, token_headers: dict[str, str], types: tuple[str, ...] | None = None) -> None:
    ensure_lifesaver_schema()
    for consent_type in types or CONSENT_TYPES:
        response = client.post(
            "/api/lifesaver/consents",
            headers=token_headers,
            json={"consent_type": consent_type, "granted": True},
        )
        assert response.status_code == 200, response.text


def bootstrap_profile(client: TestClient, token_headers: dict[str, str]) -> dict:
    response = client.get("/api/lifesaver/me", headers=token_headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def create_other_org_user(email: str = "lifesaver.other@example.local") -> str:
    org_id = uuid4()
    with SessionLocal() as db:
        existing = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        if existing:
            existing.organization_id = org_id
            existing.hashed_password = hash_password(SEED_PASSWORD)
            existing.is_active = True
            db.commit()
            return existing.organization_id
        user = PlatformUser(
            email=email,
            hashed_password=hash_password(SEED_PASSWORD),
            display_name="Lifesaver Other Org",
            role="rider",
            organization_id=org_id,
            organization_name="Lifesaver Other Org",
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.commit()
        return org_id
