"""Operations-only production artifact storage. No shared credentials or disk fallback."""

from dataclasses import dataclass
from io import BytesIO
import logging
import os
import re
import threading
from urllib.parse import urlsplit

from app.modules.platform_ops.secure_storage import (
    S3PrivateDocumentStorage,
    SecureStorageNotConfigured,
    s3_bucket,
)
from app.modules.platform_ops.storage import object_key_for_upload

logger = logging.getLogger(__name__)
_R2_SUFFIX = ".r2.cloudflarestorage.com"
_R2_JURISDICTIONS = frozenset({"eu", "fedramp"})
_SAFE_ERROR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,80}")
_SIGNED_HEADER_LIST = re.compile(r"[a-z0-9;-]{1,240}")
_SCOPE_PART = re.compile(r"[A-Za-z0-9_-]{1,40}")
_ABSENT_CODES = frozenset({"NoSuchKey", "404", "NotFound"})
_R2_REJECTED_HEADERS = frozenset(
    {
        "expect",
        "x-amz-sdk-checksum-algorithm",
        "x-amz-checksum-algorithm",
        "x-amz-trailer",
        "x-amz-decoded-content-length",
        "x-amz-server-side-encryption",
        "x-amz-server-side-encryption-aws-kms-key-id",
        "x-amz-server-side-encryption-context",
        "x-amz-server-side-encryption-bucket-key-enabled",
    }
)
_r2_call = threading.local()


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


def _is_r2_endpoint(endpoint: str | None) -> bool:
    if not endpoint:
        return False
    host = (urlsplit(endpoint).hostname or "").lower().rstrip(".")
    return host.endswith(_R2_SUFFIX)


def _normalize_r2_host(hostname: str) -> str:
    host = hostname.lower().rstrip(".")
    labels = host[: -len(_R2_SUFFIX)].split(".")
    if not labels or labels == [""]:
        raise SecureStorageNotConfigured("Operations storage endpoint must be an HTTPS origin")
    if len(labels) >= 2 and labels[-1] in _R2_JURISDICTIONS:
        account_labels = labels[:-1]
        jurisdiction = labels[-1]
        if len(account_labels) > 1:
            account_labels = account_labels[1:]
        return ".".join([*account_labels, jurisdiction]) + _R2_SUFFIX
    if len(labels) > 1:
        labels = labels[1:]
    return ".".join(labels) + _R2_SUFFIX


