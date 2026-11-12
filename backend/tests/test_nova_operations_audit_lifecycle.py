"""Offline audit and artifact lifecycle integration tests.

These tests use synthetic CSV bytes and isolated SQLite/local storage only.
They do NOT prove transactional atomicity between audit, database and files;
production must make event/state changes atomic and audit denied attempts.
"""
import sqlite3
from uuid import uuid4

import pytest

from app.core.nova.work_revenue.operations_artifact_manifest import (
    build_artifact_manifest,
)
from app.core.nova.work_revenue.operations_artifact_registry import (
    approve_download, initialize_registry, load_manifest, save_manifest,
)
from app.core.nova.work_revenue.operations_audit_events import (
    initialize_audit_events, list_job_audit_events, record_audit_event,
)
from app.core.nova.work_revenue.operations_local_artifact_store import (
    LocalPrivateArtifactStore,
)
from app.core.nova.work_revenue.operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope,
)
from app.core.nova.work_revenue.operations_upload_leases import (
    acquire_upload_lease, finish_upload_lease, initialize_upload_leases,
)


def _context(connection):
    initialize_registry(connection)
    initialize_audit_events(connection)
    initialize_upload_leases(connection)
    owner = str(uuid4())
    job = TenantJobScope(tenant_id=owner, job_id=str(uuid4()))
    return owner, job


def test_persisted_audit_matches_successful_offline_artifact_lifecycle(tmp_path):
    database = tmp_path / "artifacts.sqlite"
    store = LocalPrivateArtifactStore(tmp_path / "private")
    csv_content = b"item,total\nservice,15\n"
    with sqlite3.connect(database) as connection:
        owner, job = _context(connection)
        lease = acquire_upload_lease(
            connection, acting_tenant_id=owner, job=job, now=1000,
        )
        record_audit_event(
            connection, acting_tenant_id=owner, job=job, actor_id="worker",
            action="upload_started", occurred_at=1000,
        )
        manifest = build_artifact_manifest(
            acting_tenant_id=owner, job=job,
            artifact_id=str(uuid4()), content=csv_content,
        )
        store.put(
            acting_tenant_id=owner, manifest=manifest, content=csv_content,
        )
        save_manifest(
            connection, acting_tenant_id=owner, manifest=manifest,
        )
        record_audit_event(
            connection, acting_tenant_id=owner, job=job, actor_id="worker",
            action="artifact_linked", artifact_id=manifest.artifact_id,
            occurred_at=1001,
        )
        finish_upload_lease(
            connection, acting_tenant_id=owner, lease=lease,
            success=True, now=1002,
        )
        record_audit_event(
            connection, acting_tenant_id=owner, job=job, actor_id="worker",
            action="upload_finished", occurred_at=1002,
        )
        approve_download(
            connection, acting_tenant_id=owner, job=job,
            artifact_id=manifest.artifact_id,
        )
        record_audit_event(
            connection, acting_tenant_id=owner, job=job, actor_id="reviewer",
            action="artifact_approved", artifact_id=manifest.artifact_id,
            occurred_at=1003,
        )
    with sqlite3.connect(database) as connection:
        approved = load_manifest(
            connection, acting_tenant_id=owner, job=job,
            artifact_id=manifest.artifact_id,
        )
        assert store.get(
            acting_tenant_id=owner, manifest=approved
        ) == csv_content
        record_audit_event(
            connection, acting_tenant_id=owner, job=job, actor_id="owner",
            action="artifact_downloaded", artifact_id=manifest.artifact_id,
            occurred_at=1004,
        )
        actions = tuple(
            event.action for event in list_job_audit_events(
                connection, acting_tenant_id=owner, job=job,
            )
        )
        assert actions == (
            "upload_started", "artifact_linked", "upload_finished",
            "artifact_approved", "artifact_downloaded",
        )
        with pytest.raises(TenantAccessDenied):
            list_job_audit_events(
                connection, acting_tenant_id=str(uuid4()), job=job,
            )


def test_failed_upload_is_not_labeled_completed(tmp_path):
    store = LocalPrivateArtifactStore(tmp_path / "private")
    with sqlite3.connect(tmp_path / "failed.sqlite") as connection:
        owner, job = _context(connection)
        lease = acquire_upload_lease(
            connection, acting_tenant_id=owner, job=job, now=100,
        )
        record_audit_event(
            connection, acting_tenant_id=owner, job=job, actor_id="worker",
            action="upload_started", occurred_at=100,
        )
        content = b"a,b\n1,2\n"
        manifest = build_artifact_manifest(
            acting_tenant_id=owner, job=job,
            artifact_id=str(uuid4()), content=content,
        )
        with pytest.raises(TenantAccessDenied):
            store.put(
                acting_tenant_id=owner, manifest=manifest,
                content=b"a,b\n9,9\n",
            )
        finish_upload_lease(
            connection, acting_tenant_id=owner, lease=lease,
            success=False, now=101,
        )
        record_audit_event(
            connection, acting_tenant_id=owner, job=job, actor_id="worker",
            action="upload_failed", occurred_at=101,
        )
        actions = tuple(
            event.action for event in list_job_audit_events(
                connection, acting_tenant_id=owner, job=job,
            )
        )
        assert actions == ("upload_started", "upload_failed")
        assert not list(store.root.iterdir())
        with pytest.raises(TenantAccessDenied):
            load_manifest(
                connection, acting_tenant_id=owner, job=job,
                artifact_id=manifest.artifact_id,
            )
