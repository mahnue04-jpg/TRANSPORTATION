"""Real signed-JWT dependency tests for default-off Central Workspace route.

Uses a disposable in-memory account lookup, not production user records.
Only get_db is overridden; FastAPI JWT parsing, role checks, user resolution,
and UserContext dependencies execute unmodified.
"""
import json
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth
from app.core.nova.workspace.central_journey_readonly import router
from app.db.session import get_db


class FakeQuery:
    def __init__(self, record):
        self.record = record

    def filter(self, criterion):
        return self

    def first(self):
        return self.record


class FakeSession:
    def __init__(self, record):
        self.record = record

    def query(self, model):
        return FakeQuery(self.record)


def account(*, org="org-A", role="admin", grants=("admin",),
            active=True, version=0):
    return SimpleNamespace(
        id="synthetic-owner-1",
        email="synthetic@example.invalid",
        role=role,
        session_role=role,
        authorized_roles=json.dumps(list(grants)),
        organization_id=org,
        organization_name="Synthetic Org",
        auth_version=version,
        is_active=active,
    )


def test_app(record):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: FakeSession(record)
    return app


def signed(record, *, role=None, version=None, org=None):
    return auth.create_access_token({
        "sub": record.id,
        "email": record.email,
        "role": role if role is not None else record.role,
        "auth_version": record.auth_version if version is None else version,
        "organization_id": record.organization_id if org is None else org,
    })


def get(app, token):
    with TestClient(app) as client:
        return client.get("/central/journeys", headers={"Authorization": "Bearer " + token})


def test_valid_signed_owner_session_has_no_connected_data(monkeypatch):
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    user = account()
    reply = get(test_app(user), signed(user))
    assert reply.status_code == 200
    assert reply.json()["integration_status"] == "not_connected"
    assert reply.json()["journeys"] == []


@pytest.mark.parametrize("role,grants", [
    ("staff", ("staff",)),
    ("super_admin_support", ("super_admin_support",)),
    ("admin", ("staff",)),
])
def test_signed_role_not_authorized_as_owner(monkeypatch, role, grants):
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    user = account(role=role, grants=grants)
    assert get(test_app(user), signed(user)).status_code == 403


def test_role_revocation_with_existing_signed_admin_token(monkeypatch):
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    user = account(role="admin", grants=("admin",))
    token = signed(user)
    user.authorized_roles = json.dumps(["staff"])
    assert get(test_app(user), token).status_code == 403


def test_inactivated_account_rejected(monkeypatch):
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    user = account(active=False)
    assert get(test_app(user), signed(user)).status_code == 401


def test_session_auth_version_revocation_rejected(monkeypatch):
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    user = account(version=2)
    assert get(test_app(user), signed(user, version=1)).status_code == 401


@pytest.mark.parametrize("org", ["global", "", None])
def test_owner_without_normal_tenant_rejected(monkeypatch, org):
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    user = account(org=org)
    assert get(test_app(user), signed(user)).status_code == 403


def test_token_org_cannot_override_persisted_user_org(monkeypatch):
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    user = account(org="org-A")
    reply = get(test_app(user), signed(user, org="org-B"))
    assert reply.status_code == 200
    assert reply.json()["journeys"] == []
    # Authorization is scoped to persisted user.organization_id, not JWT org.
    assert user.organization_id == "org-A"


def test_signed_owner_still_sees_default_off_404(monkeypatch):
    monkeypatch.delenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", raising=False)
    user = account()
    assert get(test_app(user), signed(user)).status_code == 404


def test_expired_signed_token_rejected(monkeypatch):
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    user = account()
    token = auth._jwt_sign({
        "sub": user.id, "email": user.email, "role": "admin",
        "auth_version": 0, "exp": time.time() - 60,
        **({"iss": auth.JWT_ISSUER} if auth.JWT_ISSUER else {}),
        **({"aud": auth.JWT_AUDIENCE} if auth.JWT_AUDIENCE else {}),
    })
    assert get(test_app(user), token).status_code == 401
