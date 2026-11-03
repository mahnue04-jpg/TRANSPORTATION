"""SQLite-backed registry contract tests using synthetic artifacts only."""
import sqlite3
from uuid import uuid4

import pytest

from app.core.nova.work_revenue.operations_artifact_manifest import (
    authorize_artifact_download, build_artifact_manifest,
)
from app.core.nova.work_revenue.operations_artifact_registry import (
    approve_download, initialize_registry, load_manifest, save_manifest,
)
from app.core.nova.work_revenue.operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope,
)


def _sample(owner=None):
    owner = owner or str(uuid4())
    job = TenantJobScope(tenant_id=owner, job_id=str(uuid4()))
    artifact_id = str(uuid4())
    content = b"item,amount\nservice,15\n"
    manifest = build_artifact_manifest(
        acting_tenant_id=owner, job=job,
        artifact_id=artifact_id, content=content,
    )
    return owner, manifest, content


def test_persist_and_reload_only_with_tenant_scope(tmp_path):
    path = tmp_path / "artifact_registry.db"
    owner, manifest, content = _sample()
    with sqlite3.connect(path) as connection:
        initialize_registry(connection)
        save_manifest(connection, acting_tenant_id=owner, manifest=manifest)
    with sqlite3.connect(path) as connection:
        loaded = load_manifest(
            connection, acting_tenant_id=owner,
            job=manifest.job, artifact_id=manifest.artifact_id,
        )
        assert loaded == manifest
        with pytest.raises(TenantAccessDenied):
            authorize_artifact_download(
                acting_tenant_id=owner, manifest=loaded, content=content
            )
        approve_download(
            connection, acting_tenant_id=owner,
            job=manifest.job, artifact_id=manifest.artifact_id,
        )
        approved = load_manifest(
            connection, acting_tenant_id=owner,
            job=manifest.job, artifact_id=manifest.artifact_id,
        )
        assert authorize_artifact_download(
            acting_tenant_id=owner, manifest=approved, content=content
        ) == content


def test_cross_tenant_read_and_approval_fail_closed():
    owner, manifest, _ = _sample()
    intruder = str(uuid4())
    with sqlite3.connect(":memory:") as connection:
        initialize_registry(connection)
        save_manifest(connection, acting_tenant_id=owner, manifest=manifest)
        with pytest.raises(TenantAccessDenied):
            load_manifest(
                connection, acting_tenant_id=intruder,
                job=manifest.job, artifact_id=manifest.artifact_id,
            )
        with pytest.raises(TenantAccessDenied):
            approve_download(
                connection, acting_tenant_id=intruder,
                job=manifest.job, artifact_id=manifest.artifact_id,
            )
        assert not load_manifest(
            connection, acting_tenant_id=owner,
            job=manifest.job, artifact_id=manifest.artifact_id,
        ).approved_for_download


def test_other_job_and_missing_artifact_denied():
    owner, manifest, _ = _sample()
    with sqlite3.connect(":memory:") as connection:
        initialize_registry(connection)
        save_manifest(connection, acting_tenant_id=owner, manifest=manifest)
        with pytest.raises(TenantAccessDenied):
            load_manifest(
                connection, acting_tenant_id=owner,
                job=TenantJobScope(tenant_id=owner, job_id=str(uuid4())),
                artifact_id=manifest.artifact_id,
            )
        with pytest.raises(TenantAccessDenied):
            load_manifest(
                connection, acting_tenant_id=owner,
                job=manifest.job, artifact_id=str(uuid4()),
            )


def test_duplicate_artifact_refused():
    owner, manifest, _ = _sample()
    with sqlite3.connect(":memory:") as connection:
        initialize_registry(connection)
        save_manifest(connection, acting_tenant_id=owner, manifest=manifest)
        with pytest.raises(sqlite3.IntegrityError):
            save_manifest(
                connection, acting_tenant_id=owner, manifest=manifest
            )
