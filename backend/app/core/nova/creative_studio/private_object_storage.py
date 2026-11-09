"""Private S3-compatible storage for owner-imported Creative Studio MP4 files.

Opt-in only. No public object URLs, no query-string bearer credentials.
The calling service must validate project/asset ownership before any read.
"""
from __future__ import annotations

import hashlib
import os
import re

_REMOTE_PREFIX = "private-studio-s3://"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_FILENAME = re.compile(r"^imported_video_[A-Za-z0-9_-]+\.mp4$")


class PrivateStorageError(RuntimeError):
    pass


def enabled() -> bool:
    return os.getenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "").lower() in {"1", "true", "yes"}


def _client():
    import boto3
    from botocore.config import Config
    endpoint = os.getenv("NOVA_STUDIO_S3_ENDPOINT", "").strip()
    access = os.getenv("NOVA_STUDIO_S3_ACCESS_KEY_ID", "").strip()
    secret = os.getenv("NOVA_STUDIO_S3_SECRET_ACCESS_KEY", "").strip()
    if not endpoint.startswith("https://") or not access or not secret:
        raise PrivateStorageError("Private object storage is not configured")
    return boto3.client("s3", endpoint_url=endpoint,
                        aws_access_key_id=access, aws_secret_access_key=secret,
                        region_name=os.getenv("NOVA_STUDIO_S3_REGION", "us-east-1"),
                        config=Config(s3={"addressing_style": "path"},
                                      retries={"max_attempts": 2, "mode": "standard"}))


def _bucket() -> str:
    name = os.getenv("NOVA_STUDIO_S3_BUCKET", "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,62}", name):
        raise PrivateStorageError("Private object bucket is not configured")
    return name


def make_key(owner_id: str, project_id: str, filename: str) -> str:
    if not _IDENTIFIER.fullmatch(owner_id) or not _IDENTIFIER.fullmatch(project_id):
        raise PrivateStorageError("Invalid private object owner/project")
    if not _FILENAME.fullmatch(filename):
        raise PrivateStorageError("Invalid private object filename")
    return f"{owner_id}/{project_id}/{filename}"


def parse_owned_ref(ref: str, owner_id: str, project_id: str) -> str | None:
    if not ref.startswith(_REMOTE_PREFIX):
        return None
    key = ref[len(_REMOTE_PREFIX):]
    parts = key.split("/")
    if len(parts) != 3 or make_key(owner_id, project_id, parts[-1]) != key:
        raise PrivateStorageError("Private object access denied")
    return key


def put_original(owner_id: str, project_id: str, filename: str, data: bytes, sha256: str) -> str:
    if not enabled():
        raise PrivateStorageError("Private object storage is disabled")
    if hashlib.sha256(data).hexdigest() != sha256:
        raise PrivateStorageError("Private upload checksum mismatch")
    key = make_key(owner_id, project_id, filename)
    client = _client()
    bucket = _bucket()
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType="video/mp4",
                      Metadata={"sha256": sha256})
    check = client.head_object(Bucket=bucket, Key=key)
    if int(check.get("ContentLength", -1)) != len(data) or check.get("Metadata", {}).get("sha256") != sha256:
        raise PrivateStorageError("Private object verification failed")
    return _REMOTE_PREFIX + key


def object_exists(ref: str, owner_id: str, project_id: str, sha256: str) -> bool:
    """Check owner-scoped object HEAD metadata and reject empty objects.

    This is a cheap readiness check, not a full remote byte-by-byte digest.
    Full MP4 integrity is verified when the source is downloaded for assembly.
    """
    key = parse_owned_ref(ref, owner_id, project_id)
    if key is None:
        return False
    info = _client().head_object(Bucket=_bucket(), Key=key)
    try:
        length = int(info.get("ContentLength", 0))
    except (TypeError, ValueError):
        return False
    return (
        length > 0
        and isinstance(sha256, str) and len(sha256) == 64
        and info.get("Metadata", {}).get("sha256") == sha256
    )


def open_original(ref: str, owner_id: str, project_id: str):
    key = parse_owned_ref(ref, owner_id, project_id)
    if key is None:
        raise PrivateStorageError("Not a private remote object")
    obj = _client().get_object(Bucket=_bucket(), Key=key)
    return obj["Body"]


def delete_original(ref: str, owner_id: str, project_id: str) -> None:
    key = parse_owned_ref(ref, owner_id, project_id)
    if key is not None:
        _client().delete_object(Bucket=_bucket(), Key=key)


def put_original_file(owner_id: str, project_id: str, filename: str, path, sha256: str,
                      *, max_bytes: int = 512 * 1024 * 1024) -> str:
    """Stream a validated long-form MP4 from disk into private durable storage.

    Never loads the finished master into application memory. Restricted to
    the existing owner/project key format. Extended masters require an explicit opt-in.
    """
    from pathlib import Path

    if not enabled():
        raise PrivateStorageError("Private object storage is disabled")
    source = Path(path)
    if not source.is_file():
        raise PrivateStorageError("Finished master is missing")
    length = source.stat().st_size
    hard_cap = 2 * 1024 * 1024 * 1024
    extended = os.getenv("NOVA_STUDIO_EXTENDED_MASTER_EXPORTS", "").lower() in {"1", "true", "yes"}
    allowed = hard_cap if extended else 512 * 1024 * 1024
    if not 0 < max_bytes <= allowed or not 0 < length <= max_bytes:
        raise PrivateStorageError("Finished master exceeds configured secure storage limit")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != sha256:
        raise PrivateStorageError("Finished master checksum mismatch")
    key = make_key(owner_id, project_id, filename)
    client = _client()
    bucket = _bucket()
    with source.open("rb") as handle:
        client.upload_fileobj(
            handle, bucket, key,
            ExtraArgs={"ContentType": "video/mp4", "Metadata": {"sha256": sha256}},
        )
    try:
        remote = client.head_object(Bucket=bucket, Key=key)
        if (int(remote.get("ContentLength", -1)) != length or
                remote.get("Metadata", {}).get("sha256") != sha256):
            raise PrivateStorageError("Finished master remote verification failed")
    except Exception:
        client.delete_object(Bucket=bucket, Key=key)
        raise
    return _REMOTE_PREFIX + key
