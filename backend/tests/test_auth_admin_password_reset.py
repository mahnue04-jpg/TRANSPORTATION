"""Admin password reset: existing accounts only, hash-only update, no secret leakage."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as UserModel
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str, password: str = SEED_PASSWORD) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _user_snapshot(email: str) -> dict[str, object]:
    with SessionLocal() as db:
        row = db.query(UserModel).filter(UserModel.email == email).first()
        assert row is not None
        return {
            "role": row.role,
            "authorized_roles": row.authorized_roles,
            "session_role": row.session_role,
            "organization_id": row.organization_id,
            "organization_name": row.organization_name,
            "is_active": row.is_active,
            "is_verified": row.is_verified,
            "display_name": row.display_name,
            "hashed_password": row.hashed_password,
        }


def test_admin_reset_existing_account_only_and_preserves_identity() -> None:
    client = _client()
    admin = _login(client, "admin@amicor.local")
    target_email = f"reset-target-{uuid4()[:12]}@amicor.local"
    created = client.post(
        "/api/auth/register",
        json={
            "email": target_email,
            "password": "OldPass123!",
            "display_name": "Reset Target",
            "role": "staff",
        },
    )
    assert created.status_code == 201, created.text
    before = _user_snapshot(target_email)
    with SessionLocal() as db:
        user_count = db.query(UserModel).count()

    missing = client.post(
        "/api/auth/admin/reset-password",
        headers=admin,
        json={"email": "does-not-exist@amicor.local", "new_password": "NewPass123!"},
    )
    assert missing.status_code == 404, missing.text
    with SessionLocal() as db:
        assert db.query(UserModel).count() == user_count
        assert db.query(UserModel).filter(UserModel.email == "does-not-exist@amicor.local").first() is None

    reset = client.post(
        "/api/auth/admin/reset-password",
        headers=admin,
        json={"email": target_email.upper(), "new_password": "NewPass123!"},
    )
    assert reset.status_code == 200, reset.text
    body = reset.json()
    assert body == {"status": "ok", "email": target_email}
    lowered = reset.text.lower()
    assert "new_password" not in lowered
    assert "pbkdf2" not in lowered
    assert "hashed" not in lowered

    after = _user_snapshot(target_email)
    assert after["hashed_password"] != before["hashed_password"]
    assert str(after["hashed_password"]).startswith("pbkdf2$")
    for key in (
        "role",
        "authorized_roles",
        "session_role",
        "organization_id",
        "organization_name",
        "is_active",
        "is_verified",
        "display_name",
    ):
        assert after[key] == before[key], key

    assert client.post(
        "/api/auth/login",
        json={"email": target_email, "password": "OldPass123!"},
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": target_email, "password": "NewPass123!"},
    ).status_code == 200


def test_admin_reset_requires_admin_and_rejects_unauthenticated() -> None:
    client = _client()
    payload = {"email": "dispatcher@amicor.local", "new_password": "OtherPass123!"}
    assert client.post("/api/auth/admin/reset-password", json=payload).status_code == 401
    dispatcher = _login(client, "dispatcher@amicor.local")
    denied = client.post("/api/auth/admin/reset-password", headers=dispatcher, json=payload)
    assert denied.status_code == 403, denied.text
    after = _user_snapshot("dispatcher@amicor.local")
    assert after["role"] == "dispatcher"
    assert client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    ).status_code == 200


def test_admin_reset_does_not_change_other_seed_accounts() -> None:
    client = _client()
    admin = _login(client, "admin@amicor.local")
    created = client.post(
        "/api/auth/register",
        json={
            "email": f"reset-only-{uuid4()[:12]}@amicor.local",
            "password": "OnlyMine123!",
            "display_name": "Reset Only",
            "role": "staff",
        },
    )
    assert created.status_code == 201, created.text
    reset = client.post(
        "/api/auth/admin/reset-password",
        headers=admin,
        json={"email": created.json()["email"], "new_password": "ChangedOnly123!"},
    )
    assert reset.status_code == 200, reset.text
    assert client.post(
        "/api/auth/login",
        json={"email": "admin@amicor.local", "password": SEED_PASSWORD},
    ).status_code == 200
    assert client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    ).status_code == 200
