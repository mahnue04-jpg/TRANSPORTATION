"""Offline tenant access checks. No live API, database, or storage required."""
from uuid import uuid4

import pytest

from app.core.nova.work_revenue.operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope, artifact_storage_key,
    authorize_tenant_job,
)


def test_owner_can_scope_job_and_build_private_artifact_key():
    owner, job_id, artifact = str(uuid4()), str(uuid4()), str(uuid4())
    job = TenantJobScope(tenant_id=owner, job_id=job_id)
    authorize_tenant_job(acting_tenant_id=owner, job=job)
    assert artifact_storage_key(
        acting_tenant_id=owner, job=job, artifact_id=artifact
    ) == f"operations-csv/tenants/{owner}/jobs/{job_id}/artifacts/{artifact}"


def test_other_tenant_cannot_access_job_or_artifact():
    owner, intruder = str(uuid4()), str(uuid4())
    job = TenantJobScope(tenant_id=owner, job_id=str(uuid4()))
    with pytest.raises(TenantAccessDenied):
        authorize_tenant_job(acting_tenant_id=intruder, job=job)
    with pytest.raises(TenantAccessDenied):
        artifact_storage_key(
            acting_tenant_id=intruder, job=job, artifact_id=str(uuid4())
        )


@pytest.mark.parametrize("identity", [
    "", "not-a-uuid", "../tenant", "00000000-0000-0000-0000-000000000000",
    "AAAAAAAA-AAAA-4AAA-AAAA-AAAAAAAAAAAA", None,
])
def test_invalid_authenticated_tenant_denied(identity):
    job = TenantJobScope(tenant_id=str(uuid4()), job_id=str(uuid4()))
    with pytest.raises(TenantAccessDenied):
        authorize_tenant_job(acting_tenant_id=identity, job=job)


def test_missing_or_untrusted_job_ownership_denied():
    with pytest.raises(TenantAccessDenied):
        authorize_tenant_job(acting_tenant_id=str(uuid4()), job=None)
    with pytest.raises(TenantAccessDenied):
        TenantJobScope(tenant_id="../other", job_id=str(uuid4()))


@pytest.mark.parametrize("artifact", ["../secret", "", "not-an-id", None])
def test_artifact_id_cannot_supply_object_path(artifact):
    owner = str(uuid4())
    job = TenantJobScope(tenant_id=owner, job_id=str(uuid4()))
    with pytest.raises(TenantAccessDenied):
        artifact_storage_key(
            acting_tenant_id=owner, job=job, artifact_id=artifact
        )
