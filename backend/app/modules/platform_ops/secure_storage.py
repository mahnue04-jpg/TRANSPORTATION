"""Production-safe document storage policy and private-object adapters.

Local development may use plaintext disk. Production fails closed unless a
private encrypted/object backend is configured. S3 credentials are not invented.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from app.modules.platform_ops.storage import (
    DEFAULT_LOCAL_ROOT,
    DocumentStorageBackend,
    LocalDocumentStorage,
    STORAGE_BACKEND_LOCAL_DEV,
    STORAGE_BACKEND_PENDING_PRODUCTION,
    STORAGE_BACKEND_RENDER_DISK,
    assert_safe_storage_ref,
    object_key_for_upload,
)

STORAGE_BACKEND_ENCRYPTED_PRIVATE = "encrypted_private"
STORAGE_BACKEND_S3_PRIVATE = "s3_private"

SECURE_STORAGE_BACKENDS = frozenset(
    {STORAGE_BACKEND_ENCRYPTED_PRIVATE, STORAGE_BACKEND_S3_PRIVATE}
)
INSECURE_STORAGE_BACKENDS = frozenset(
    {
        STORAGE_BACKEND_LOCAL_DEV,
        STORAGE_BACKEND_RENDER_DISK,
        STORAGE_BACKEND_PENDING_PRODUCTION,
        "",
    }
)

S3_BUCKET_ENV = "AMICOR_DOCUMENT_S3_BUCKET"
S3_REGION_ENV = "AMICOR_DOCUMENT_S3_REGION"
S3_ACCESS_KEY_ENV = "AMICOR_DOCUMENT_S3_ACCESS_KEY"
S3_SECRET_KEY_ENV = "AMICOR_DOCUMENT_S3_SECRET_KEY"
S3_ENDPOINT_ENV = "AMICOR_DOCUMENT_S3_ENDPOINT"
ENCRYPTION_KEY_ENV = "PLATFORM_OPS_DOCUMENT_ENCRYPTION_KEY"
STORAGE_PROVIDER_ENV = "PLATFORM_OPS_DOCUMENT_STORAGE"
MAX_BYTES_ENV = "AMICOR_DOCUMENT_MAX_BYTES"
DEFAULT_MAX_DOCUMENT_BYTES = 10 * 1024 * 1024

ALLOWED_DOCUMENT_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif",
        "text/plain",
    }
)
ALLOWED_DOCUMENT_EXTENSIONS = frozenset(
    {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".txt"}
)

_PRODUCTION_ENVS = frozenset({"production", "prod"})


def _env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


class SecureStorageNotConfigured(RuntimeError):
    """Raised when production document storage is not safely configured."""


def is_production_document_environment() -> bool:
    raw = (
        os.getenv("AMICOR_ENVIRONMENT")
        or os.getenv("ENVIRONMENT")
        or os.getenv("APP_ENV")
        or ""
    ).strip().lower()
    return raw in _PRODUCTION_ENVS


def configured_storage_backend() -> str:
    return (
        _env(STORAGE_PROVIDER_ENV, "AMICOR_DOCUMENT_STORAGE_PROVIDER")
        or STORAGE_BACKEND_LOCAL_DEV
    ).strip().lower()


def s3_bucket() -> str:
    return _env(S3_BUCKET_ENV, "AMICOR_DOCUMENT_BUCKET")


def s3_region() -> str:
    return _env(S3_REGION_ENV, "AMICOR_DOCUMENT_REGION", "AWS_DEFAULT_REGION") or "us-east-1"


def s3_access_key() -> str:
    return _env(S3_ACCESS_KEY_ENV, "AMICOR_DOCUMENT_ACCESS_KEY", "AWS_ACCESS_KEY_ID")


def s3_secret_key() -> str:
    return _env(S3_SECRET_KEY_ENV, "AMICOR_DOCUMENT_SECRET_KEY", "AWS_SECRET_ACCESS_KEY")


def s3_endpoint() -> str:
    return _env(S3_ENDPOINT_ENV)


def s3_endpoint_url() -> str | None:
    """Optional S3-compatible endpoint. Absent preserves default AWS S3. HTTPS required when set."""
    raw = s3_endpoint()
    if not raw:
        return None
    cleaned = raw.rstrip("/")
    if not cleaned.lower().startswith("https://"):
        raise SecureStorageNotConfigured(
            "COMPLIANCE_STORAGE_BLOCKED: AMICOR_DOCUMENT_S3_ENDPOINT must use https://. "
            "TLS is required for private document storage."
        )
    return cleaned


def s3_credentials_present() -> bool:
    return bool(s3_bucket() and s3_access_key() and s3_secret_key())


def s3_client_library_available() -> bool:
    try:
        import boto3  # noqa: F401
    except ImportError:
        return False
    return True


def s3_configuration_status() -> dict[str, str]:
    if not s3_credentials_present():
        return {
            "backend": STORAGE_BACKEND_S3_PRIVATE,
            "status": "BLOCKED",
            "reason": (
                "Private S3 object storage is not configured. OWNER ACTION REQUIRED: create a "
                f"private bucket with Block Public Access, then set {S3_BUCKET_ENV}, "
                f"{S3_REGION_ENV}, {S3_ACCESS_KEY_ENV}, and {S3_SECRET_KEY_ENV}. "
                "Do not invent credentials."
            ),
            "public_urls": "never",
        }
    if not s3_client_library_available():
        return {
            "backend": STORAGE_BACKEND_S3_PRIVATE,
            "status": "BLOCKED",
            "reason": (
                "S3 credentials are present but boto3 is not installed. "
                "OWNER ACTION REQUIRED: install boto3 before connecting the private bucket."
            ),
            "public_urls": "never",
        }
    try:
        s3_endpoint_url()
    except SecureStorageNotConfigured as exc:
        return {
            "backend": STORAGE_BACKEND_S3_PRIVATE,
            "status": "BLOCKED",
            "reason": str(exc).removeprefix("COMPLIANCE_STORAGE_BLOCKED: ").strip(),
            "public_urls": "never",
        }
    return {
        "backend": STORAGE_BACKEND_S3_PRIVATE,
        "status": "READY",
        "reason": "Private S3 credentials and client library are present. Bucket must remain non-public.",
        "public_urls": "never",
    }


def assert_production_storage_allowed(backend: str | None = None) -> None:
    if not is_production_document_environment():
        return
    name = (backend or configured_storage_backend()).strip().lower()
    if name == STORAGE_BACKEND_S3_PRIVATE:
        status = s3_configuration_status()
        if status["status"] != "READY":
            raise SecureStorageNotConfigured(
                "COMPLIANCE_STORAGE_BLOCKED: production document storage is s3_private "
                f"but is not ready. {status['reason']}"
            )
        return
    if name == STORAGE_BACKEND_ENCRYPTED_PRIVATE:
        key = os.getenv(ENCRYPTION_KEY_ENV, "").strip()
        if len(key) < 32:
            raise SecureStorageNotConfigured(
                f"COMPLIANCE_STORAGE_BLOCKED: {ENCRYPTION_KEY_ENV} must be at least 32 characters "
                "for encrypted_private production storage."
            )
        return
    raise SecureStorageNotConfigured(
        "COMPLIANCE_STORAGE_BLOCKED: production document storage is not securely configured. "
        f"Backend '{name or STORAGE_BACKEND_LOCAL_DEV}' is not allowed for real Driver #001 documents. "
        f"Use {STORAGE_BACKEND_ENCRYPTED_PRIVATE} with {ENCRYPTION_KEY_ENV} or configure "
        f"{STORAGE_BACKEND_S3_PRIVATE} after credentials are issued. Do not invent credentials."
    )


def max_document_bytes() -> int:
    raw = _env(MAX_BYTES_ENV)
    if not raw:
        return DEFAULT_MAX_DOCUMENT_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_DOCUMENT_BYTES
    return value if value > 0 else DEFAULT_MAX_DOCUMENT_BYTES


def validate_document_upload(*, filename: str, content_type: str, file_bytes: bytes) -> None:
    if not file_bytes:
        raise ValueError("Uploaded file is empty.")
    if len(file_bytes) > max_document_bytes():
        raise ValueError(
            f"Uploaded file exceeds the {max_document_bytes()} byte limit."
        )
    name = os.path.basename((filename or "").replace("\\", "/"))
    if not name or name in {".", ".."} or ".." in name:
        raise ValueError("Invalid upload filename.")
    ext = os.path.splitext(name)[1].lower()
    normalized_type = (content_type or "").split(";")[0].strip().lower()
    if normalized_type in {"", "application/octet-stream"}:
        normalized_type = {
            ".pdf": "application/pdf",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".heic": "image/heic",
            ".heif": "image/heif",
            ".txt": "text/plain",
        }.get(ext, normalized_type)
    if ext and ext not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValueError(f"Unsafe file type rejected: {ext}")
    if not ext and normalized_type not in ALLOWED_DOCUMENT_CONTENT_TYPES:
        raise ValueError("Unsafe file type rejected: unknown extension")
    if normalized_type not in ALLOWED_DOCUMENT_CONTENT_TYPES:
        raise ValueError(f"Unsafe content type rejected: {normalized_type or 'unknown'}")


def secure_document_storage_readiness() -> dict[str, str | bool]:
    """READY only when a production-safe private backend is actually configured."""
    backend = configured_storage_backend()
    payload: dict[str, str | bool] = {
        "key": "SECURE_DOCUMENT_STORAGE",
        "backend": backend,
        "state": "BLOCKED",
        "public_urls": "never",
        "real_document_onboarding_allowed": False,
        "activates_driver": False,
    }
    if backend == STORAGE_BACKEND_ENCRYPTED_PRIVATE:
        key = _env(ENCRYPTION_KEY_ENV)
        if len(key) >= 32:
            if is_production_document_environment():
                try:
                    assert_production_storage_allowed(backend)
                except SecureStorageNotConfigured as exc:
                    payload["reason"] = str(exc)
                    return payload
            payload["state"] = "READY"
            payload["real_document_onboarding_allowed"] = True
            payload["reason"] = (
                "encrypted_private is configured with an application encryption key. "
                "This does not activate Driver #001."
            )
            return payload
        payload["reason"] = (
            f"COMPLIANCE_STORAGE_BLOCKED: {ENCRYPTION_KEY_ENV} must be at least 32 characters."
        )
        return payload
    if backend == STORAGE_BACKEND_S3_PRIVATE:
        status = s3_configuration_status()
        payload["reason"] = status["reason"]
        if status["status"] == "READY":
            payload["state"] = "READY"
            payload["real_document_onboarding_allowed"] = True
        return payload
    payload["reason"] = (
        f"COMPLIANCE_STORAGE_BLOCKED: backend '{backend}' is not production-safe for real "
        "Driver #001 documents. Use encrypted_private or s3_private. "
        "Do not silently fall back to local disk in production."
    )
    return payload


class EncryptedPrivateDocumentStorage(DocumentStorageBackend):
    """Local private files wrapped with authenticated encryption. Not a public URL store."""

    MAGIC = b"AMICORDOC1"
    backend_name = STORAGE_BACKEND_ENCRYPTED_PRIVATE

    def __init__(self, *, base_dir: Path | None = None, encryption_key: str | None = None) -> None:
        raw = (encryption_key if encryption_key is not None else os.getenv(ENCRYPTION_KEY_ENV, "")).strip()
        if len(raw) < 32:
            raise SecureStorageNotConfigured(
                f"{ENCRYPTION_KEY_ENV} must be at least 32 characters for encrypted_private storage."
            )
        self._key = hashlib.sha256(raw.encode("utf-8")).digest()
        self._inner = LocalDocumentStorage(base_dir=base_dir or DEFAULT_LOCAL_ROOT)

    def _wrap(self, data: bytes) -> bytes:
        nonce = os.urandom(16)
        keystream = bytearray()
        counter = 0
        while len(keystream) < len(data):
            keystream.extend(
                hmac.new(self._key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
            )
            counter += 1
        xored = bytes(a ^ b for a, b in zip(data, keystream[: len(data)]))
        tag = hmac.new(self._key, nonce + xored, hashlib.sha256).digest()
        return self.MAGIC + nonce + tag + xored

    def _unwrap(self, blob: bytes) -> bytes:
        if not blob.startswith(self.MAGIC):
            raise ValueError("Invalid encrypted document envelope.")
        nonce = blob[len(self.MAGIC) : len(self.MAGIC) + 16]
        tag = blob[len(self.MAGIC) + 16 : len(self.MAGIC) + 48]
        xored = blob[len(self.MAGIC) + 48 :]
        expected = hmac.new(self._key, nonce + xored, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("Encrypted document authentication failed.")
        keystream = bytearray()
        counter = 0
        while len(keystream) < len(xored):
            keystream.extend(
                hmac.new(self._key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
            )
            counter += 1
        return bytes(a ^ b for a, b in zip(xored, keystream[: len(xored)]))

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
        plaintext = stream.read()
        wrapped = self._wrap(plaintext)
        backend, storage_ref, _ = self._inner.store(
            organization_id=organization_id,
            application_id=application_id,
            category=category,
            filename=filename,
            content_type=content_type,
            stream=BytesIO(wrapped),
        )
        return self.backend_name, storage_ref, len(plaintext)

    def retrieve(self, *, storage_ref: str) -> tuple[bytes, str | None]:
        blob, content_type = self._inner.retrieve(storage_ref=storage_ref)
        return self._unwrap(blob), content_type

    def delete(self, *, storage_ref: str) -> None:
        self._inner.delete(storage_ref=storage_ref)


class S3PrivateDocumentStorage(DocumentStorageBackend):
    """Private S3 objects only. Fails closed without credentials. Never emits public URLs."""

    backend_name = STORAGE_BACKEND_S3_PRIVATE

    def __init__(self) -> None:
        status = s3_configuration_status()
        if status["status"] != "READY":
            raise SecureStorageNotConfigured(
                f"COMPLIANCE_STORAGE_BLOCKED: {status['reason']}"
            )
        import boto3
        from botocore.config import Config

        self._bucket = s3_bucket()
        client_kwargs: dict = {
            "region_name": s3_region(),
            "aws_access_key_id": s3_access_key(),
            "aws_secret_access_key": s3_secret_key(),
            "config": Config(signature_version="s3v4"),
        }
        endpoint_url = s3_endpoint_url()
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        self._client = boto3.client("s3", **client_kwargs)

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
        data = stream.read()
        key = object_key_for_upload(
            organization_id=organization_id,
            application_id=application_id,
            category=category,
            filename=filename,
        )
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
            ServerSideEncryption="AES256",
            Metadata={"amicor-private": "true", "amicor-public": "never"},
        )
        return self.backend_name, key, len(data)

    def retrieve(self, *, storage_ref: str) -> tuple[bytes, str | None]:
        assert_safe_storage_ref(storage_ref)
        response = self._client.get_object(Bucket=self._bucket, Key=storage_ref)
        body = response["Body"].read()
        return body, response.get("ContentType")

    def delete(self, *, storage_ref: str) -> None:
        assert_safe_storage_ref(storage_ref)
        self._client.delete_object(Bucket=self._bucket, Key=storage_ref)
