"""Casting sandbox uses the shared Nova account. No separate casting password."""
from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, verify_password
from app.db.models import User as UserModel
from app.db.session import SessionLocal
from app.helpers import now, uuid4
from app.main import app
from app.password_reset import PasswordResetToken
from app.password_reset_service import (
    clear_test_reset_capture,
    ensure_password_reset_schema,
    get_test_reset_token,
)


def _enable_sandbox(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_CASTING_STAGING_READS", "true")
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(name, "disposable")
    monkeypatch.setenv("AMICOR_PASSWORD_RESET_TEST_CAPTURE", "1")
    for name in ("AUTH_SMTP_HOST", "AUTH_SMTP_FROM", "MARKETING_SMTP_HOST", "MARKETING_SMTP_FROM"):
        monkeypatch.delenv(name, raising=False)


def _ensure_casting_tables() -> None:
    from app.core.nova.creative_studio import casting_db_models
    from app.db.session import engine, init_platform_db

    init_platform_db()

    tables = [
        casting_db_models.NovaCastingOrganization.__table__,
        casting_db_models.NovaCastingMembership.__table__,
        casting_db_models.NovaCastingCampaign.__table__,
        casting_db_models.NovaCastingApplication.__table__,
        casting_db_models.NovaCastingReview.__table__,
        casting_db_models.NovaCastingMedia.__table__,
        casting_db_models.NovaCastingConsentEvent.__table__,
        casting_db_models.NovaCastingAuditEvent.__table__,
    ]
    for table in tables:
        table.create(bind=engine, checkfirst=True)


def _client() -> TestClient:
    ensure_auth_schema()
    ensure_password_reset_schema()
    _ensure_casting_tables()
    ensure_auth_schema()
    return TestClient(app)


def _password() -> str:
    return f"CastPass1!{uuid4()[:6]}"


def _signup(client: TestClient, *, label: str) -> dict:
    payload = {
        "business_name": f"Casting {label} {uuid4()[:6]}",
        "contact_name": "Casting Owner",
        "email": f"casting.{label}.{uuid4()[:10]}@example.com",
        "phone": "6125550199",
        "industry": "creative",
        "password": _password(),
        "terms_accepted": True,
    }
    created = client.post("/api/nova/signup/free", json=payload)
    assert created.status_code == 200, created.text
    body = created.json()
    assert payload["password"] not in created.text
    assert "pbkdf2" not in created.text.lower()
    assert body["login_ready"] is True
    return payload


def _login(client: TestClient, payload: dict, password: str | None = None):
    return client.post(
        "/api/auth/login",
        json={"email": payload["email"], "password": password or payload["password"]},
    )


def test_new_account_signs_in_creates_org_and_signs_in_again(monkeypatch) -> None:
    _enable_sandbox(monkeypatch)
    client = _client()
    payload = _signup(client, label="new")
    first = _login(client, payload)
    assert first.status_code == 200, first.text
    token = first.json()["access_token"]
    refresh = first.json()["refresh_token"]
    assert payload["password"] not in first.text
    headers = {"Authorization": f"Bearer {token}"}

    readiness = client.get("/api/nova/casting/readiness", headers=headers)
    assert readiness.status_code == 200, readiness.text
    ready = readiness.json()
    assert ready["enabled"] is False
    assert ready["applications_enabled"] is False
    assert ready["media_uploads_enabled"] is False
    assert ready["sandbox_writes_enabled"] is True

    created = client.post(
        "/api/nova/casting/sandbox/organization",
        headers=headers,
        json={"name": f"Studio {uuid4().replace('-', '')[:8]}"},
    )
    assert created.status_code == 200, created.text
    org_id = created.json()["id"]
    assert created.json()["casting_role"] == "organizer"

    logged_out = client.post("/api/auth/logout", json={"refresh_token": refresh})
    assert logged_out.status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": refresh}).status_code == 401

    second = _login(client, payload)
    assert second.status_code == 200, second.text
    again = {"Authorization": f"Bearer {second.json()['access_token']}"}
    mine = client.get(f"/api/nova/casting/organizations/{org_id}/campaigns", headers=again)
    assert mine.status_code == 200, mine.text

    other_payload = _signup(client, label="other")
    other_login = _login(client, other_payload)
    assert other_login.status_code == 200, other_login.text
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
    denied = client.get(f"/api/nova/casting/organizations/{org_id}/campaigns", headers=other_headers)
    assert denied.status_code == 404
    assert denied.json()["detail"] == "Application unavailable"
    assert payload["email"] not in denied.text
    stolen = client.post(
        f"/api/nova/casting/organizations/{org_id}/campaigns",
        headers=other_headers,
        json={"title": "Stolen", "category": "film", "minimum_age": 18, "status": "DRAFT"},
    )
    assert stolen.status_code == 404
    assert payload["email"] not in stolen.text


def test_existing_user_reset_rejects_expired_and_reused_tokens(monkeypatch) -> None:
    _enable_sandbox(monkeypatch)
    clear_test_reset_capture()
    client = _client()
    payload = _signup(client, label="reset")
    old_password = payload["password"]
    new_password = _password()

    missing = client.post("/api/auth/forgot-password", json={"email": "missing.casting@example.com"})
    asked = client.post("/api/auth/forgot-password", json={"email": payload["email"].upper()})
    assert missing.status_code == 200
    assert asked.json() == missing.json()
    assert "No message was sent" in asked.json()["message"]
    assert "have been sent" not in asked.text
    token = get_test_reset_token(payload["email"])
    assert token
    assert token not in asked.text
    assert old_password not in asked.text

    with SessionLocal() as db:
        row = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash != "").all()
        match = [item for item in row if item.email == payload["email"].lower()]
        assert len(match) == 1
        match[0].expires_at = now() - timedelta(minutes=1)
        db.commit()
    stale = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": new_password, "confirm_password": new_password},
    )
    assert stale.status_code == 400
    assert token not in stale.text
    assert "Invalid or expired" in stale.text

    clear_test_reset_capture()
    asked_again = client.post("/api/auth/forgot-password", json={"email": payload["email"]})
    assert asked_again.json() == missing.json()
    fresh = get_test_reset_token(payload["email"])
    assert fresh and fresh != token
    updated = client.post(
        "/api/auth/reset-password",
        json={"token": fresh, "new_password": new_password, "confirm_password": new_password},
    )
    assert updated.status_code == 200, updated.text
    assert fresh not in updated.text
    assert "Password updated" in updated.json()["message"]
    reused = client.post(
        "/api/auth/reset-password",
        json={"token": fresh, "new_password": new_password + "2", "confirm_password": new_password + "2"},
    )
    assert reused.status_code == 400
    assert _login(client, payload, old_password).status_code == 401
    signed_in = _login(client, payload, new_password)
    assert signed_in.status_code == 200, signed_in.text

    with SessionLocal() as db:
        user = db.query(UserModel).filter(UserModel.email == payload["email"].lower()).one()
        assert verify_password(new_password, user.hashed_password)
        assert not verify_password(old_password, user.hashed_password)
