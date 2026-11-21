"""No destructive action: active leases protect every orphan candidate."""
import sqlite3
from uuid import uuid4

from app.core.nova.work_revenue.operations_artifact_inventory import OrphanInventory
from app.core.nova.work_revenue.operations_recovery_triage import (
    FileObservation, OrphanScan,
)
from app.core.nova.work_revenue.operations_recovery_with_leases import (
    audit_with_upload_leases,
)
from app.core.nova.work_revenue.operations_tenant_scope import TenantJobScope
from app.core.nova.work_revenue.operations_upload_leases import (
    acquire_upload_lease, finish_upload_lease, initialize_upload_leases,
)


def _scan(at):
    return OrphanScan(
        observed_at=at,
        inventory=OrphanInventory(
            registered_files=("registered.artifact",),
            unregistered_files=("unregistered.artifact",),
            missing_files=(),
            unexpected_entries=(),
        ),
        files=(
            FileObservation(
                name="unregistered.artifact", size=12, modified_at=100
            ),
        ),
    )


def test_any_live_lease_blocks_review_even_without_artifact_linkage():
    tenant = str(uuid4())
    job = TenantJobScope(tenant_id=tenant, job_id=str(uuid4()))
    with sqlite3.connect(":memory:") as connection:
        initialize_upload_leases(connection)
        acquire_upload_lease(
            connection, acting_tenant_id=tenant, job=job,
            now=4000, ttl_seconds=300,
        )
        report = audit_with_upload_leases(
            connection, previous=_scan(3700), current=_scan(4100),
        )
        assert report.blocked_by_active_uploads
        assert report.active_upload_jobs == 1
        assert report.triage.needs_review == ()
        assert "unregistered.artifact" in report.triage.protected


def test_finished_upload_no_longer_blocks_review_only():
    tenant = str(uuid4())
    job = TenantJobScope(tenant_id=tenant, job_id=str(uuid4()))
    with sqlite3.connect(":memory:") as connection:
        initialize_upload_leases(connection)
        lease = acquire_upload_lease(
            connection, acting_tenant_id=tenant, job=job,
            now=4000, ttl_seconds=300,
        )
        finish_upload_lease(
            connection, acting_tenant_id=tenant,
            lease=lease, success=True, now=4001,
        )
        report = audit_with_upload_leases(
            connection, previous=_scan(3700), current=_scan(4100),
        )
        assert report.active_upload_jobs == 0
        assert not report.blocked_by_active_uploads
        assert report.triage.needs_review == ("unregistered.artifact",)


def test_expired_upload_has_no_live_lease_but_does_not_delete():
    tenant = str(uuid4())
    job = TenantJobScope(tenant_id=tenant, job_id=str(uuid4()))
    with sqlite3.connect(":memory:") as connection:
        initialize_upload_leases(connection)
        acquire_upload_lease(
            connection, acting_tenant_id=tenant, job=job,
            now=3800, ttl_seconds=10,
        )
        report = audit_with_upload_leases(
            connection, previous=_scan(3700), current=_scan(4100),
        )
        assert report.triage.needs_review == ("unregistered.artifact",)
        # Recovery remains a report-only result; the caller does not mutate
        # the database or storage.
        assert report.active_upload_jobs == 0
