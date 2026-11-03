"""Read-only artifact reconciliation tests with synthetic files."""
import sqlite3
from uuid import uuid4

from app.core.nova.work_revenue.operations_artifact_manifest import (
    build_artifact_manifest,
)
from app.core.nova.work_revenue.operations_artifact_registry import (
    initialize_registry, save_manifest,
)
from app.core.nova.work_revenue.operations_artifact_inventory import (
    inventory_local_artifacts,
)
from app.core.nova.work_revenue.operations_local_artifact_store import (
    LocalPrivateArtifactStore,
)
from app.core.nova.work_revenue.operations_tenant_scope import TenantJobScope


def _new(owner, payload):
    return build_artifact_manifest(
        acting_tenant_id=owner,
        job=TenantJobScope(tenant_id=owner, job_id=str(uuid4())),
        artifact_id=str(uuid4()), content=payload,
    )


def test_inventory_reports_orphans_and_missing_files_without_deleting(tmp_path):
    store = LocalPrivateArtifactStore(tmp_path / "private")
    owner = str(uuid4())
    intact = _new(owner, b"a,b\n1,2\n")
    missing = _new(owner, b"a,b\n3,4\n")
    orphan = _new(owner, b"a,b\n5,6\n")
    with sqlite3.connect(":memory:") as connection:
        initialize_registry(connection)
        store.put(
            acting_tenant_id=owner, manifest=intact, content=b"a,b\n1,2\n"
        )
        save_manifest(connection, acting_tenant_id=owner, manifest=intact)
        save_manifest(connection, acting_tenant_id=owner, manifest=missing)
        store.put(
            acting_tenant_id=owner, manifest=orphan, content=b"a,b\n5,6\n"
        )
        before = sorted(p.name for p in store.root.iterdir())
        result = inventory_local_artifacts(connection, store)
        after = sorted(p.name for p in store.root.iterdir())
        assert before == after
        assert len(result.registered_files) == 1
        assert len(result.unregistered_files) == 1
        assert len(result.missing_files) == 1
        assert not result.unexpected_entries


def test_inventory_classifies_symlink_as_unexpected(tmp_path):
    store = LocalPrivateArtifactStore(tmp_path / "private")
    link = store.root / ("a" * 64 + ".artifact")
    destination = tmp_path / "elsewhere"
    destination.write_bytes(b"not customer data")
    link.symlink_to(destination)
    with sqlite3.connect(":memory:") as connection:
        initialize_registry(connection)
        result = inventory_local_artifacts(connection, store)
        assert result.unexpected_entries == (link.name,)
        assert link.is_symlink()
