"""Concurrent sandbox organization creates must keep one row per tenant and name."""
import os
import threading
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.core.nova.creative_studio.casting_access import CastingRequestRejected
from app.core.nova.creative_studio.casting_db_writes import ensure_sandbox_organization

POSTGRES = os.getenv("CASTING_TEST_POSTGRES_URL", "")


def _enable(monkeypatch):
    monkeypatch.setenv("NOVA_CASTING_STAGING_READS", "true")
    for key in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(key, "disposable")


def _prepare(engine):
    from app.db.models import User
    from app.core.nova.creative_studio import casting_db_models

    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    for table in (
        User.__table__,
        casting_db_models.NovaCastingOrganization.__table__,
        casting_db_models.NovaCastingMembership.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    seed = Session()
    seed.add(User(
        id="organizer",
        email="organizer@example.invalid",
        hashed_password="not-a-login",
        role="staff",
        organization_id="tenant-a",
        is_active=True,
        is_verified=True,
    ))
    seed.add(User(
        id="applicant",
        email="applicant@example.invalid",
        hashed_password="not-a-login",
        role="staff",
        organization_id="tenant-a",
        is_active=True,
        is_verified=True,
    ))
    seed.commit()
    seed.close()
    return Session


def _run_pair(session_factory, user_id, name):
    barrier = threading.Barrier(2)
    found = []
    errors = []
    guard = threading.Lock()

    def worker():
        db = session_factory()
        try:
            barrier.wait(timeout=10)
            view = ensure_sandbox_organization(
                db=db,
                user_id=user_id,
                tenant_id="tenant-a",
                payload={"name": name},
            )
            db.commit()
            with guard:
                found.append(view["id"])
        except Exception as exc:
            db.rollback()
            with guard:
                errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    return found, errors


def _org_count(session_factory, name):
    from app.core.nova.creative_studio.casting_db_models import (
        NovaCastingMembership,
        NovaCastingOrganization,
    )

    db = session_factory()
    try:
        organizations = db.query(NovaCastingOrganization).filter(
            NovaCastingOrganization.nova_tenant_id == "tenant-a",
            NovaCastingOrganization.name == name,
        ).count()
        memberships = db.query(NovaCastingMembership).count()
        return organizations, memberships
    finally:
        db.close()


def test_concurrent_creates_for_one_caller_return_one_organization(monkeypatch, tmp_path):
    _enable(monkeypatch)
    database = Path(tmp_path) / "casting-org-race.db"
    engine = sa.create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=sa.pool.NullPool,
    )

    @sa.event.listens_for(engine, "connect")
    def _sqlite_setup(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    session_factory = _prepare(engine)
    found, errors = _run_pair(session_factory, "organizer", "North Studio")
    assert errors == []
    assert found[0] == found[1]
    organizations, memberships = _org_count(session_factory, "North Studio")
    assert organizations == 1
    assert memberships == 1
    engine.dispose()


def test_second_caller_does_not_join_an_existing_name(monkeypatch, tmp_path):
    _enable(monkeypatch)
    database = Path(tmp_path) / "casting-org-taken.db"
    engine = sa.create_engine(f"sqlite:///{database}")
    session_factory = _prepare(engine)
    first = session_factory()
    created = ensure_sandbox_organization(
        db=first, user_id="organizer", tenant_id="tenant-a", payload={"name": "North Studio"},
    )
    first.commit()
    first.close()
    second = session_factory()
    with pytest.raises(CastingRequestRejected, match="Request rejected"):
        ensure_sandbox_organization(
            db=second, user_id="applicant", tenant_id="tenant-a", payload={"name": "North Studio"},
        )
    second.rollback()
    second.close()
    check = session_factory()
    from app.core.nova.creative_studio.casting_db_models import NovaCastingMembership
    members = check.query(NovaCastingMembership).filter(
        NovaCastingMembership.organization_id == created["id"],
    ).all()
    check.close()
    assert [row.user_id for row in members] == ["organizer"]
    engine.dispose()


@pytest.mark.skipif(not POSTGRES, reason="Disposable PostgreSQL not configured")
def test_postgres_concurrent_creates_return_one_organization(monkeypatch):
    _enable(monkeypatch)
    admin = sa.create_engine(POSTGRES)
    with admin.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS casting_org_race_ci CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA casting_org_race_ci")
    admin.dispose()
    engine = sa.create_engine(
        POSTGRES,
        connect_args={"options": "-csearch_path=casting_org_race_ci"},
        poolclass=sa.pool.NullPool,
    )
    session_factory = _prepare(engine)
    found, errors = _run_pair(session_factory, "organizer", "North Studio")
    assert errors == []
    assert len(found) == 2
    assert found[0] == found[1]
    organizations, memberships = _org_count(session_factory, "North Studio")
    assert organizations == 1
    assert memberships == 1
    engine.dispose()
    admin = sa.create_engine(POSTGRES)
    with admin.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS casting_org_race_ci CASCADE")
    admin.dispose()
