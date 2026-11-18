"""Isolated HTTP integration for Nova Central's staging-only read adapter.

Real FastAPI auth dependencies and actual User ORM, but only disposable SQLite.
No migration, customer records, production access or live agent actions.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import sessionmaker

from app import auth
from app.db.models import User
from app.db.session import get_db
from app.core.nova.workspace.central_read_model import JOURNEY_READ_ROWS
from app.core.nova.workspace.central_journey_readonly import router


@pytest.fixture
def preview(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED", "true")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "test")
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "preview.sqlite"),
        connect_args={"check_same_thread": False},
    )
    User.__table__.create(engine)
    JOURNEY_READ_ROWS.create(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for uid, org in (("owner-A", "org-A"), ("owner-B", "org-B")):
            db.add(User(
                id=uid, email=uid + "@example.invalid",
                hashed_password="no-login", role="admin",
                authorized_roles=json.dumps(["admin"]), session_role="admin",
                organization_id=org, auth_version=0,
                is_active=True, is_verified=True,
            ))
        db.execute(insert(JOURNEY_READ_ROWS), [
            dict(organization_id="org-A", correlation_id="shared", state="pending_approval",
                 assigned_agent="owner", owner_action="review", revision=2),
            dict(organization_id="org-B", correlation_id="shared", state="completed",
                 assigned_agent="operations", owner_action="none", revision=4),
            dict(organization_id="org-B", correlation_id="private-B", state="qualified",
                 assigned_agent="work_revenue", owner_action="none", revision=1),
        ])
        db.commit()
    app = FastAPI()
    app.include_router(router)

    def test_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    yield app, factory, engine
    app.dependency_overrides.clear()
    engine.dispose()


def _token(uid, org):
    return auth.create_access_token({
        "sub": uid, "email": uid + "@example.invalid", "role": "admin",
        "organization_id": org, "auth_version": 0,
    })


def _read(app, uid="owner-A", org="org-A"):
    with TestClient(app) as client:
        return client.get("/central/journeys", headers={
            "Authorization": "Bearer " + _token(uid, org),
        })


def test_owner_preview_returns_only_its_organization(preview):
    app, _, _ = preview
    a = _read(app)
    b = _read(app, "owner-B", "org-B")
    assert a.status_code == b.status_code == 200
    assert a.json()["integration_status"] == "read_model_preview"
    assert a.json()["customer_data_connected"] is False
    assert [(j["correlation_id"], j["state"]) for j in a.json()["journeys"]] == [
        ("shared", "pending_approval")]
    assert [(j["correlation_id"], j["state"]) for j in b.json()["journeys"]] == [
        ("private-B", "qualified"), ("shared", "completed")]


def test_signed_org_mismatch_rejected_before_data_read(preview):
    app, _, _ = preview
    assert _read(app, "owner-A", "org-B").status_code == 403


def test_read_model_flag_default_off_returns_unconnected(preview, monkeypatch):
    app, _, _ = preview
    monkeypatch.delenv("NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED")
    result = _read(app)
    assert result.status_code == 200
    assert result.json()["integration_status"] == "not_connected"
    assert result.json()["journeys"] == []


def test_primary_feature_flag_off_still_404(preview, monkeypatch):
    app, _, _ = preview
    monkeypatch.delenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED")
    assert _read(app).status_code == 404


@pytest.mark.parametrize("environment", ["production", "prod", "", "development"])
def test_non_staging_or_test_environments_never_read_data(preview, monkeypatch, environment):
    app, _, _ = preview
    monkeypatch.setenv("AMICOR_ENVIRONMENT", environment)
    assert _read(app).status_code == 503


def test_missing_read_model_table_fails_closed(preview):
    app, _, engine = preview
    JOURNEY_READ_ROWS.drop(engine)
    result = _read(app)
    assert result.status_code == 503
    assert result.json()["detail"] == "Journey read model unavailable"


def test_no_pii_and_no_caching(preview):
    app, _, _ = preview
    result = _read(app)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    assert set(result.json()["journeys"][0]) == {
        "correlation_id", "state", "assigned_agent", "owner_action", "revision",
    }


def test_revoked_role_denied_by_real_orm_auth(preview):
    app, factory, _ = preview
    with factory() as db:
        row = db.query(User).filter(User.id == "owner-A").one()
        row.authorized_roles = json.dumps(["staff"])
        db.commit()
    assert _read(app).status_code == 403


def test_no_journey_write_routes():
    assert all(route.methods == {"GET"} for route in router.routes)


@pytest.mark.parametrize("primary,secondary", [
    ("test", "production"),
    ("production", "test"),
    ("staging", "prod"),
    ("", "staging"),
])
def test_conflicting_environment_flags_fail_closed(preview, monkeypatch, primary, secondary):
    app, _, _ = preview
    monkeypatch.setenv("AMICOR_ENVIRONMENT", primary)
    monkeypatch.setenv("APP_ENV", secondary)
    assert _read(app).status_code == 503
