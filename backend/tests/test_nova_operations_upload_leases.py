"""Isolated durable upload-lease tests with synthetic identities."""
import sqlite3
from uuid import uuid4

import pytest

from app.core.nova.work_revenue.operations_upload_leases import (
    acquire_upload_lease, active_lease_expirations,
    finish_upload_lease, initialize_upload_leases, renew_upload_lease,
)
from app.core.nova.work_revenue.operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope,
)


def _job():
    tenant = str(uuid4())
    return tenant, TenantJobScope(tenant_id=tenant, job_id=str(uuid4()))


def test_durable_lease_blocks_parallel_upload_and_reopens(tmp_path):
    db = tmp_path / "leases.db"
    tenant, job = _job()
    with sqlite3.connect(db) as connection:
        initialize_upload_leases(connection)
        first = acquire_upload_lease(
            connection, acting_tenant_id=tenant, job=job, now=1000,
        )
        with pytest.raises(TenantAccessDenied):
            acquire_upload_lease(
                connection, acting_tenant_id=tenant, job=job, now=1001,
            )
    with sqlite3.connect(db) as connection:
        assert active_lease_expirations(connection, at=1001) == {
            (tenant, job.job_id): first.expires_at
        }
        second = renew_upload_lease(
            connection, acting_tenant_id=tenant, lease=first, now=1100
        )
        assert second.expires_at == 1400
        finish_upload_lease(
            connection, acting_tenant_id=tenant,
            lease=second, success=True, now=1200,
        )
        assert active_lease_expirations(connection, at=1200) == {}
        replacement = acquire_upload_lease(
            connection, acting_tenant_id=tenant, job=job, now=1201
        )
        assert replacement.token != first.token
        with pytest.raises(TenantAccessDenied):
            renew_upload_lease(
                connection, acting_tenant_id=tenant, lease=first, now=1202
            )


def test_expiry_reclaim_and_stale_token_cannot_finish():
    tenant, job = _job()
    with sqlite3.connect(":memory:") as connection:
        initialize_upload_leases(connection)
        old = acquire_upload_lease(
            connection, acting_tenant_id=tenant,
            job=job, now=500, ttl_seconds=10,
        )
        current = acquire_upload_lease(
            connection, acting_tenant_id=tenant, job=job, now=510
        )
        assert old.token != current.token
        with pytest.raises(TenantAccessDenied):
            finish_upload_lease(
                connection, acting_tenant_id=tenant,
                lease=old, success=False, now=511,
            )
        assert (tenant, job.job_id) in active_lease_expirations(
            connection, at=511
        )


def test_cross_tenant_cannot_acquire_or_complete():
    tenant, job = _job()
    other = str(uuid4())
    with sqlite3.connect(":memory:") as connection:
        initialize_upload_leases(connection)
        with pytest.raises(TenantAccessDenied):
            acquire_upload_lease(
                connection, acting_tenant_id=other, job=job, now=100,
            )
        lease = acquire_upload_lease(
            connection, acting_tenant_id=tenant, job=job, now=100,
        )
        with pytest.raises(TenantAccessDenied):
            finish_upload_lease(
                connection, acting_tenant_id=other,
                lease=lease, success=True, now=110,
            )


@pytest.mark.parametrize("ttl", [0, -1, 3601, True, 1.5])
def test_invalid_ttl_rejected(ttl):
    tenant, job = _job()
    with sqlite3.connect(":memory:") as connection:
        initialize_upload_leases(connection)
        with pytest.raises(ValueError):
            acquire_upload_lease(
                connection, acting_tenant_id=tenant,
                job=job, now=100, ttl_seconds=ttl,
            )
