"""Offline immutable artifact-job link tests using SQLite only."""
import sqlite3
from uuid import uuid4

import pytest

from app.core.nova.work_revenue.operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope,
)
from app.core.nova.work_revenue.operations_upload_leases import (
    acquire_upload_lease, initialize_upload_leases,
)
from app.core.nova.work_revenue.operations_upload_artifact_links import (
    initialize_upload_artifact_links, link_artifact_to_active_upload,
    linked_storage_keys, list_job_artifact_links,
)


def _setup(connection):
    initialize_upload_leases(connection)
    initialize_upload_artifact_links(connection)


def _new_job():
    tenant = str(uuid4())
    return tenant, TenantJobScope(tenant_id=tenant, job_id=str(uuid4()))


def test_link_is_durable_and_tenant_scoped(tmp_path):
    path = tmp_path / "links.db"
    owner, job = _new_job()
    artifact_id = str(uuid4())
    with sqlite3.connect(path) as connection:
        _setup(connection)
        lease = acquire_upload_lease(
            connection, acting_tenant_id=owner, job=job, now=100,
        )
        link = link_artifact_to_active_upload(
            connection, acting_tenant_id=owner,
            lease=lease, artifact_id=artifact_id, now=101,
        )
    with sqlite3.connect(path) as connection:
        assert list_job_artifact_links(
            connection, acting_tenant_id=owner, lease=lease
        ) == (link,)
        assert linked_storage_keys(connection) == frozenset([link.storage_key])
        with pytest.raises(TenantAccessDenied):
            list_job_artifact_links(
                connection, acting_tenant_id=str(uuid4()), lease=lease,
            )


def test_expired_lease_cannot_create_artifact_link():
    owner, job = _new_job()
    with sqlite3.connect(":memory:") as connection:
        _setup(connection)
        lease = acquire_upload_lease(
            connection, acting_tenant_id=owner,
            job=job, now=100, ttl_seconds=2,
        )
        with pytest.raises(TenantAccessDenied):
            link_artifact_to_active_upload(
                connection, acting_tenant_id=owner,
                lease=lease, artifact_id=str(uuid4()), now=102,
            )
        assert not linked_storage_keys(connection)


def test_replaced_lease_token_cannot_link():
    owner, job = _new_job()
    with sqlite3.connect(":memory:") as connection:
        _setup(connection)
        old = acquire_upload_lease(
            connection, acting_tenant_id=owner,
            job=job, now=100, ttl_seconds=2,
        )
        current = acquire_upload_lease(
            connection, acting_tenant_id=owner, job=job, now=102,
        )
        with pytest.raises(TenantAccessDenied):
            link_artifact_to_active_upload(
                connection, acting_tenant_id=owner,
                lease=old, artifact_id=str(uuid4()), now=103,
            )
        link = link_artifact_to_active_upload(
            connection, acting_tenant_id=owner,
            lease=current, artifact_id=str(uuid4()), now=103,
        )
        assert link.lease_token == current.token


def test_duplicate_mapping_fails_without_replacement():
    owner, job = _new_job()
    artifact_id = str(uuid4())
    with sqlite3.connect(":memory:") as connection:
        _setup(connection)
        lease = acquire_upload_lease(
            connection, acting_tenant_id=owner, job=job, now=100,
        )
        first = link_artifact_to_active_upload(
            connection, acting_tenant_id=owner,
            lease=lease, artifact_id=artifact_id, now=101,
        )
        with pytest.raises(sqlite3.IntegrityError):
            link_artifact_to_active_upload(
                connection, acting_tenant_id=owner,
                lease=lease, artifact_id=artifact_id, now=101,
            )
        assert list_job_artifact_links(
            connection, acting_tenant_id=owner, lease=lease
        ) == (first,)


def test_cross_tenant_attempt_fails_closed():
    owner, job = _new_job()
    with sqlite3.connect(":memory:") as connection:
        _setup(connection)
        lease = acquire_upload_lease(
            connection, acting_tenant_id=owner, job=job, now=100,
        )
        with pytest.raises(TenantAccessDenied):
            link_artifact_to_active_upload(
                connection, acting_tenant_id=str(uuid4()),
                lease=lease, artifact_id=str(uuid4()), now=101,
            )
        assert not linked_storage_keys(connection)
