"""Test atomic approval/audit coupling in isolated SQLite."""
import sqlite3
from uuid import uuid4

import pytest

from app.core.nova.work_revenue.operations_artifact_manifest import (
    build_artifact_manifest,
)
from app.core.nova.work_revenue.operations_artifact_registry import (
    initialize_registry, load_manifest, save_manifest,
)
from app.core.nova.work_revenue.operations_audit_events import (
    initialize_audit_events, list_job_audit_events,
)
from app.core.nova.work_revenue.operations_atomic_approval import (
    approve_artifact_with_audit,
)
from app.core.nova.work_revenue.operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope,
)


def _setup(connection):
    initialize_registry(connection)
    initialize_audit_events(connection)
    tenant = str(uuid4())
    job = TenantJobScope(tenant_id=tenant, job_id=str(uuid4()))
    manifest = build_artifact_manifest(
        acting_tenant_id=tenant, job=job,
        artifact_id=str(uuid4()), content=b"x,y\n1,2\n",
    )
    save_manifest(connection, acting_tenant_id=tenant, manifest=manifest)
    return tenant, job, manifest


def test_approval_and_audit_survive_database_reopen(tmp_path):
    db = tmp_path / "approval.sqlite"
    with sqlite3.connect(db) as connection:
        tenant, job, manifest = _setup(connection)
        event_id = approve_artifact_with_audit(
            connection, acting_tenant_id=tenant, job=job,
            artifact_id=manifest.artifact_id,
            authenticated_actor_id="reviewer-from-session",
            occurred_at=1001,
        )
    with sqlite3.connect(db) as connection:
        approved = load_manifest(
            connection, acting_tenant_id=tenant,
            job=job, artifact_id=manifest.artifact_id,
        )
        events = list_job_audit_events(
            connection, acting_tenant_id=tenant, job=job,
        )
        assert approved.approved_for_download
        assert len(events) == 1
        assert events[0].event_id == event_id
        assert events[0].action == "artifact_approved"


def test_missing_audit_table_rolls_back_approval():
    with sqlite3.connect(":memory:") as connection:
        tenant, job, manifest = _setup(connection)
        connection.execute("DROP TABLE operations_csv_audit_events")
        with pytest.raises(sqlite3.OperationalError):
            approve_artifact_with_audit(
                connection, acting_tenant_id=tenant, job=job,
                artifact_id=manifest.artifact_id,
                authenticated_actor_id="reviewer", occurred_at=1000,
            )
        assert not load_manifest(
            connection, acting_tenant_id=tenant,
            job=job, artifact_id=manifest.artifact_id,
        ).approved_for_download


def test_cross_tenant_and_duplicate_approval_denied():
    with sqlite3.connect(":memory:") as connection:
        tenant, job, manifest = _setup(connection)
        with pytest.raises(TenantAccessDenied):
            approve_artifact_with_audit(
                connection, acting_tenant_id=str(uuid4()), job=job,
                artifact_id=manifest.artifact_id,
                authenticated_actor_id="attacker", occurred_at=1000,
            )
        approve_artifact_with_audit(
            connection, acting_tenant_id=tenant, job=job,
            artifact_id=manifest.artifact_id,
            authenticated_actor_id="reviewer", occurred_at=1000,
        )
        with pytest.raises(TenantAccessDenied):
            approve_artifact_with_audit(
                connection, acting_tenant_id=tenant, job=job,
                artifact_id=manifest.artifact_id,
                authenticated_actor_id="reviewer", occurred_at=1001,
            )
        assert len(list_job_audit_events(
            connection, acting_tenant_id=tenant, job=job,
        )) == 1


def test_invalid_actor_does_not_approve():
    with sqlite3.connect(":memory:") as connection:
        tenant, job, manifest = _setup(connection)
        with pytest.raises(TenantAccessDenied):
            approve_artifact_with_audit(
                connection, acting_tenant_id=tenant, job=job,
                artifact_id=manifest.artifact_id,
                authenticated_actor_id="bad\nname", occurred_at=1000,
            )
        assert not load_manifest(
            connection, acting_tenant_id=tenant,
            job=job, artifact_id=manifest.artifact_id,
        ).approved_for_download
