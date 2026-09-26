"""Customer forgot/reset password. Never exposes whether an email exists."""
from __future__ import annotations

import os
from datetime import timedelta

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users, verify_password
from app.db.models import User as UserModel
from app.db.session import SessionLocal
from app.helpers import now, uuid4
from app.main import app
from app.password_reset import PasswordResetToken
from app.password_reset_service import (
    clear_test_reset_capture,
    ensure_password_reset_schema,
    get_test_reset_token,
    hash_reset_token,
)


def _client() -> TestClient:
    ensure_auth_schema()
    ensure_password_reset_schema()
    seed_default_users()
    return TestClient(app)


def _password() -> str:
    return f"FreePass1!{uuid4()[:6]}"


def _free_signup(client: TestClient) -> dict:
    payload = {
        "business_name": f"Free Reset Co {uuid4()[:8]}",
        "contact_name": "Free Owner",
        "email": f"free.reset.{uuid4()[:10]}@example.com",
        "phone": "6125550100",
        "industry": "operations",
        "password": _password(),
        "terms_accepted": True,
    }
    created = client.post("/api/nova/signup/free", json=payload)
    assert created.status_code == 200, created.text
    return payload


def test_forgot_password_pages_and_generic_response(monkeypatch) -> None:
    monkeypatch.setenv("AMICOR_PASSWORD_RESET_TEST_CAPTURE", "1")
    clear_test_reset_capture()
    client = _client()
    assert client.get("/nova/forgot-password").status_code == 200
    assert client.get("/nova/reset-password").status_code == 200
    assert 'href="/nova/forgot-password"' in client.get("/nova").text

    missing = client.post("/api/auth/forgot-password", json={"email": "nobody-exists@example.com"})
    assert missing.status_code == 200, missing.text
    assert "If an account exists" in missing.json()["message"]
    assert get_test_reset_token("nobody-exists@example.com") is None

    payload = _free_signup(client)
    asked = client.post("/api/auth/forgot-password", json={"email": payload["email"].upper()})
    assert asked.status_code == 200, asked.text
    assert asked.json()["message"] == missing.json()["message"]
    assert asked.json()["email_delivery"] in {"config_required", "not_configured", "send_failed", "sent", "attempted"}
    token = get_test_reset_token(payload["email"])
    assert token
    assert token not in asked.text
    assert "pbkdf2" not in asked.text.lower()

    with SessionLocal() as db:
        rows = db.query(PasswordResetToken).filter(PasswordResetToken.email == payload["email"].lower()).all()
        assert len(rows) == 1
        assert rows[0].token_hash == hash_reset_token(token)
        assert rows[0].token_hash != token


def test_reset_token_expiry_single_use_and_password_swap(monkeypatch) -> None:
    monkeypatch.setenv("AMICOR_PASSWORD_RESET_TEST_CAPTURE", "1")
    clear_test_reset_capture()
    client = _client()
    payload = _free_signup(client)
    old_password = payload["password"]
    new_password = f"NewPass1!{uuid4()[:6]}"

    assert client.post(
        "/api/auth/login",
        json={"email": payload["email"], "password": old_password},
    ).status_code == 200

    with SessionLocal() as db:
        before = db.query(UserModel).filter(UserModel.email == payload["email"].lower()).one()
        before_snap = {
            "role": before.role,
            "organization_id": before.organization_id,
            "authorized_roles": before.authorized_roles,
            "is_active": before.is_active,
        }

    asked = client.post("/api/auth/forgot-password", json={"email": payload["email"]})
    assert asked.status_code == 200
    token = get_test_reset_token(payload["email"])
    assert token

    with SessionLocal() as db:
        row = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == hash_reset_token(token)).one()
        row.expires_at = now() - timedelta(minutes=1)
        db.commit()
    stale = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": new_password, "confirm_password": new_password},
    )
    assert stale.status_code == 400
    assert "Invalid or expired" in stale.text

    clear_test_reset_capture()
    asked2 = client.post("/api/auth/forgot-password", json={"email": payload["email"]})
    assert asked2.status_code == 200
    token2 = get_test_reset_token(payload["email"])
    assert token2

    mismatch = client.post(
        "/api/auth/reset-password",
        json={"token": token2, "new_password": new_password, "confirm_password": new_password + "x"},
    )
    assert mismatch.status_code == 400

    updated = client.post(
        "/api/auth/reset-password",
        json={"token": token2, "new_password": new_password, "confirm_password": new_password},
    )
    assert updated.status_code == 200, updated.text
    assert "Password updated" in updated.json()["message"]

    reused = client.post(
        "/api/auth/reset-password",
        json={"token": token2, "new_password": new_password + "2", "confirm_password": new_password + "2"},
    )
    assert reused.status_code == 400

    assert client.post(
        "/api/auth/login",
        json={"email": payload["email"], "password": old_password},
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": payload["email"], "password": new_password},
    ).status_code == 200

    with SessionLocal() as db:
        after = db.query(UserModel).filter(UserModel.email == payload["email"].lower()).one()
        assert {
            "role": after.role,
            "organization_id": after.organization_id,
            "authorized_roles": after.authorized_roles,
            "is_active": after.is_active,
        } == before_snap
        assert verify_password(new_password, after.hashed_password)
        assert not verify_password(old_password, after.hashed_password)
