"""Secure document storage interface with local and persistent-volume adapters."""
from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from app.helpers import uuid4

STORAGE_BACKEND_LOCAL_DEV = "local_dev"
STORAGE_BACKEND_RENDER_DISK = "render_disk"
STORAGE_BACKEND_PENDING_PRODUCTION = "pending_production"

DEFAULT_LOCAL_ROOT = Path(__file__).resolve().parents[3] / "data" / "onboarding_docs"
DEFAULT_RENDER_DISK_ROOT = Path(os.getenv("PLATFORM_OPS_DOCUMENT_STORAGE_PATH", "/data/onboarding_docs"))


class DocumentStorageBackend(ABC):
    backend_name: str

    @abstractmethod
    def store(
        self,
        *,
        organization_id: str,
        application_id: str,
        category: str,
        filename: str,
        content_type: str,
        stream: BinaryIO,
    ) -> tuple[str, str, int]:
        """Return (backend_name, storage_ref, byte_size)."""

    @abstractmethod
    def retrieve(self, *, storage_ref: str) -> tuple[bytes, str | None]:
        """Return (file_bytes, content_type_guess)."""

    @abstractmethod
    def delete(self, *, storage_ref: str) -> None:
        ...


class _FilesystemDocumentStorage(DocumentStorageBackend):
    """Shared filesystem storage used by local dev and Render persistent disk."""

    def __init__(self, *, backend_name: str, base_dir: Path) -> None:
        self.backend_name = backend_name
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _target_path(self, organization_id: str, application_id: str, category: str, filename: str) -> Path:
        safe_name = os.path.basename(filename).replace("..", "_")
        digest = hashlib.sha256(f"{application_id}:{category}:{safe_name}".encode()).hexdigest()[:12]
        folder = self.base_dir / organization_id / application_id / category
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{digest}_{safe_name}"

    def _resolve_ref(self, storage_ref: str) -> Path:
        candidate = (self.base_dir / storage_ref).resolve()
        base = self.base_dir.resolve()
        if base not in candidate.parents and candidate != base:
            raise ValueError("Invalid storage reference.")
        return candidate

    def store(
        self,
        *,
        organization_id: str,
        application_id: str,
        category: str,
        filename: str,
        content_type: str,
        stream: BinaryIO,
    ) -> tuple[str, str, int]:
        target = self._target_path(organization_id, application_id, category, filename)
        data = stream.read()
        target.write_bytes(data)
        storage_ref = str(target.relative_to(self.base_dir))
        return self.backend_name, storage_ref, len(data)

    def retrieve(self, *, storage_ref: str) -> tuple[bytes, str | None]:
        path = self._resolve_ref(storage_ref)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(storage_ref)
        return path.read_bytes(), None

    def delete(self, *, storage_ref: str) -> None:
        path = self._resolve_ref(storage_ref)
        if path.exists() and path.is_file():
            path.unlink()


class LocalDocumentStorage(_FilesystemDocumentStorage):
    """Development storage under backend/data/onboarding_docs."""

    def __init__(self, base_dir: Path | None = None) -> None:
        super().__init__(backend_name=STORAGE_BACKEND_LOCAL_DEV, base_dir=base_dir or DEFAULT_LOCAL_ROOT)


class RenderDiskDocumentStorage(_FilesystemDocumentStorage):
    """Production staging storage on a Render persistent disk mount."""

    def __init__(self, base_dir: Path | None = None) -> None:
        super().__init__(backend_name=STORAGE_BACKEND_RENDER_DISK, base_dir=base_dir or DEFAULT_RENDER_DISK_ROOT)


def get_document_storage() -> DocumentStorageBackend:
    backend = os.getenv("PLATFORM_OPS_DOCUMENT_STORAGE", STORAGE_BACKEND_LOCAL_DEV).strip().lower()
    if backend == STORAGE_BACKEND_RENDER_DISK:
        return RenderDiskDocumentStorage()
    if backend in {STORAGE_BACKEND_LOCAL_DEV, STORAGE_BACKEND_PENDING_PRODUCTION}:
        return LocalDocumentStorage()
    return LocalDocumentStorage()


def store_bytes_for_test(
    *,
    organization_id: str,
    application_id: str,
    category: str,
    filename: str,
    content_type: str,
    payload: bytes,
) -> tuple[str, str, int]:
    """Helper for infrastructure validation scripts."""
    storage = get_document_storage()
    return storage.store(
        organization_id=organization_id,
        application_id=application_id,
        category=category,
        filename=filename,
        content_type=content_type,
        stream=BytesIO(payload),
    )
