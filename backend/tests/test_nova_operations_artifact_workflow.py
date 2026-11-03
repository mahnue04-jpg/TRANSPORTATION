"""Offline end-to-end artifact lifecycle contract using only synthetic data.

Exercised components: private filesystem adapter, SQLite metadata registry,
tenant authorization, human-approval gate, and SHA-256 integrity checks.
This is not CSV processing, HTTP integration, or production storage.
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
from app.core.nova.work_revenue.operations_local_artifact_store import (
    LocalPrivateArtifactStore,
)
from app.core.nova.work_revenue.operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope,
)


def _new_manifest(owner, data):
    job = TenantJobScope(tenant_id=owner, job_id=str(uuid4()))
    return build_artifact_manifest(
        acting_tenant_id=owner, job=job,
        artifact_id=str(uuid4()), content=data,
    )


def _persist(connection, store, owner, manifest, content):
    # File and SQL writes are deliberately NOT atomic. Production needs a
    # recovery protocol and garbage collection for orphaned private objects.
    store.put(acting_tenant_id=owner, manifest=manifest, content=content)
    save_manifest(connection, acting_tenant_id=owner, manifest=manifest)


def test_restart_approval_and_cross_tenant_denial(tmp_path):
    database = tmp_path / "registry.sqlite"
    store = LocalPrivateArtifactStore(tmp_path / "private")
    owner = str(uuid4())
    intruder = str(uuid4())
    content = b"item,amount\nservice,15\n"
    manifest = _new_manifest(owner, content)

    with sqlite3.connect(database) as connection:
        initialize_registry(connection)
        _persist(connection, store, owner, manifest, content)

    # Reopen database and artifact store to exercise disk persistence.
    store = LocalPrivateArtifactStore(tmp_path / "private")
    with sqlite3.connect(database) as connection:
        saved = load_manifest(
            connection, acting_tenant_id=owner,
            job=manifest.job, artifact_id=manifest.artifact_id,
        )
        with pytest.raises(TenantAccessDenied):
            store.get(acting_tenant_id=owner, manifest=saved)
        with pytest.raises(TenantAccessDenied):
            store.get(acting_tenant_id=intruder, manifest=saved)
        with pytest.raises(TenantAccessDenied):
            approve_download(
                connection, acting_tenant_id=intruder,
                job=manifest.job, artifact_id=manifest.artifact_id,
            )
        approve_download(
            connection, acting_tenant_id=owner,
            job=manifest.job, artifact_id=manifest.artifact_id,
        )
        approved = load_manifest(
            connection, acting_tenant_id=owner,
            job=manifest.job, artifact_id=manifest.artifact_id,
        )
        assert store.get(
            acting_tenant_id=owner, manifest=approved
        ) == content
        with pytest.raises(TenantAccessDenied):
            store.get(acting_tenant_id=intruder, manifest=approved)


def test_tampered_bytes_fail_after_database_approval(tmp_path):
    store = LocalPrivateArtifactStore(tmp_path / "private")
    owner = str(uuid4())
    original = b"item,total\nA,15\n"
    manifest = _new_manifest(owner, original)
    with sqlite3.connect(tmp_path / "registry.sqlite") as connection:
        initialize_registry(connection)
        _persist(connection, store, owner, manifest, original)
        approve_download(
            connection, acting_tenant_id=owner,
            job=manifest.job, artifact_id=manifest.artifact_id,
        )
        approved = load_manifest(
            connection, acting_tenant_id=owner,
            job=manifest.job, artifact_id=manifest.artifact_id,
        )
        file_path = next((tmp_path / "private").iterdir())
        file_path.write_bytes(b"item,total\nA,99\n")
        with pytest.raises(TenantAccessDenied):
            store.get(acting_tenant_id=owner, manifest=approved)


def test_duplicate_registry_record_reveals_nonatomic_orphan_risk(tmp_path):
    store = LocalPrivateArtifactStore(tmp_path / "private")
    owner = str(uuid4())
    first = _new_manifest(owner, b"a,b\n1,2\n")
    second = _new_manifest(owner, b"a,b\n3,4\n")
    with sqlite3.connect(":memory:") as connection:
        initialize_registry(connection)
        _persist(connection, store, owner, first, b"a,b\n1,2\n")
        # Simulate SQL failure after a successful second file write by
        # pre-creating the same primary-key row. The file remains orphaned.
        save_manifest(connection, acting_tenant_id=owner, manifest=second)
        other_owner = str(uuid4())
        conflicting = build_artifact_manifest(
            acting_tenant_id=other_owner,
            job=TenantJobScope(tenant_id=other_owner, job_id=str(uuid4())),
            artifact_id=str(uuid4()), content=b"x,y\n5,6\n",
        )
        store.put(
            acting_tenant_id=other_owner,
            manifest=conflicting, content=b"x,y\n5,6\n",
        )
        with pytest.raises(sqlite3.IntegrityError):
            save_manifest(
                connection, acting_tenant_id=owner, manifest=first
            )
        # Existing metadata must remain intact after duplicate rejection.
        assert load_manifest(
            connection, acting_tenant_id=owner,
            job=first.job, artifact_id=first.artifact_id,
        ) == first
        with pytest.raises(TenantAccessDenied):
            load_manifest(
                connection, acting_tenant_id=other_owner,
                job=conflicting.job, artifact_id=conflicting.artifact_id,
            )
    assert len(list((tmp_path / "private").iterdir())) == 3
