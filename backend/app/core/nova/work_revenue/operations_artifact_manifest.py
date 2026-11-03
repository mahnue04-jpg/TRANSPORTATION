"""Offline private artifact manifest and integrity checks for Operations CSV.

No provider, disk, database, network, or API integration. The caller must load
trusted artifact metadata from its tenant-filtered database transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest

from .operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope, artifact_storage_key,
    authorize_tenant_job,
)


@dataclass(frozen=True)
class ArtifactManifest:
    job: TenantJobScope
    artifact_id: str
    storage_key: str
    byte_count: int
    sha256_hex: str
    approved_for_download: bool = False


def build_artifact_manifest(
    *, acting_tenant_id: str, job: TenantJobScope, artifact_id: str,
    content: bytes,
) -> ArtifactManifest:
    """Build private metadata; do not persist or expose raw content here."""
    key = artifact_storage_key(
        acting_tenant_id=acting_tenant_id, job=job, artifact_id=artifact_id
    )
    if not isinstance(content, bytes) or not content:
        raise ValueError("Artifact bytes are required")
    return ArtifactManifest(
        job=job, artifact_id=artifact_id, storage_key=key,
        byte_count=len(content), sha256_hex=sha256(content).hexdigest(),
    )


def authorize_artifact_download(
    *, acting_tenant_id: str, manifest: ArtifactManifest, content: bytes,
) -> bytes:
    """Fail closed before returning bytes, including on integrity mismatch.

    The manifest MUST originate from a trusted tenant-filtered database query,
    not an HTTP request or an untrusted object-store header. The caller must
    load content from a private store with server credentials and audit access.
    """
    if not isinstance(manifest, ArtifactManifest):
        raise TenantAccessDenied("Artifact metadata is not trusted")
    authorize_tenant_job(acting_tenant_id=acting_tenant_id, job=manifest.job)
    expected_key = artifact_storage_key(
        acting_tenant_id=acting_tenant_id, job=manifest.job,
        artifact_id=manifest.artifact_id,
    )
    if not compare_digest(expected_key, manifest.storage_key):
        raise TenantAccessDenied("Artifact ownership or key mismatch")
    if manifest.approved_for_download is not True:
        raise TenantAccessDenied("Artifact download requires human approval")
    if not isinstance(content, bytes) or len(content) != manifest.byte_count:
        raise TenantAccessDenied("Artifact content failed integrity checks")
    if not isinstance(manifest.sha256_hex, str) or not compare_digest(
        sha256(content).hexdigest(), manifest.sha256_hex
    ):
        raise TenantAccessDenied("Artifact content failed integrity checks")
    return content
