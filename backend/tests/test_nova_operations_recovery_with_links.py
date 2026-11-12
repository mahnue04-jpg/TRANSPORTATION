"""Read-only link-aware recovery tests with synthetic identities."""
import sqlite3
from hashlib import sha256
from uuid import uuid4

import pytest

from app.core.nova.work_revenue.operations_artifact_inventory import OrphanInventory
from app.core.nova.work_revenue.operations_recovery_triage import (
    FileObservation, OrphanScan,
)
from app.core.nova.work_revenue.operations_recovery_with_links import (
    audit_with_artifact_links,
)
from app.core.nova.work_revenue.operations_tenant_scope import TenantJobScope, TenantAccessDenied
from app.core.nova.work_revenue.operations_upload_leases import (
    acquire_upload_lease, finish_upload_lease, initialize_upload_leases,
)
from app.core.nova.work_revenue.operations_upload_artifact_links import (
    initialize_upload_artifact_links, link_artifact_to_active_upload,
)


def _scan(at, filenames):
    return OrphanScan(
        observed_at=at,
        inventory=OrphanInventory(
            registered_files=(), unregistered_files=tuple(filenames),
            missing_files=(), unexpected_entries=(),
        ),
        files=tuple(
            FileObservation(name=name, size=12, modified_at=100)
            for name in filenames
        ),
    )


def _new_link(connection, now=1000):
    tenant = str(uuid4())
    job = TenantJobScope(tenant_id=tenant, job_id=str(uuid4()))
    lease = acquire_upload_lease(
        connection, acting_tenant_id=tenant, job=job, now=now,
    )
    link = link_artifact_to_active_upload(
        connection, acting_tenant_id=tenant, lease=lease,
        artifact_id=str(uuid4()), now=now + 1,
    )
    name = sha256(link.storage_key.encode("utf-8")).hexdigest() + ".artifact"
    return tenant, lease, name


def test_linked_file_stays_protected_after_lease_finished():
    with sqlite3.connect(":memory:") as connection:
        initialize_upload_leases(connection)
        initialize_upload_artifact_links(connection)
        tenant, lease, linked = _new_link(connection)
        finish_upload_lease(
            connection, acting_tenant_id=tenant, lease=lease,
            success=True, now=1002,
        )
        unlinked = sha256(b"unlinked").hexdigest() + ".artifact"
        files = (linked, unlinked)
        report = audit_with_artifact_links(
            connection, previous=_scan(3700, files),
            current=_scan(4100, files),
        )
        assert report.active_upload_jobs == 0
        assert report.linked_files_protected == (linked,)
        assert linked in report.triage.protected
        assert linked not in report.triage.needs_review
        assert report.triage.needs_review == (unlinked,)


def test_active_lease_still_protects_every_orphan():
    with sqlite3.connect(":memory:") as connection:
        initialize_upload_leases(connection)
        initialize_upload_artifact_links(connection)
        _, _, linked = _new_link(connection, now=4000)
        unlinked = sha256(b"unlinked").hexdigest() + ".artifact"
        files = (linked, unlinked)
        result = audit_with_artifact_links(
            connection, previous=_scan(3700, files),
            current=_scan(4100, files),
        )
        assert result.active_upload_jobs == 1
        assert not result.triage.needs_review
        assert set(files) <= set(result.triage.protected)


def test_missing_link_table_raises_instead_of_treating_files_as_orphan():
    with sqlite3.connect(":memory:") as connection:
        initialize_upload_leases(connection)
        name = sha256(b"candidate").hexdigest() + ".artifact"
        with pytest.raises(sqlite3.OperationalError):
            audit_with_artifact_links(
                connection, previous=_scan(3700, (name,)),
                current=_scan(4100, (name,)),
            )


def test_corrupted_link_storage_key_fails_closed():
    with sqlite3.connect(":memory:") as connection:
        initialize_upload_leases(connection)
        initialize_upload_artifact_links(connection)
        tenant, lease, linked = _new_link(connection)
        connection.execute(
            """UPDATE operations_csv_upload_artifact_links
               SET storage_key = ? WHERE tenant_id = ? AND job_id = ?""",
            ("operations-csv/invalid-path", tenant, lease.job.job_id),
        )
        with pytest.raises(TenantAccessDenied, match="inconsistent"):
            audit_with_artifact_links(
                connection, previous=_scan(3700, (linked,)),
                current=_scan(4100, (linked,)),
            )


def test_malformed_link_identity_fails_closed():
    with sqlite3.connect(":memory:") as connection:
        initialize_upload_leases(connection)
        initialize_upload_artifact_links(connection)
        tenant, lease, linked = _new_link(connection)
        connection.execute(
            """UPDATE operations_csv_upload_artifact_links
               SET artifact_id = ? WHERE tenant_id = ? AND job_id = ?""",
            ("invalid-id", tenant, lease.job.job_id),
        )
        with pytest.raises(TenantAccessDenied):
            audit_with_artifact_links(
                connection, previous=_scan(3700, (linked,)),
                current=_scan(4100, (linked,)),
            )
