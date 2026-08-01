"""Secure document storage interface with local development adapter."""
from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from app.helpers import uuid4

STORAGE_BACKEND_LOCAL_DEV = "local_dev"
STORAGE_BACKEND_PENDING_PRODUCTION = "pending_production"


class DocumentStorageBackend(ABC):
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
    def delete(self, *, storage_ref: str) -> None:
        ...


class LocalDocumentStorage(DocumentStorageBackend):
    """Development-only storage. NOT production-ready."""

    def __init__(self, base_dir: Path | None = None) -> None:
        root = base_dir or Path(__file__).resolve().parents[3] / "data" / "onboarding_docs"
        self.base_dir = root
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _target_path(self, organization_id: str, application_id: str, category: str, filename: str) -> Path:
        safe_name = os.path.basename(filename).replace("..", "_")
        digest = hashlib.sha256(f"{application_id}:{category}:{safe_name}".encode()).hexdigest()[:12]
        folder = self.base_dir / organization_id / application_id / category
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{digest}_{safe_name}"

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
        return STORAGE_BACKEND_LOCAL_DEV, storage_ref, len(data)

    def delete(self, *, storage_ref: str) -> None:
        path = self.base_dir / storage_ref
        if path.exists() and path.is_file():
            path.unlink()


def get_document_storage() -> DocumentStorageBackend:
    backend = os.getenv("PLATFORM_OPS_DOCUMENT_STORAGE", STORAGE_BACKEND_LOCAL_DEV).strip().lower()
    if backend in {STORAGE_BACKEND_LOCAL_DEV, STORAGE_BACKEND_PENDING_PRODUCTION}:
        return LocalDocumentStorage()
    return LocalDocumentStorage()
