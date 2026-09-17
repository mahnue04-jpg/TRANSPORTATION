"""Source URLs are stored as text only. They are never fetched or opened by this engine."""
from __future__ import annotations

import ipaddress
from urllib.parse import unquote, urlparse

BLOCKED_SCHEMES = ("javascript:", "data:", "vbscript:", "file:")
ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}


class UnsafeSourceUrl(ValueError):
    pass


def _decode_url(value: str) -> str:
    current = value.strip()
    for _ in range(3):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
    return current


def _host_is_blocked(host: str) -> bool:
    token = (host or "").strip().strip("[]").lower().rstrip(".")
    if not token:
        return True
    if token in BLOCKED_HOSTS or token.endswith(".localhost") or token.endswith(".local"):
        return True
    if token.startswith("0x") or "0x" in token:
        return True
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    try:
        ip = ipaddress.ip_address(token)
    except ValueError:
        if token.isdigit():
            try:
                ip = ipaddress.IPv4Address(int(token))
            except (ValueError, OverflowError):
                return True
        else:
            return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_source_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _decode_url(str(value))
    if not cleaned:
        return None
    if "\\" in cleaned or "\x00" in cleaned:
        raise UnsafeSourceUrl("Source URL is malformed")
    lowered = cleaned.lower()
    if lowered.startswith(BLOCKED_SCHEMES) or any(lowered.startswith(item) for item in BLOCKED_SCHEMES):
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
    if _host_is_blocked(host):
        raise UnsafeSourceUrl("Local, private, or link-local source URLs are not allowed")
    return cleaned[:800]
