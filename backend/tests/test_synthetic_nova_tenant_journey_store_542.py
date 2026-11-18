"""Disposable tenant-scoped journey read tests; no production datastore."""
import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from synthetic_nova_tenant_journey_store_542 import (
    get_owner_journey, journey_rows, metadata,
)


@pytest.fixture
def session(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "journeys.sqlite"))
    metadata.create_all(engine)
    with Session(engine) as db:
        db.execute(insert(journey_rows), [
            dict(organization_id="org-A", correlation_id="same-id",
                 state="pending_approval", owner_action="review",
                 assigned_agent="owner", revision=2),
            dict(organization_id="org-B", correlation_id="same-id",
                 state="completed", owner_action="none",
                 assigned_agent="operations", revision=4),
            dict(organization_id="org-B", correlation_id="only-B",
                 state="qualified", owner_action="none",
                 assigned_agent="work_revenue", revision=1),
        ])
        db.commit()
        yield db
    engine.dispose()


def test_tenant_a_only_reads_own_status(session):
    result = get_owner_journey(
        session, verified_organization_id="org-A",
        verified_role="admin", correlation_id="same-id",
    )
    assert result.state == "pending_approval"
    assert result.owner_action == "review"
    assert result.assigned_agent == "owner"


def test_two_organizations_same_correlation_never_cross_read(session):
    a = get_owner_journey(
        session, verified_organization_id="org-A",
        verified_role="admin", correlation_id="same-id",
    )
    b = get_owner_journey(
        session, verified_organization_id="org-B",
        verified_role="admin", correlation_id="same-id",
    )
    assert a.state == "pending_approval"
    assert b.state == "completed"
    assert a.revision != b.revision


def test_foreign_journey_is_not_found(session):
    assert get_owner_journey(
        session, verified_organization_id="org-A",
        verified_role="admin", correlation_id="only-B",
    ) is None


@pytest.mark.parametrize("org,role", [
    ("org-A", "staff"),
    ("org-A", "super_admin_support"),
    ("global", "admin"),
    ("", "admin"),
])
def test_unverified_owner_scope_denied(session, org, role):
    with pytest.raises(PermissionError, match="verified organization owner"):
        get_owner_journey(
            session, verified_organization_id=org,
            verified_role=role, correlation_id="same-id",
        )


def test_unknown_journey_returns_none_not_other_tenant_fallback(session):
    assert get_owner_journey(
        session, verified_organization_id="org-A",
        verified_role="admin", correlation_id="missing",
    ) is None


def test_projection_never_returns_personal_data(session):
    row = get_owner_journey(
        session, verified_organization_id="org-A",
        verified_role="admin", correlation_id="same-id",
    )
    assert set(row.__dataclass_fields__) == {
        "correlation_id", "state", "assigned_agent", "owner_action", "revision",
    }