def _normalize_operations_endpoint(endpoint: str, bucket: str) -> str:
    try:
        parsed = urlsplit(endpoint.strip())
        valid = (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
        if parsed.port == 0:
            valid = False
        path = parsed.path.rstrip("/")
        if path not in ("",) and path != "/" + bucket:
            valid = False
    except ValueError:
        valid = False
    if not valid:
        raise SecureStorageNotConfigured("Operations storage endpoint must be an HTTPS origin")
    host = parsed.hostname or ""
    if _is_r2_endpoint(f"https://{host}"):
        host = _normalize_r2_host(host)
    origin = f"https://{host}"
    if parsed.port and parsed.port != 443:
        origin += f":{parsed.port}"
    return origin


def _operations_s3_config(endpoint: str | None):
    from botocore.config import Config

    options = {
        "signature_version": "s3v4",
        "connect_timeout": 5,
        "read_timeout": 10,
        "retries": {"max_attempts": 2, "mode": "standard"},
        "s3": {"addressing_style": "path"},
    }
    if _is_r2_endpoint(endpoint):
        options["request_checksum_calculation"] = "when_required"
        options["response_checksum_validation"] = "when_required"
        options["s3"] = {"addressing_style": "path", "payload_signing_enabled": True}
    return Config(**options)


def _credential_class(value: str) -> str:
    key = value.strip()
    if not key:
        return "missing"
    if key.startswith("AKIA") and len(key) == 20:
        return "akia"
    if key.startswith("ASIA"):
        return "asia-session"
    if len(key) == 32 and all(character in "0123456789abcdefABCDEF" for character in key):
        return "hex32"
    return "other"


def _secret_class(value: str) -> str:
    secret = value.strip()
    if not secret:
        return "missing"
    if len(secret) == 64 and all(character in "0123456789abcdefABCDEF" for character in secret):
        return "hex64"
    return "other"


def _sanitize_provider_detail(text: str) -> str:
    """Keep a short provider reason and remove URLs, keys, and signatures."""
    cleaned = text or ""
    for secret in getattr(_r2_call, "redactions", ()):
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    cleaned = re.sub(r"https?://\S+", "[url]", cleaned, flags=re.I)
    cleaned = re.sub(
        r"(?i)(credential|authorization|signature|access[_ ]?key|secret(?:_key)?)\s*[=:]\s*\S+",
        r"\1=[redacted]",
        cleaned,
    )
    cleaned = re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[key]", cleaned)
    cleaned = re.sub(r"\b[0-9a-fA-F]{16,}\b", "[token]", cleaned)
    cleaned = re.sub(r"\b[A-Za-z0-9+/]{32,}={0,2}\b", "[token]", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return (cleaned or "none")[:180]


def _confirmed_object_absent(exc: Exception) -> bool:
    """True only for a provider object-not-found response."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error") if isinstance(response.get("Error"), dict) else {}
    code = str(error.get("Code") or "")
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return code in _ABSENT_CODES or status == 404


def _header_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("ascii", "replace")
    return str(value)


def _prepare_r2_put(request, **kwargs):
    """Drop headers Cloudflare R2 rejects, only for an Operations R2 upload."""
    if not getattr(_r2_call, "active", False):
        return
    host = (urlsplit(request.url).hostname or "").lower().rstrip(".")
    if not host.endswith(_R2_SUFFIX):
        return
    body = getattr(request, "body", None)
    raw = getattr(body, "_raw", None)
    if raw is not None and type(body).__name__ == "AwsChunkedWrapper":
        if hasattr(raw, "seek"):
            raw.seek(0)
        data = raw.read() if hasattr(raw, "read") else raw
        if isinstance(data, (bytes, bytearray)):
            request.body = bytes(data)
    headers = request.headers
    for name in list(headers):
        lowered = _header_text(name).lower()
        if lowered in _R2_REJECTED_HEADERS or lowered.startswith("x-amz-checksum-"):
            del headers[name]
    encoding = _header_text(headers.get("Content-Encoding"))
    if "aws-chunked" in encoding.lower():
        kept = [part.strip() for part in encoding.split(",") if part.strip().lower() != "aws-chunked"]
        if kept:
            headers["Content-Encoding"] = ",".join(kept)
        else:
            del headers["Content-Encoding"]
    if _header_text(headers.get("Transfer-Encoding")).lower() == "chunked":
        del headers["Transfer-Encoding"]
    if isinstance(request.body, (bytes, bytearray)) and "Content-Length" not in headers:
        headers["Content-Length"] = str(len(request.body))


def _remember_r2_request(request, **kwargs):
    if not getattr(_r2_call, "active", False):
        return
    host = (urlsplit(request.url).hostname or "").lower().rstrip(".")
    if not host.endswith(_R2_SUFFIX):
        return
    auth = _header_text(request.headers.get("Authorization"))
    scheme = auth.split(" ", 1)[0] if auth else "none"
    if scheme not in {"AWS4-HMAC-SHA256", "none"}:
        scheme = "other"
    signed = "none"
    scope = "none"
    if "SignedHeaders=" in auth:
        candidate = auth.split("SignedHeaders=", 1)[1].split(",", 1)[0]
        if _SIGNED_HEADER_LIST.fullmatch(candidate):
            signed = candidate
    if "Credential=" in auth:
        parts = auth.split("Credential=", 1)[1].split(",", 1)[0].split("/")
        if len(parts) >= 4 and all(_SCOPE_PART.fullmatch(part) for part in parts[-3:]):
            scope = "/".join(parts[-3:])
    digest = _header_text(request.headers.get("X-Amz-Content-SHA256"))
    if re.fullmatch(r"[0-9a-f]{64}", digest):
        sha = "hex-sha256"
    elif "UNSIGNED" in digest or "STREAMING" in digest:
        sha = "unsigned-or-streaming"
    elif digest:
        sha = "other"
    else:
        sha = "missing"
    _r2_call.shape = {
        "auth_scheme": scheme,
        "scope": scope,
        "sha": sha,
        "expect": "yes" if any(_header_text(name).lower() == "expect" for name in request.headers) else "no",
        "signed_headers": signed,
    }


def _install_r2_put_hardening(client) -> None:
    events = getattr(getattr(client, "meta", None), "events", None)
    if events is None:
        return
    events.register_last(
        "before-sign.s3.PutObject",
        _prepare_r2_put,
        unique_id="amicor-operations-r2-put",
    )
    events.register(
        "before-send.s3.PutObject",
        _remember_r2_request,
        unique_id="amicor-operations-r2-shape",
    )


def _log_storage_failure(operation: str, exc: Exception) -> None:
    """Record the failing step and a redacted provider reason. No credentials."""
    code = "none"
    status = "none"
    argument = "none"
    detail = "none"
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error") if isinstance(response.get("Error"), dict) else {}
        raw_code = str(error.get("Code") or "")
        if _SAFE_ERROR_CODE.fullmatch(raw_code):
            code = raw_code
        raw_argument = str(error.get("ArgumentName") or error.get("Argument") or "")
        if _SAFE_ERROR_CODE.fullmatch(raw_argument):
            argument = raw_argument
        raw_status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        if type(raw_status) is int and 100 <= raw_status <= 599:
            status = str(raw_status)
        detail = _sanitize_provider_detail(str(error.get("Message") or ""))
    elif str(exc):
        detail = _sanitize_provider_detail(type(exc).__name__)
    shape = getattr(_r2_call, "shape", {}) or {}
    logger.warning(
        "Operations storage diagnostic operation=%s error_class=%s error_code=%s "
        "http_status=%s argument=%s credential_class=%s secret_class=%s endpoint_class=%s "
        "auth_scheme=%s scope=%s sha=%s expect=%s signed_headers=%s detail=%s",
        operation,
        type(exc).__name__,
        code,
        status,
        argument,
        getattr(_r2_call, "credential_class", "missing"),
        getattr(_r2_call, "secret_class", "missing"),
        getattr(_r2_call, "endpoint_class", "missing"),
        shape.get("auth_scheme", "none"),
        shape.get("scope", "none"),
        shape.get("sha", "none"),
        shape.get("expect", "none"),
        shape.get("signed_headers", "none"),
        detail,
    )


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
            endpoint = _normalize_operations_endpoint(endpoint, bucket)
        signing_region = "auto" if _is_r2_endpoint(endpoint) else region
        return cls(bucket, signing_region, access_key, secret_key, endpoint)


class OperationsPrivateArtifactStorage(S3PrivateDocumentStorage):
    """Use the existing non-public object API with an isolated explicit S3 client."""

    def __init__(self) -> None:
        settings = OperationsStorageSettings.from_environment()
        try:
            import boto3
        except ImportError as exc:
            raise SecureStorageNotConfigured("Operations private storage client is unavailable") from exc

        self._bucket = settings.bucket
        self._omit_sse = _is_r2_endpoint(settings.endpoint)
        _r2_call.redactions = (
            settings.access_key,
            settings.secret_key,
            settings.endpoint or "",
            (urlsplit(settings.endpoint or "").hostname or ""),
            settings.bucket,
        )
        _r2_call.credential_class = _credential_class(settings.access_key)
        _r2_call.secret_class = _secret_class(settings.secret_key)
        _r2_call.endpoint_class = "r2" if self._omit_sse else "custom"
        _r2_call.shape = {}
        self._client = boto3.client(
            "s3",
            region_name=settings.region,
            aws_access_key_id=settings.access_key,
            aws_secret_access_key=settings.secret_key,
            endpoint_url=settings.endpoint,
            config=_operations_s3_config(settings.endpoint),
        )
        if self._omit_sse:
            _install_r2_put_hardening(self._client)

    def store(
        self,
        *,
        organization_id: str,
        application_id: str,
        category: str,
        filename: str,
        content_type: str,
        stream,
    ) -> tuple[str, str, int]:
        """Store one private object. R2 rejects SSE headers and encrypts at rest itself."""
        if not self._omit_sse:
            return super().store(
                organization_id=organization_id,
                application_id=application_id,
                category=category,
                filename=filename,
                content_type=content_type,
                stream=stream,
            )
        data = stream.read()
        key = object_key_for_upload(
            organization_id=organization_id,
            application_id=application_id,
            category=category,
            filename=filename,
        )
        _r2_call.active = True
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type or "application/octet-stream",
                Metadata={"amicor-private": "true", "amicor-public": "never"},
            )
        finally:
            _r2_call.active = False
        return self.backend_name, key, len(data)


SYNTHETIC_PROBE_BODY = b"AMICOR synthetic operations storage probe. No customer data.\n"
_PROBE_ORGANIZATION = "owner-storage-probe"
_PROBE_APPLICATION = "synthetic-storage-probe"


def run_synthetic_storage_probe() -> dict[str, bool | None]:
    """Upload, read back, verify, and delete one synthetic private object.

    The result has no bucket name, object key, file bytes, or credentials.
    Store or retrieve errors still attempt delete before they escape.
    A failed delete is reported and does not include the provider error.
    """
    try:
        storage = OperationsPrivateArtifactStorage()
    except Exception as exc:
        _log_storage_failure("configure", exc)
        raise
    ref: str | None = None
    uploaded = retrieved = verified = deleted = absent = False
    try:
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
        except Exception as exc:
            _log_storage_failure("put_object", exc)
            raise
        try:
            body, content_type = storage.retrieve(storage_ref=ref)
        except Exception as exc:
            _log_storage_failure("get_object", exc)
            raise
        retrieved = True
        verified = body == SYNTHETIC_PROBE_BODY and content_type == "text/plain"
    finally:
        if ref:
            try:
                storage.delete(storage_ref=ref)
                deleted = True
            except Exception as exc:
                _log_storage_failure("delete_object", exc)
                deleted = False
            else:
                try:
                    storage.retrieve(storage_ref=ref)
                except Exception as exc:
                    absent = _confirmed_object_absent(exc)
                    if not absent:
                        _log_storage_failure("confirm_deleted", exc)
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
