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


def test_fresh_process_binds_only_the_configured_disposable_database(tmp_path):
    """A new interpreter must validate config before constructing session.engine."""
    import os
    import subprocess
    import sys
    dbfile = tmp_path / "never-created.sqlite"
    env = dict(os.environ)
    env.update({
        "AMICOR_ENVIRONMENT": "test",
        "APP_ENV": "test",
        "NOVA_CENTRAL_ISOLATED_TEST": "1",
        "DATABASE_URL": "sqlite:///" + str(dbfile),
        "NOVA_CENTRAL_APPROVED_COMMIT": "a" * 40,
        "RENDER_GIT_COMMIT": "a" * 40,
        "NOVA_CENTRAL_JOURNEY_READONLY_ENABLED": "false",
        "NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED": "false",
    })
    script = """
import sys
from pathlib import Path
from sqlalchemy import event
from sqlalchemy.engine import Engine
from fastapi.testclient import TestClient
def reject_any_sql_connection(dbapi_connection, connection_record):
    raise AssertionError("Fresh-process isolated readiness unexpectedly connected to a database")
event.listen(Engine, "connect", reject_any_sql_connection)
from nova_central_isolated import create_app
app = create_app()
from app.db.session import engine
assert engine.url.database == sys.argv[1], "Global SQL engine target mismatch"
assert "app.main" not in sys.modules, "Shared app lifespan accidentally imported"
assert not Path(sys.argv[1]).exists(), "App construction unexpectedly opened or wrote DB"
assert sorted(route.path for route in app.routes) == [
    "/api/nova/workspace/central/journeys", "/health/live"
]
with TestClient(app) as client:
    assert client.get("/health/live").status_code == 200
    assert client.get("/api/nova/workspace/central/journeys").status_code == 401
    assert client.post("/api/nova/workspace/central/journeys").status_code == 405
assert not Path(sys.argv[1]).exists(), "Lifespan/request unexpectedly opened or wrote DB"

"""
    proc = subprocess.run(
        [sys.executable, "-c", script, str(dbfile)],
        cwd=str(FILE.parent), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20,
    )
    assert proc.returncode == 0, proc.stderr[-1800:]
    assert not dbfile.exists()


def test_fresh_process_rejects_foreign_db_before_importing_auth(tmp_path):
    """The denied target must never be connected, even in a fresh interpreter."""
    import os
    import subprocess
    import sys
    badfile = tmp_path / "should-not-exist.sqlite"
    env = dict(os.environ)
    env.update({
        "AMICOR_ENVIRONMENT": "staging",
        "APP_ENV": "staging",
        "NOVA_CENTRAL_ISOLATED_TEST": "0",
        "DATABASE_URL": "sqlite:///" + str(badfile),
        "NOVA_CENTRAL_APPROVED_COMMIT": "a" * 40,
        "RENDER_GIT_COMMIT": "a" * 40,
        "NOVA_CENTRAL_EXPECTED_DB_HOST": "central-only.internal",
        "NOVA_CENTRAL_EXPECTED_DB_NAME": "nova_central_542_dispos",
        "NOVA_CENTRAL_JOURNEY_READONLY_ENABLED": "false",
        "NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED": "false",
    })
    script = """
import sys
from nova_central_isolated import create_app
try:
    create_app()
except RuntimeError:
    assert "app.auth" not in sys.modules
    assert "app.db.session" not in sys.modules
else:
    raise AssertionError("Foreign DB unexpectedly accepted")
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(FILE.parent), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20,
    )
    assert proc.returncode == 0, proc.stderr[-1800:]
    assert not badfile.exists()


def test_fresh_process_real_database_dependency_reads_without_writes(tmp_path):
    """Exercise the unmodified global get_db dependency, not a test override.

    A subprocess provisions its own throwaway owner record before instrumentation.
    During the ASGI lifespan/authenticated GET all SQL connections must bind to
    that same file, and no application DDL/DML is allowed.
    """
    import os
    import subprocess
    import sys

    dbfile = tmp_path / "fresh-process-owner.sqlite"
    env = dict(os.environ)
    env.update({
        "AMICOR_ENVIRONMENT": "test",
        "APP_ENV": "test",
        "NOVA_CENTRAL_ISOLATED_TEST": "1",
        "DATABASE_URL": "sqlite:///" + str(dbfile),
        "NOVA_CENTRAL_APPROVED_COMMIT": "a" * 40,
        "RENDER_GIT_COMMIT": "a" * 40,
        "NOVA_CENTRAL_JOURNEY_READONLY_ENABLED": "false",
        "NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED": "false",
    })
    script = """
