"""Offline tenant authorization contract for future Operations CSV jobs.

These helpers do not register routes, write customer artifacts, or trust tenant IDs
from request payloads. The authenticated server must supply the acting tenant.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


class TenantAccessDenied(PermissionError):
    """A job or artifact cannot be accessed by the authenticated tenant."""


def _canonical_id(raw: str) -> str:
    if not isinstance(raw, str):
        raise TenantAccessDenied("Tenant or job identity is invalid")
    try:
        value = UUID(raw)
    except (ValueError, AttributeError, TypeError) as exc:
        raise TenantAccessDenied("Tenant or job identity is invalid") from exc
    if str(value) != raw or value.int == 0:
        raise TenantAccessDenied("Tenant or job identity is invalid")
    return str(value)


@dataclass(frozen=True)
class TenantJobScope:
    tenant_id: str
    job_id: str

    def __post_init__(self) -> None:
        _canonical_id(self.tenant_id)
        _canonical_id(self.job_id)


def authorize_tenant_job(*, acting_tenant_id: str, job: TenantJobScope) -> None:
    """Fail closed unless server-authenticated tenant owns the job."""
    caller = _canonical_id(acting_tenant_id)
    if not isinstance(job, TenantJobScope):
        raise TenantAccessDenied("Job ownership is not established")
    owner = _canonical_id(job.tenant_id)
    if caller != owner:
        raise TenantAccessDenied("Job is not accessible")


def artifact_storage_key(*, acting_tenant_id: str, job: TenantJobScope,
                         artifact_id: str) -> str:
    """Return an opaque private storage key only after ownership verification.

    The caller must still use an access-controlled private object store, enforce
    server-side authorization on every read, and avoid client-provided object keys.
    """
    authorize_tenant_job(acting_tenant_id=acting_tenant_id, job=job)
    artifact = _canonical_id(artifact_id)
    return f"operations-csv/tenants/{job.tenant_id}/jobs/{job.job_id}/artifacts/{artifact}"
