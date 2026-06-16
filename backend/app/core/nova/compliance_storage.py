from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from app.helpers import uuid4


class SecureDocumentStorageAbstraction:
    def store_document(self, *, document_id: str, content: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError()

    def retrieve_document(self, *, immutable_reference_id: str) -> dict[str, Any] | None:
        raise NotImplementedError()

    def generate_signed_access(self, *, immutable_reference_id: str, expires_at: datetime, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError()

    def revoke_access(self, *, signed_access_id: str) -> bool:
        raise NotImplementedError()

    def verify_integrity(self, *, immutable_reference_id: str, expected_checksum: str) -> bool:
        raise NotImplementedError()


class InMemorySecureDocumentStorage(SecureDocumentStorageAbstraction):
    def __init__(self) -> None:
        self._documents: dict[str, dict[str, Any]] = {}
        self._signed_access: dict[str, dict[str, Any]] = {}

    def store_document(self, *, document_id: str, content: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        checksum = hashlib.sha256(content).hexdigest()
        immutable_reference_id = str(metadata.get("immutable_reference_id") or f"imm-{uuid4()}")
        record = {
            "document_id": document_id,
            "immutable_reference_id": immutable_reference_id,
            "content": content,
            "checksum": checksum,
            "metadata": metadata,
            "stored_at": datetime.now(timezone.utc),
        }
        self._documents[immutable_reference_id] = record
        return {
            "document_id": document_id,
            "immutable_reference_id": immutable_reference_id,
            "checksum": checksum,
            "storage_provider": str(metadata.get("storage_provider") or "local_abstraction"),
            "mime_type": str(metadata.get("mime_type") or "application/octet-stream"),
            "retention_class": str(metadata.get("retention_class") or "operational"),
            "encryption_status": str(metadata.get("encryption_status") or "encrypted_at_rest"),
        }

    def retrieve_document(self, *, immutable_reference_id: str) -> dict[str, Any] | None:
        record = self._documents.get(immutable_reference_id)
        if record is None:
            return None
        return {
            "document_id": record["document_id"],
            "immutable_reference_id": immutable_reference_id,
            "checksum": record["checksum"],
            "mime_type": str((record.get("metadata") or {}).get("mime_type") or "application/octet-stream"),
            "size_bytes": len(record.get("content") or b""),
            "metadata": record.get("metadata") or {},
        }

    def generate_signed_access(self, *, immutable_reference_id: str, expires_at: datetime, context: dict[str, Any]) -> dict[str, Any]:
        signed_access_id = f"sga-{uuid4()}"
        token_seed = f"{immutable_reference_id}:{signed_access_id}:{expires_at.isoformat()}".encode("utf-8")
        token = hashlib.sha256(token_seed).hexdigest()
        self._signed_access[signed_access_id] = {
            "immutable_reference_id": immutable_reference_id,
            "expires_at": expires_at,
            "token": token,
            "context": context,
            "revoked": False,
        }
        return {
            "signed_access_id": signed_access_id,
            "token": token,
            "expires_at": expires_at.isoformat(),
        }

    def revoke_access(self, *, signed_access_id: str) -> bool:
        row = self._signed_access.get(signed_access_id)
        if row is None:
            return False
        row["revoked"] = True
        row["revoked_at"] = datetime.now(timezone.utc)
        return True

    def verify_integrity(self, *, immutable_reference_id: str, expected_checksum: str) -> bool:
        row = self._documents.get(immutable_reference_id)
        if row is None:
            return False
        return str(row.get("checksum") or "") == str(expected_checksum or "")

    def validate_signed_access(self, *, signed_access_id: str) -> dict[str, Any] | None:
        row = self._signed_access.get(signed_access_id)
        if row is None:
            return None
        if bool(row.get("revoked")):
            return None
        expires_at = row.get("expires_at")
        if not isinstance(expires_at, datetime):
            return None
        if expires_at < datetime.now(timezone.utc):
            return None
        return row


storage_abstraction = InMemorySecureDocumentStorage()