import json, sys
from sqlalchemy import event
from sqlalchemy.engine import Engine
from fastapi.testclient import TestClient
from app import auth
from app.db.models import User
from app.db.session import engine, SessionLocal
from nova_central_isolated import create_app

target = sys.argv[1]
assert engine.url.database == target
User.__table__.create(engine)
with SessionLocal() as db:
    db.add(User(id="owner-A", email="owner@example.invalid",
                hashed_password="fixture", role="admin",
                authorized_roles=json.dumps(["admin"]),
                session_role="admin", organization_id="org-A",
                auth_version=0, is_active=True, is_verified=True))
    db.commit()

connections, unexpected_sql, owner_selects = [], [], []
def inspect_connection(conn, branch):
    connections.append(str(conn.engine.url.database))
    assert conn.engine.url.database == target, "Unexpected DB connection target"
def inspect_sql(conn, cursor, statement, params, context, many):
    operation = statement.lstrip().split(None, 1)[0].upper()
    if operation not in {"SELECT", "PRAGMA"}:
        unexpected_sql.append(operation)
    if operation == "SELECT" and "platform_users" in statement.lower():
        owner_selects.append(statement.lower())
event.listen(Engine, "engine_connect", inspect_connection)
event.listen(Engine, "before_cursor_execute", inspect_sql)

app = create_app()
assert not app.dependency_overrides, "Real auth/database dependencies must be used"
assert "app.main" not in sys.modules
token = auth.create_access_token({
    "sub": "owner-A", "email": "owner@example.invalid",
    "role": "admin", "organization_id": "org-A", "auth_version": 0,
})
with TestClient(app) as client:
    assert client.get("/health/live").status_code == 200
    assert client.get("/api/nova/workspace/central/journeys",
                      headers={"Authorization": "Bearer " + token}).status_code == 404
    # This controlled test may enable only empty readiness *after* app creation.
    import os
    os.environ["NOVA_CENTRAL_JOURNEY_READONLY_ENABLED"] = "true"
    read = client.get("/api/nova/workspace/central/journeys",
                      headers={"Authorization": "Bearer " + token})
    assert read.status_code == 200, read.text
    assert read.json()["journeys"] == []
    assert read.json()["integration_status"] == "not_connected"
    assert read.headers["cache-control"] == "private, no-store"
assert connections and set(connections) == {target}
assert not unexpected_sql, unexpected_sql
assert owner_selects, "Expected actual persisted-owner SELECT"
assert all("hashed_password" not in statement and "email" not in statement
           and "display_name" not in statement for statement in owner_selects), owner_selects
with SessionLocal() as db:
    assert db.query(User).count() == 1
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, str(dbfile)],
        cwd=str(FILE.parent), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=25,
    )
    assert proc.returncode == 0, proc.stderr[-2600:]
    assert dbfile.exists()


