"""Test-only HTTP bridge: real JWT dependencies + disposable tenant journey rows.

This route is declared only in this test file; it is NOT registered in app.main
or the production Workspace router. All data is fictional and stored in a
pytest-owned SQLite database.
"""
import json

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session, sessionmaker

from app.auth import (
    ROLE_ADMIN, UserContext, create_access_token, get_current_user_context,
    require_any_role,
)
from app.db.models import User
from app.db.session import get_db
from synthetic_nova_tenant_journey_store_542 import (
    get_owner_journey, journey_rows, metadata,
)


@pytest.fixture
def context(tmp_path):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "tenant-journey-http.sqlite"),
        connect_args={"check_same_thread": False},
    )
    # Create only two explicitly requested tables; no main DB bootstrap.
    User.__table__.create(engine)
    journey_rows.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        for uid, org in [("owner-A", "org-A"), ("owner-B", "org-B")]:
            db.add(User(
                id=uid, email=uid + "@example.invalid",
                hashed_password="non-login-hash", display_name="Synthetic Owner",
                role=ROLE_ADMIN, authorized_roles=json.dumps([ROLE_ADMIN]),
                session_role=ROLE_ADMIN, organization_id=org,
                organization_name="Fictional Organization", auth_version=0,
                is_active=True, is_verified=True,
            ))
        db.execute(insert(journey_rows), [
            dict(organization_id="org-A", correlation_id="shared",
                 state="pending_approval", owner_action="review",
                 assigned_agent="owner", revision=2),
            dict(organization_id="org-B", correlation_id="shared",
                 state="completed", owner_action="none",
                 assigned_agent="operations", revision=4),
            dict(organization_id="org-B", correlation_id="private-B",
                 state="qualified", owner_action="none",
                 assigned_agent="work_revenue", revision=1),
        ])
        db.commit()

    app = FastAPI()

    @app.get("/test-only/journeys/{correlation_id}",
             dependencies=[Depends(require_any_role(ROLE_ADMIN))])
    def lookup(correlation_id: str, user: UserContext = Depends(get_current_user_context),
               db: Session = Depends(get_db)):
        try:
            result = get_owner_journey(
                db, verified_organization_id=user.organization_id,
                verified_role=user.role, correlation_id=correlation_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Owner organization required") from exc
        if result is None:
            raise HTTPException(status_code=404, detail="Journey unavailable")
        return result

    def temporary_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = temporary_db
    yield app, factory
    app.dependency_overrides.clear()
    engine.dispose()


def jwt(uid, org, role="admin", version=0):
    return create_access_token({
        "sub": uid, "email": uid + "@example.invalid",
        "role": role, "organization_id": org, "auth_version": version,
    })


def read(app, path, token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    with TestClient(app) as client:
        return client.get("/test-only/journeys/" + path, headers=headers)


def test_two_real_jwt_accounts_get_different_same_id_journeys(context):
    app, _ = context
    a = read(app, "shared", jwt("owner-A", "org-A"))
    b = read(app, "shared", jwt("owner-B", "org-B"))
    assert a.status_code == b.status_code == 200
    assert a.json()["state"] == "pending_approval"
    assert b.json()["state"] == "completed"


def test_owner_a_cannot_fetch_owner_b_private_journey(context):
    app, _ = context
    assert read(app, "private-B", jwt("owner-A", "org-A")).status_code == 404


def test_forged_token_organization_does_not_override_database_tenant(context):
    app, _ = context
    response = read(app, "shared", jwt("owner-A", "org-B"))
    assert response.status_code == 200
    assert response.json()["state"] == "pending_approval"


def test_anonymous_request_fails_authentication(context):
    app, _ = context
    assert read(app, "shared").status_code == 401


def test_revoked_role_fails_on_subsequent_request(context):
    app, factory = context
    token = jwt("owner-A", "org-A")
    assert read(app, "shared", token).status_code == 200
    with factory() as db:
        owner = db.query(User).filter(User.id == "owner-A").one()
        owner.authorized_roles = json.dumps(["staff"])
        db.commit()
    assert read(app, "shared", token).status_code == 403


def test_invalidated_session_fails_after_auth_version_change(context):
    app, factory = context
    token = jwt("owner-A", "org-A")
    with factory() as db:
        owner = db.query(User).filter(User.id == "owner-A").one()
        owner.auth_version = 1
        db.commit()
    assert read(app, "shared", token).status_code == 401


def test_no_pii_or_payload_reference_in_http_response(context):
    app, _ = context
    result = read(app, "shared", jwt("owner-A", "org-A"))
    assert result.status_code == 200
    assert set(result.json()) == {
        "correlation_id", "state", "assigned_agent", "owner_action", "revision",
    }
