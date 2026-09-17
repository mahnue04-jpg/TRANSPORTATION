"""Source URLs are stored as text only. They are never fetched or opened by this engine."""
from __future__ import annotations

from urllib.parse import urlparse

BLOCKED_SCHEMES = ("javascript:", "data:", "vbscript:", "file:")
ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}


class UnsafeSourceUrl(ValueError):
    pass


def validate_source_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered.startswith(BLOCKED_SCHEMES):
        raise UnsafeSourceUrl("Source URL scheme is not allowed")
    if "://" not in cleaned:
        raise UnsafeSourceUrl("Source URL is malformed")
    parsed = urlparse(cleaned)
    if parsed.username or parsed.password:
        raise UnsafeSourceUrl("Source URL must not contain credentials")
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeSourceUrl("Source URL scheme is not allowed")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeSourceUrl("Source URL is malformed")
    if host in BLOCKED_HOSTS or host.endswith(".localhost"):
        raise UnsafeSourceUrl("Local or loopback source URLs are not allowed")
    return cleaned[:800]