def test_fresh_process_sqlite_authorizer_enforces_minimal_auth_permissions(tmp_path):
    """Deny sensitive account column reads and all SQL mutations at DB level.

    This tests a disposable SQLite permission simulation, not actual Postgres
    GRANTs. The unmodified ASGI auth dependency must succeed with that policy.
    """
    import os
    import subprocess
    import sys

    dbfile = tmp_path / "reader-only-simulation.sqlite"
    env = dict(os.environ)
    env.update({
        "AMICOR_ENVIRONMENT": "test", "APP_ENV": "test",
        "NOVA_CENTRAL_ISOLATED_TEST": "1",
        "DATABASE_URL": "sqlite:///" + str(dbfile),
        "NOVA_CENTRAL_APPROVED_COMMIT": "a" * 40,
        "RENDER_GIT_COMMIT": "a" * 40,
        "NOVA_CENTRAL_JOURNEY_READONLY_ENABLED": "false",
        "NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED": "false",
    })
    script = """
import json, os, sqlite3, sys
from fastapi.testclient import TestClient
from sqlalchemy import event
from app import auth
from app.db.models import User
from app.db.session import SessionLocal, engine
from nova_central_isolated import create_app

assert engine.url.database == sys.argv[1]
User.__table__.create(engine)
with SessionLocal() as db:
    db.add(User(id="owner-A", email="owner@example.invalid",
                hashed_password="fictional-hash", role="admin",
                authorized_roles=json.dumps(["admin"]), session_role="admin",
                organization_id="org-A", auth_version=0,
                is_active=True, is_verified=True))
    db.commit()
# A fictional unrelated table confirms that this reader cannot see other data.
with engine.begin() as conn:
    conn.exec_driver_sql("CREATE TABLE unrelated_private_records (secret TEXT)")
    conn.exec_driver_sql("INSERT INTO unrelated_private_records VALUES ('fictional')")
engine.dispose()

private = {"hashed_password", "email", "display_name"}
allowed = {"id", "role", "authorized_roles", "session_role",
           "organization_id", "auth_version", "is_active"}
denied_ops = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE,
              sqlite3.SQLITE_DELETE, sqlite3.SQLITE_CREATE_TABLE,
              sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE}
observed = []
def install_policy(connection, record):
    def authorize(op, table, column, database, source):
        if op in denied_ops:
            observed.append(("forbidden_mutation", table, column))
            return sqlite3.SQLITE_DENY
        if op == sqlite3.SQLITE_READ:
            if table != "platform_users":
                observed.append(("forbidden_table", table, column))
                return sqlite3.SQLITE_DENY
            if column not in allowed:
                observed.append(("forbidden_column", table, column))
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    connection.set_authorizer(authorize)
event.listen(engine, "connect", install_policy)

app = create_app()
assert not app.dependency_overrides
token = auth.create_access_token({
    "sub":"owner-A", "email":"owner@example.invalid", "role":"admin",
    "organization_id":"org-A", "auth_version":0,
})
with TestClient(app) as client:
    assert client.get("/health/live").status_code == 200
    os.environ["NOVA_CENTRAL_JOURNEY_READONLY_ENABLED"] = "true"
    response = client.get("/api/nova/workspace/central/journeys",
                          headers={"Authorization": "Bearer " + token})
    assert response.status_code == 200, response.text
    assert response.json()["journeys"] == []
    assert response.json()["integration_status"] == "not_connected"
    assert client.post("/api/nova/workspace/central/journeys").status_code == 405
assert observed == [], observed

# Prove the same installed authorizer actively rejects forbidden operations,
# rather than merely observing that normal application requests avoided them.
from sqlalchemy.exc import DatabaseError
with engine.connect() as conn:
    for forbidden in (
        "SELECT hashed_password FROM platform_users LIMIT 1",
        "SELECT secret FROM unrelated_private_records LIMIT 1",
        "UPDATE platform_users SET role='staff' WHERE id='owner-A'",
        "CREATE TABLE forbidden_central_ddl (id INTEGER)",
    ):
        try:
            conn.exec_driver_sql(forbidden)
        except DatabaseError:
            pass
        else:
            raise AssertionError("Forbidden SQL unexpectedly succeeded: " + forbidden)
assert any(item[0] == "forbidden_column" for item in observed), observed
assert any(item[0] == "forbidden_table" for item in observed), observed
assert any(item[0] == "forbidden_mutation" for item in observed), observed
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, str(dbfile)],
        cwd=str(FILE.parent), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, timeout=25,
    )
    assert proc.returncode == 0, proc.stderr[-2600:]
