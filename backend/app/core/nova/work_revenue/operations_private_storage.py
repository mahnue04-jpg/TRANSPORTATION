"""Operations-only production artifact storage. No shared credentials or disk fallback."""

from dataclasses import dataclass
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
