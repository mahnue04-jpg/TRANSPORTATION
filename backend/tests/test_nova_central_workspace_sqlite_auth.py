"""Signed JWT against a real, disposable SQLAlchemy platform_users table.

This exercises the actual User ORM, JWT decoding, role gate and FastAPI
dependencies. Creates ONLY a temporary SQLite file under pytest tmp_path.
It does not initialize the main database or authenticate production accounts.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import auth
from app.db.models import User
from app.db.session import get_db
from app.core.nova.workspace.central_journey_readonly import router


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "disposable_users.sqlite"),
        connect_args={"check_same_thread": False},
    )
    User.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(
            id="synthetic-owner-1", email="fake-owner@example.invalid",
            hashed_password="not-a-login-password", display_name="Fake Owner",
            role="admin", authorized_roles=json.dumps(["admin"]),
            session_role="admin", auth_version=0,
            organization_id="org-A", organization_name="Fake Organization",
            is_active=True, is_verified=True,
        ))
        db.commit()
    app = FastAPI()
    app.include_router(router)

    def scoped_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = scoped_db
    yield app, factory
    app.dependency_overrides.clear()
    engine.dispose()


def token(*, role="admin", version=0, org="org-A"):
    return auth.create_access_token({
        "sub": "synthetic-owner-1", "email": "fake-owner@example.invalid",
        "role": role, "auth_version": version, "organization_id": org,
    })


def read(app, bearer):
    with TestClient(app) as client:
        return client.get(
            "/central/journeys",
            headers={"Authorization": "Bearer " + bearer},
        )


def modify(factory, **changes):
    with factory() as db:
        account = db.query(User).filter(User.id == "synthetic-owner-1").one()
        for key, value in changes.items():
            setattr(account, key, value)
        db.commit()


def test_signed_admin_from_real_orm_table_sees_empty_readiness(sandbox):
    app, _ = sandbox
    response = read(app, token())
    assert response.status_code == 200
    assert response.json()["journeys"] == []
    assert response.json()["integration_status"] == "not_connected"


def test_real_orm_role_revocation_denied_with_old_token(sandbox):
    app, factory = sandbox
    existing_token = token()
    modify(factory, authorized_roles=json.dumps(["staff"]))
    assert read(app, existing_token).status_code == 403


def test_real_orm_account_deactivation_denies_signed_token(sandbox):
    app, factory = sandbox
    existing_token = token()
    modify(factory, is_active=False)
    assert read(app, existing_token).status_code == 401


def test_real_orm_session_version_invalidation_denies_old_token(sandbox):
    app, factory = sandbox
    existing_token = token()
    modify(factory, auth_version=1)
    assert read(app, existing_token).status_code == 401


def test_real_orm_missing_organization_denies_owner_access(sandbox):
    app, factory = sandbox
    modify(factory, organization_id=None)
    assert read(app, token()).status_code == 403


def test_real_orm_support_role_does_not_inherit_customer_owner_rights(sandbox):
    app, factory = sandbox
    modify(
        factory, role="super_admin_support",
        session_role="super_admin_support",
        authorized_roles=json.dumps(["super_admin_support"]),
    )
    assert read(app, token(role="super_admin_support")).status_code == 403


def test_organization_mismatch_token_never_returns_customer_journeys(sandbox):
    app, _ = sandbox
    result = read(app, token(org="org-B"))
    # This readiness endpoint reads no customer data at all. Actual record-level
    # organization isolation must be verified before any journey connection.
    assert result.status_code == 200
    assert result.json()["journeys"] == []
