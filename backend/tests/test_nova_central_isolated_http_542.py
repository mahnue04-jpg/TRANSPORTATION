"""Isolated Central app acceptance using real auth and disposable SQLite.

No app.main lifecycle, deployment, production DB, real account or external call.
"""
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from app import auth
from app.db.models import User
from app.db.session import get_db

FILE = Path(__file__).resolve().parents[1] / "nova_central_isolated.py"
spec = importlib.util.spec_from_file_location("nova_central_isolated_http_test", FILE)
isolated = importlib.util.module_from_spec(spec)
spec.loader.exec_module(isolated)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    dbfile = tmp_path / "central-boot.sqlite"
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "test")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("NOVA_CENTRAL_ISOLATED_TEST", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(dbfile))
    monkeypatch.setenv("NOVA_CENTRAL_APPROVED_COMMIT", "a" * 40)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    monkeypatch.delenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", raising=False)
    monkeypatch.delenv("NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED", raising=False)

    engine = create_engine("sqlite:///" + str(dbfile), connect_args={"check_same_thread": False})
    # Provision only a disposable test account table BEFORE starting the app.
    User.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(
            id="owner-A", email="owner@example.invalid", hashed_password="not-a-real-password",
            role=auth.ROLE_ADMIN, authorized_roles=json.dumps([auth.ROLE_ADMIN]),
            session_role=auth.ROLE_ADMIN, organization_id="org-A",
            auth_version=0, is_active=True, is_verified=True,
        ))
        db.commit()

    writes = []
    def log_query(conn, cursor, statement, parameters, context, executemany):
        sql = statement.lstrip().upper()
        if sql.startswith(("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "CREATE ", "DROP ", "TRUNCATE ", "REPLACE ")):
            writes.append(sql.split(None, 1)[0])
    event.listen(engine, "before_cursor_execute", log_query)

    app = isolated.create_app()
    def test_session():
        with factory() as db:
            yield db
    # Override only the DATABASE session. Retain real JWT, persisted account,
    # role, active-state, auth-version and organization dependency behavior.
    app.dependency_overrides[get_db] = test_session
    yield app, factory, engine, writes
    app.dependency_overrides.clear()
    engine.dispose()


def _token(org="org-A", user="owner-A", version=0):
    return auth.create_access_token({
        "sub": user, "email": "owner@example.invalid",
        "role": "admin", "organization_id": org, "auth_version": version,
    })


def _get(app, token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    with TestClient(app) as client:
        return client.get("/api/nova/workspace/central/journeys", headers=headers)


def test_lifecycle_and_requests_never_write_or_seed(sandbox):
    app, factory, engine, writes = sandbox
    before = set(inspect(engine).get_table_names())
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/live").json()["mode"] == "isolated_readiness"
        assert client.post("/api/nova/workspace/central/journeys").status_code == 405
    assert _get(app, _token()).status_code == 404
    assert _get(app).status_code == 401
    after = set(inspect(engine).get_table_names())
    assert before == after == {"platform_users"}
    with factory() as db:
        assert db.query(User).count() == 1
    assert writes == []


def test_enabled_readiness_returns_only_empty_metadata(sandbox, monkeypatch):
    app, _, _, writes = sandbox
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    result = _get(app, _token())
    assert result.status_code == 200
    assert result.json() == {
        "mode": "read_only", "integration_status": "not_connected",
        "journeys": [], "approval_actions_enabled": False,
        "customer_data_connected": False,
    }
    assert result.headers["cache-control"] == "private, no-store"
    assert result.headers["vary"] == "Authorization, Cookie"
    assert writes == []


def test_foreign_tenant_claim_denied(sandbox, monkeypatch):
    app, _, _, writes = sandbox
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    assert _get(app, _token(org="org-B")).status_code == 403
    assert writes == []


def test_inactive_or_revoked_owner_denied(sandbox, monkeypatch):
    app, factory, _, writes = sandbox
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    with factory() as db:
        user = db.query(User).filter(User.id == "owner-A").one()
        user.auth_version = 1
        db.commit()
    writes.clear()  # Explicit fixture manipulation is not app behavior.
    assert _get(app, _token(version=0)).status_code == 401
    assert writes == []


def test_route_inventory_has_no_job_or_write_paths(sandbox):
    app, _, _, _ = sandbox
    paths = {(r.path, tuple(sorted(r.methods))) for r in app.routes if hasattr(r, "methods")}
    assert paths == {
        ("/health/live", ("GET",)),
        ("/api/nova/workspace/central/journeys", ("GET",)),
    }


def test_inactive_account_denied_without_application_writes(sandbox, monkeypatch):
    app, factory, _, writes = sandbox
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    with factory() as db:
        owner = db.query(User).filter(User.id == "owner-A").one()
        owner.is_active = False
        db.commit()
    writes.clear()
    assert _get(app, _token()).status_code == 401
    assert writes == []


def test_removed_owner_grant_denied_without_application_writes(sandbox, monkeypatch):
    app, factory, _, writes = sandbox
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    with factory() as db:
        owner = db.query(User).filter(User.id == "owner-A").one()
        owner.authorized_roles = json.dumps(["staff"])
        owner.session_role = "staff"
        db.commit()
    writes.clear()
    assert _get(app, _token()).status_code == 403
    assert writes == []


def test_cookie_session_auth_and_bearer_precedence(sandbox, monkeypatch):
    app, _, _, writes = sandbox
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    with TestClient(app) as client:
        client.cookies.set(auth.ADMIN_SESSION_COOKIE, _token())
        good = client.get("/api/nova/workspace/central/journeys")
        assert good.status_code == 200
        # A foreign signed bearer must not fall back to a valid owner cookie.
        wrong = client.get("/api/nova/workspace/central/journeys", headers={
            "Authorization": "Bearer " + _token(org="org-B"),
        })
        assert wrong.status_code == 403
        # An invalid bearer must not fall back to a valid owner cookie.
        invalid = client.get("/api/nova/workspace/central/journeys", headers={
            "Authorization": "Bearer deliberately-invalid",
        })
        assert invalid.status_code == 401
    assert writes == []


def test_foreign_or_unknown_identity_denied(sandbox, monkeypatch):
    app, _, _, writes = sandbox
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    assert _get(app, _token(user="unprovisioned-user")).status_code == 401
    assert writes == []


def test_data_read_flag_cannot_enable_unmounted_preview(sandbox, monkeypatch):
    app, _, _, writes = sandbox
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED", "true")
    result = _get(app, _token())
    assert result.status_code == 200
    assert result.json()["integration_status"] == "not_connected"
    assert result.json()["journeys"] == []
    assert writes == []
