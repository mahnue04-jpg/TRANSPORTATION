"""Signup login survives a stage-store restart. Stale tokens stay rejected.

The isolated preview has no DATABASE_URL and no JWT_SECRET. Accounts and the
signing key must live in the durable auth store, and a later signup must not
replace a password that already belongs to that login identity.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.helpers import uuid4

BACKEND = Path(__file__).resolve().parents[1]
STORE_NAME = "auth-store"
TOKEN_NAME = "session.token"


def _password() -> str:
    return f"Restart1!{uuid4()[:8]}"


def _child_env(store: Path, email: str, password: str) -> dict[str, str]:
    env = os.environ.copy()
    for name in ("DATABASE_URL", "DB_FILENAME", "JWT_SECRET", "SECRET_KEY"):
        env.pop(name, None)
    env["AMICOR_AUTH_STORE_DIR"] = str(store)
    env["AMICOR_TEST_EMAIL"] = email
    env["AMICOR_TEST_PASSWORD"] = password
    env["TESTING"] = "true"
    env["PYTHONPATH"] = str(BACKEND)
    return env


def _run_child(store: Path, email: str, password: str, mode: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), mode],
        cwd=str(BACKEND),
        env=_child_env(store, email, password),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "")[-2000:]
        raise AssertionError(f"{mode} child failed: {tail}")
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    assert lines, completed.stdout[-500:]
    return json.loads(lines[-1])


def test_signup_login_survives_stage_restart_and_rejects_stale_token(tmp_path: Path) -> None:
    store = tmp_path / STORE_NAME
    email = f"restart.{uuid4()[:10]}@example.invalid"
    password = _password()
    created = _run_child(store, email, password, "setup")
    assert created["signup"] == 200, {key: created.get(key) for key in ("signup", "detail", "login")}
    assert created["login_ready"] is True
    assert created["login"] == 200
    assert created["readiness"] == 200
    assert created["enabled"] is False
    assert created["auth_store"]["durable"] is True
    assert created["auth_store"]["location"] == "configured-directory"
    assert created["auth_store"]["signing_key"] == "durable-file"
    assert (store / ".signing_key").is_file()
    assert (store / TOKEN_NAME).is_file()

    restarted = _run_child(store, email, password, "restart")
    assert restarted["existing_login"] == 200
    assert restarted["saved_token_readiness"] == 200
    assert restarted["tampered_token"] == 401
    assert restarted["stale_auth_version"] == 401
    assert restarted["stale_detail"] == "Session invalidated"
    assert restarted["login_after_stale"] == 200
    assert restarted["duplicate_signup"] == 409
    assert restarted["login_after_duplicate"] == 200
    assert restarted["replacement_login"] == 401


def test_pending_signup_cannot_replace_an_existing_login_password() -> None:
    from fastapi.testclient import TestClient

    from app.auth import ensure_auth_schema, hash_password, verify_password
    from app.core.nova.signup.service import SignupError, create_signup
    from app.db.models import User as UserModel
    from app.db.session import SessionLocal, init_platform_db
    from app.main import app

    init_platform_db()
    ensure_auth_schema()
    email = f"pending.{uuid4()[:10]}@example.invalid"
    original = _password()
    replacement = _password()
    with SessionLocal() as db:
        create_signup(
            db,
            business_name="Pending Studio",
            contact_name="Pending Owner",
            email=email,
            phone="5550101",
            industry="creative",
            password=original,
            terms_accepted=True,
        )
        db.add(
            UserModel(
                email=email,
                hashed_password=hash_password(original),
                display_name="Pending Owner",
                role="admin",
                is_active=True,
                is_verified=True,
            )
        )
        db.commit()

    with SessionLocal() as db:
        try:
            create_signup(
                db,
                business_name="Pending Studio",
                contact_name="Pending Owner",
                email=email,
                phone="5550101",
                industry="creative",
                password=replacement,
                terms_accepted=True,
            )
        except SignupError as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("duplicate signup replaced an existing login")
        user = db.query(UserModel).filter(UserModel.email == email).one()
        signup_hash = user.hashed_password
        assert verify_password(original, signup_hash)
        assert not verify_password(replacement, signup_hash)

    client = TestClient(app)
    kept = client.post("/api/auth/login", json={"email": email, "password": original})
    rejected = client.post("/api/auth/login", json={"email": email, "password": replacement})
    assert kept.status_code == 200
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "Invalid email or password"


def _client():
    from fastapi.testclient import TestClient

    from app.auth import ensure_auth_schema
    from app.db.session import init_platform_db
    from app.main import app

    init_platform_db()
    ensure_auth_schema()
    return TestClient(app)


def _setup() -> dict:
    email = os.environ["AMICOR_TEST_EMAIL"]
    password = os.environ["AMICOR_TEST_PASSWORD"]
    client = _client()
    signup = client.post(
        "/api/nova/signup/free",
        json={
            "business_name": "Restart Studio",
            "contact_name": "Restart Owner",
            "email": email,
            "phone": "5550102",
            "industry": "creative",
            "password": password,
            "terms_accepted": True,
        },
    )
    raw = signup.text.replace(password, "[redacted]")
    try:
        body = signup.json()
    except Exception:
        body = {}
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    if signup.status_code != 200:
        return {"signup": signup.status_code, "detail": str(body.get("detail") or raw)[:240]}
    token = login.json().get("access_token", "")
    token_path = Path(os.environ["AMICOR_AUTH_STORE_DIR"]) / TOKEN_NAME
    token_path.write_text(token, encoding="ascii")
    os.chmod(token_path, 0o600)
    readiness = client.get("/api/nova/casting/readiness", headers={"Authorization": f"Bearer {token}"})
    status = client.get("/api/auth/deployment/seed-status")
    return {
        "signup": signup.status_code,
        "login_ready": body.get("login_ready"),
        "login": login.status_code,
        "readiness": readiness.status_code,
        "enabled": (readiness.json() or {}).get("enabled") if readiness.status_code == 200 else None,
        "auth_store": (status.json() or {}).get("auth_store"),
    }


def _restart() -> dict:
    email = os.environ["AMICOR_TEST_EMAIL"]
    password = os.environ["AMICOR_TEST_PASSWORD"]
    replacement = _password()
    client = _client()
    token = (Path(os.environ["AMICOR_AUTH_STORE_DIR"]) / TOKEN_NAME).read_text(encoding="ascii")
    existing = client.post("/api/auth/login", json={"email": email, "password": password})
    saved = client.get("/api/nova/casting/readiness", headers={"Authorization": f"Bearer {token}"})
    tampered = client.get("/api/nova/casting/readiness", headers={"Authorization": f"Bearer {token}x"})
    from app.db.models import User as UserModel
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        user = db.query(UserModel).filter(UserModel.email == email).one()
        user.auth_version = int(user.auth_version or 0) + 1
        db.commit()
    stale = client.get("/api/nova/casting/readiness", headers={"Authorization": f"Bearer {token}"})
    resigned = client.post("/api/auth/login", json={"email": email, "password": password})
    duplicate = client.post(
        "/api/nova/signup/free",
        json={
            "business_name": "Restart Studio",
            "contact_name": "Restart Owner",
            "email": email,
            "phone": "5550102",
            "industry": "creative",
            "password": replacement,
            "terms_accepted": True,
        },
    )
    after = client.post("/api/auth/login", json={"email": email, "password": password})
    replaced = client.post("/api/auth/login", json={"email": email, "password": replacement})
    return {
        "existing_login": existing.status_code,
        "saved_token_readiness": saved.status_code,
        "tampered_token": tampered.status_code,
        "stale_auth_version": stale.status_code,
        "stale_detail": (stale.json() or {}).get("detail"),
        "login_after_stale": resigned.status_code,
        "duplicate_signup": duplicate.status_code,
        "login_after_duplicate": after.status_code,
        "replacement_login": replaced.status_code,
    }


if __name__ == "__main__":
    mode = sys.argv[1]
    payload = _setup() if mode == "setup" else _restart()
    print(json.dumps(payload))
