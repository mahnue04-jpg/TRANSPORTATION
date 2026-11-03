"""Isolated local-file adapter for testing private Operations CSV artifacts.

NOT wired to any HTTP route or production filesystem. A production adapter
requires managed encrypted object storage, audited credentials, lifecycle
controls, and transactional linkage to trusted database metadata.
"""
from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

from .operations_artifact_manifest import (
    ArtifactManifest, authorize_artifact_download,
)
from .operations_tenant_scope import (
    TenantAccessDenied, artifact_storage_key, authorize_tenant_job,
)

_MAX_BYTES = 1_000_000


class LocalPrivateArtifactStore:
    """Ephemeral single-directory adapter; opaque filenames and exclusive writes."""

    def __init__(self, root: Path):
        self.root = Path(root)
        if self.root.is_symlink():
            raise TenantAccessDenied("Unsafe storage root")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise TenantAccessDenied("Unsafe storage root")
        if os.name != "posix":
            raise RuntimeError("Test adapter requires POSIX no-follow support")
        self.root.chmod(0o700)

    @staticmethod
    def _opaque_name(key: str) -> str:
        return sha256(key.encode("utf-8")).hexdigest() + ".artifact"

    def _open_root(self) -> int:
        return os.open(
            self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )

    @staticmethod
    def _validate_manifest(tenant_id: str, manifest: ArtifactManifest) -> str:
        if not isinstance(manifest, ArtifactManifest):
            raise TenantAccessDenied("Artifact metadata is required")
        authorize_tenant_job(
            acting_tenant_id=tenant_id, job=manifest.job
        )
        expected = artifact_storage_key(
            acting_tenant_id=tenant_id, job=manifest.job,
            artifact_id=manifest.artifact_id,
        )
        if manifest.storage_key != expected:
            raise TenantAccessDenied("Artifact key mismatch")
        return expected

    def put(
        self, *, acting_tenant_id: str, manifest: ArtifactManifest,
        content: bytes,
    ) -> None:
        key = self._validate_manifest(acting_tenant_id, manifest)
        if (
            not isinstance(content, bytes)
            or not 0 < len(content) <= _MAX_BYTES
            or len(content) != manifest.byte_count
            or sha256(content).hexdigest() != manifest.sha256_hex
        ):
            raise TenantAccessDenied("Artifact integrity failed")
        root_fd = self._open_root()
        try:
            fd = os.open(
                self._opaque_name(key),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=root_fd,
            )
            try:
                with os.fdopen(fd, "wb", closefd=True) as file:
                    file.write(content)
                    file.flush()
                    os.fsync(file.fileno())
            except BaseException:
                try:
                    os.unlink(self._opaque_name(key), dir_fd=root_fd)
                except FileNotFoundError:
                    pass
                raise
        finally:
            os.close(root_fd)

    def get(
        self, *, acting_tenant_id: str, manifest: ArtifactManifest,
    ) -> bytes:
        key = self._validate_manifest(acting_tenant_id, manifest)
        if manifest.approved_for_download is not True:
            raise TenantAccessDenied("Artifact download requires approval")
        root_fd = self._open_root()
        try:
            fd = os.open(
                self._opaque_name(key), os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=root_fd,
            )
            with os.fdopen(fd, "rb", closefd=True) as file:
                content = file.read(_MAX_BYTES + 1)
        finally:
            os.close(root_fd)
        return authorize_artifact_download(
            acting_tenant_id=acting_tenant_id,
            manifest=manifest,
            content=content,
        )
