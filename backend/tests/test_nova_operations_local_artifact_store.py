"""Isolated filesystem adapter tests. No production paths or customer data."""
import os
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.nova.work_revenue.operations_artifact_manifest import (
    build_artifact_manifest,
)
from app.core.nova.work_revenue.operations_local_artifact_store import (
    LocalPrivateArtifactStore,
)
from app.core.nova.work_revenue.operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope,
)


def _sample():
    tenant = str(uuid4())
    job = TenantJobScope(tenant_id=tenant, job_id=str(uuid4()))
    content = b"item,total\nA,15\n"
    manifest = build_artifact_manifest(
        acting_tenant_id=tenant, job=job,
        artifact_id=str(uuid4()), content=content,
    )
    return tenant, manifest, content


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only storage adapter")
def test_private_write_requires_approval_for_read(tmp_path):
    owner, manifest, content = _sample()
    store = LocalPrivateArtifactStore(tmp_path / "private")
    store.put(acting_tenant_id=owner, manifest=manifest, content=content)
    paths = list((tmp_path / "private").iterdir())
    assert len(paths) == 1
    assert manifest.artifact_id not in paths[0].name
    assert paths[0].stat().st_mode & 0o777 == 0o600
    with pytest.raises(TenantAccessDenied):
        store.get(acting_tenant_id=owner, manifest=manifest)
    assert store.get(
        acting_tenant_id=owner,
        manifest=replace(manifest, approved_for_download=True),
    ) == content


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only storage adapter")
def test_cross_tenant_read_write_denied(tmp_path):
    owner, manifest, content = _sample()
    store = LocalPrivateArtifactStore(tmp_path / "private")
    with pytest.raises(TenantAccessDenied):
        store.put(
            acting_tenant_id=str(uuid4()),
            manifest=manifest, content=content,
        )
    store.put(acting_tenant_id=owner, manifest=manifest, content=content)
    with pytest.raises(TenantAccessDenied):
        store.get(
            acting_tenant_id=str(uuid4()),
            manifest=replace(manifest, approved_for_download=True),
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only storage adapter")
def test_tampering_and_duplicate_writes_fail(tmp_path):
    owner, manifest, content = _sample()
    store = LocalPrivateArtifactStore(tmp_path / "private")
    store.put(acting_tenant_id=owner, manifest=manifest, content=content)
    with pytest.raises(FileExistsError):
        store.put(acting_tenant_id=owner, manifest=manifest, content=content)
    file = next((tmp_path / "private").iterdir())
    file.write_bytes(b"item,total\nA,99\n")
    with pytest.raises(TenantAccessDenied):
        store.get(
            acting_tenant_id=owner,
            manifest=replace(manifest, approved_for_download=True),
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only storage adapter")
def test_symlink_root_and_artifact_rejected(tmp_path):
    destination = tmp_path / "destination"
    destination.mkdir()
    shortcut = tmp_path / "shortcut"
    shortcut.symlink_to(destination, target_is_directory=True)
    with pytest.raises(TenantAccessDenied):
        LocalPrivateArtifactStore(shortcut)
    owner, manifest, _ = _sample()
    store = LocalPrivateArtifactStore(tmp_path / "private")
    key_name = sha256(manifest.storage_key.encode("utf-8")).hexdigest() + ".artifact"
    (tmp_path / "private" / key_name).symlink_to(destination)
    with pytest.raises(OSError):
        store.get(
            acting_tenant_id=owner,
            manifest=replace(manifest, approved_for_download=True),
        )
