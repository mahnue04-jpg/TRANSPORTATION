"""Disposable database acceptance for proposed Nova Central read-only model.

No production migration, writer, customer records, app route or deployments.
"""
import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.core.nova.workspace.central_read_model import (
    JOURNEY_READ_ROWS, READ_MODEL_METADATA, read_journey, list_journeys,
)


@pytest.fixture
def db(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "central-read-model.sqlite"))
    READ_MODEL_METADATA.create_all(engine)
    with Session(engine) as session:
        session.execute(insert(JOURNEY_READ_ROWS), [
            dict(organization_id="org-A", correlation_id="journey-001",
                 state="pending_approval", assigned_agent="owner",
                 owner_action="review", revision=2),
            dict(organization_id="org-B", correlation_id="journey-001",
                 state="completed", assigned_agent="operations",
                 owner_action="none", revision=4),
            dict(organization_id="org-B", correlation_id="private-B",
                 state="qualified", assigned_agent="work_revenue",
                 owner_action="none", revision=1),
        ])
        session.commit()
        yield session
    engine.dispose()


def test_owner_reads_exact_tenant_same_id(db):
    a = read_journey(db, authenticated_organization_id="org-A",
                     authenticated_role="admin", correlation_id="journey-001")
    b = read_journey(db, authenticated_organization_id="org-B",
                     authenticated_role="admin", correlation_id="journey-001")
    assert a.state == "pending_approval"
    assert b.state == "completed"


def test_foreign_record_returns_none(db):
    assert read_journey(db, authenticated_organization_id="org-A",
                        authenticated_role="admin", correlation_id="private-B") is None


def test_bounded_listing_never_leaks_other_tenant(db):
    a = list_journeys(db, authenticated_organization_id="org-A",
                      authenticated_role="admin", limit=20)
    b = list_journeys(db, authenticated_organization_id="org-B",
                      authenticated_role="admin", limit=20)
    assert len(a) == 1
    assert len(b) == 2
    assert [row.correlation_id for row in a] == ["journey-001"]


@pytest.mark.parametrize("org,role", [
    ("global", "admin"), ("", "admin"), ("org-A", "staff"),
    ("org-A", "super_admin_support"),
])
def test_reject_untrusted_roles_and_global_org(db, org, role):
    with pytest.raises(PermissionError):
        read_journey(db, authenticated_organization_id=org,
                     authenticated_role=role, correlation_id="journey-001")
    with pytest.raises(PermissionError):
        list_journeys(db, authenticated_organization_id=org,
                      authenticated_role=role)


@pytest.mark.parametrize("limit", [-1, 0, 51, True])
def test_reject_bad_limit(db, limit):
    with pytest.raises(ValueError):
        list_journeys(db, authenticated_organization_id="org-A",
                      authenticated_role="admin", limit=limit)


def test_exact_public_shape_excludes_sensitive_data(db):
    row = read_journey(db, authenticated_organization_id="org-A",
                       authenticated_role="admin", correlation_id="journey-001")
    assert set(row.__dataclass_fields__) == {
        "correlation_id", "state", "assigned_agent", "owner_action", "revision",
    }


def test_no_startup_registration_of_read_model():
    from app.db.session import Base
    assert JOURNEY_READ_ROWS.name not in Base.metadata.tables
