"""Operations-only production artifact storage. No shared credentials or disk fallback."""

from dataclasses import dataclass
from io import BytesIO
import os
import re
from urllib.parse import urlsplit

from app.modules.platform_ops.secure_storage import (
    S3PrivateDocumentStorage,
    SecureStorageNotConfigured,
    s3_bucket,
)


def is_production_artifact_runtime() -> bool:
    """Mixed environment markers must not fall back to rehearsal storage."""
    app_env, amicor_env = (
        os.getenv(name, "").strip().lower() for name in ("APP_ENV", "AMICOR_ENVIRONMENT")
    )
    if {app_env, amicor_env}.intersection({"prod", "production"}):
        if app_env != "production" or amicor_env != "production":
            raise SecureStorageNotConfigured("Operations production environment markers disagree")
        return True
    return False


@dataclass(frozen=True, repr=False)
class OperationsStorageSettings:
    bucket: str
    region: str
    access_key: str
    secret_key: str
    endpoint: str | None

    @classmethod
    def from_environment(cls) -> "OperationsStorageSettings":
        if not is_production_artifact_runtime():
            raise SecureStorageNotConfigured("Operations production storage is not enabled here")
        bucket, region, access_key, secret_key, endpoint = (
            os.getenv(f"NOVA_OPERATIONS_PRIVATE_S3_{suffix}", "").strip()
            for suffix in ("BUCKET", "REGION", "ACCESS_KEY", "SECRET_KEY", "ENDPOINT")
        )
        if not all((bucket, region, access_key, secret_key)):
            raise SecureStorageNotConfigured("Dedicated Operations private storage is not configured")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise SecureStorageNotConfigured("Operations storage bucket name is invalid")
        if bucket.casefold() == s3_bucket().casefold():
            raise SecureStorageNotConfigured("Operations production storage must use a separate bucket")
        if endpoint:
            try:
                parsed = urlsplit(endpoint)
                valid = (parsed.scheme == "https" and parsed.hostname and parsed.username is None
                         and parsed.password is None and parsed.path in ("", "/")
                         and not parsed.query and not parsed.fragment)
                # Accessing port also validates the optional explicit port.
                if parsed.port is not None and parsed.port == 0:
                    valid = False
            except ValueError:
                valid = False
            if not valid:
                raise SecureStorageNotConfigured("Operations storage endpoint must be an HTTPS origin")
        return cls(bucket, region, access_key, secret_key, endpoint.rstrip("/") or None)


class OperationsPrivateArtifactStorage(S3PrivateDocumentStorage):
    """Use the existing non-public object API with an isolated explicit S3 client."""

    def __init__(self) -> None:
        settings = OperationsStorageSettings.from_environment()
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise SecureStorageNotConfigured("Operations private storage client is unavailable") from exc

        self._bucket = settings.bucket
        self._client = boto3.client(
            "s3",
            region_name=settings.region,
            aws_access_key_id=settings.access_key,
            aws_secret_access_key=settings.secret_key,
            endpoint_url=settings.endpoint,
            config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=10),
        )


SYNTHETIC_PROBE_BODY = b"AMICOR synthetic operations storage probe. No customer data.\n"
_PROBE_ORGANIZATION = "owner-storage-probe"
_PROBE_APPLICATION = "synthetic-storage-probe"


def run_synthetic_storage_probe() -> dict[str, bool | None]:
    """Upload, read back, verify, and delete one synthetic private object.

    The result has no bucket name, object key, file bytes, or credentials.
    Store or retrieve errors still attempt delete before they escape.
    A failed delete is reported and does not include the provider error.
    """
    storage = OperationsPrivateArtifactStorage()
    ref: str | None = None
    uploaded = retrieved = verified = deleted = absent = False
    try:
        _, ref, size = storage.store(
            organization_id=_PROBE_ORGANIZATION,
            application_id=_PROBE_APPLICATION,
            category="owner-storage-probe",
            filename="probe.txt",
            content_type="text/plain",
            stream=BytesIO(SYNTHETIC_PROBE_BODY),
        )
        uploaded = bool(ref) and size == len(SYNTHETIC_PROBE_BODY)
        body, content_type = storage.retrieve(storage_ref=ref)
        retrieved = True
        verified = body == SYNTHETIC_PROBE_BODY and content_type == "text/plain"
    finally:
        if ref:
            try:
                storage.delete(storage_ref=ref)
                deleted = True
            except Exception:
                deleted = False
            else:
                try:
                    storage.retrieve(storage_ref=ref)
                except Exception:
                    absent = True
    return {
        "ok": bool(uploaded and retrieved and verified and deleted and absent),
        "uploaded": uploaded,
        "retrieved": retrieved,
        "verified": verified,
        "deleted": deleted,
        "absent_after_delete": absent,
        "synthetic": True,
        "public_url": None,
    }
