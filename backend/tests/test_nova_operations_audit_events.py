"""Offline audit tests: synthetic IDs only; never log file contents."""
import sqlite3
from uuid import uuid4

import pytest

from app.core.nova.work_revenue.operations_audit_events import (
    initialize_audit_events, list_job_audit_events, record_audit_event,
)
from app.core.nova.work_revenue.operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope,
)


def _job():
    tenant = str(uuid4())
    return tenant, TenantJobScope(tenant_id=tenant, job_id=str(uuid4()))


def test_persisted_scoped_audit_and_artifact_events(tmp_path):
    db = tmp_path / "audit.sqlite"
    owner, job = _job()
    artifact_id = str(uuid4())
    with sqlite3.connect(db) as connection:
        initialize_audit_events(connection)
        first = record_audit_event(
            connection, acting_tenant_id=owner, job=job,
            actor_id="authenticated-user", action="upload_started",
            occurred_at=1000,
        )
        second = record_audit_event(
            connection, acting_tenant_id=owner, job=job,
            actor_id="authenticated-user", action="artifact_linked",
            artifact_id=artifact_id, occurred_at=1001,
        )
        assert second > first
    with sqlite3.connect(db) as connection:
        events = list_job_audit_events(
            connection, acting_tenant_id=owner, job=job,
        )
        assert tuple(e.action for e in events) == (
            "upload_started", "artifact_linked",
        )
        assert events[1].artifact_id == artifact_id


def test_cross_tenant_read_and_write_denied():
    owner, job = _job()
    with sqlite3.connect(":memory:") as connection:
        initialize_audit_events(connection)
        with pytest.raises(TenantAccessDenied):
            record_audit_event(
                connection, acting_tenant_id=str(uuid4()), job=job,
                actor_id="attacker", action="upload_started",
            )
        record_audit_event(
            connection, acting_tenant_id=owner, job=job,
            actor_id="owner", action="upload_started",
        )
        with pytest.raises(TenantAccessDenied):
            list_job_audit_events(
                connection, acting_tenant_id=str(uuid4()), job=job,
            )
        assert len(list_job_audit_events(
            connection, acting_tenant_id=owner, job=job,
        )) == 1


def test_sqlite_update_and_delete_rejected():
    owner, job = _job()
    with sqlite3.connect(":memory:") as connection:
        initialize_audit_events(connection)
        identifier = record_audit_event(
            connection, acting_tenant_id=owner, job=job,
            actor_id="owner", action="upload_started",
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE operations_csv_audit_events SET action = ? WHERE event_id = ?",
                ("upload_finished", identifier),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM operations_csv_audit_events WHERE event_id = ?",
                (identifier,),
            )
        assert len(list_job_audit_events(
            connection, acting_tenant_id=owner, job=job,
        )) == 1


@pytest.mark.parametrize("bad", ["", "user\nname", None])
def test_missing_or_unsafe_actor_rejected(bad):
    owner, job = _job()
    with sqlite3.connect(":memory:") as connection:
        initialize_audit_events(connection)
        with pytest.raises(TenantAccessDenied):
            record_audit_event(
                connection, acting_tenant_id=owner, job=job,
                actor_id=bad, action="upload_started",
            )


def test_invalid_actions_artifacts_and_timestamps_rejected():
    owner, job = _job()
    with sqlite3.connect(":memory:") as connection:
        initialize_audit_events(connection)
        with pytest.raises(ValueError):
            record_audit_event(
                connection, acting_tenant_id=owner, job=job,
                actor_id="owner", action="unknown",
            )
        with pytest.raises(ValueError):
            record_audit_event(
                connection, acting_tenant_id=owner, job=job,
                actor_id="owner", action="artifact_approved",
            )
        with pytest.raises(TenantAccessDenied):
            record_audit_event(
                connection, acting_tenant_id=owner, job=job,
                actor_id="owner", action="artifact_linked",
                artifact_id="../escape",
            )
        with pytest.raises(ValueError):
            record_audit_event(
                connection, acting_tenant_id=owner, job=job,
                actor_id="owner", action="upload_started",
                occurred_at=-1,
            )
        assert not list_job_audit_events(
            connection, acting_tenant_id=owner, job=job,
        )
