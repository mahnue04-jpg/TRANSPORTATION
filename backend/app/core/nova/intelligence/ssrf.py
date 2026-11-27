"""Pure SSRF checks for synthetic media URLs.

Validation never resolves DNS, opens a connection, or follows a redirect.
Unknown addresses fail closed.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import unquote, urlsplit

_HOST_RE = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)+"
)
_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google",
    "metadata.google.internal",
    "instance-data",
}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".localdomain", ".internal")
_REDIRECT_SEGMENTS = {"redirect", "redir", "go", "out"}


class UnsafeMediaUrl(ValueError):
    """Raised when a URL is not a single plain https address."""


def _reject(message: str = "Source URL is not allowed") -> None:
    raise UnsafeMediaUrl(message)


def _decode(value: str) -> str:
    current = value
    for _ in range(3):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
    return current


def _is_ip_literal(host: str) -> bool:
    token = host.strip("[]")
    if ":" in token:
        return True
    try:
        ipaddress.ip_address(token)
        return True
    except ValueError:
        pass
    if re.fullmatch(r"\d+", token) or re.fullmatch(r"0x[0-9a-f]+", token):
        return True
    parts = token.split(".")
    if 2 <= len(parts) <= 4 and all(re.fullmatch(r"(?:0x[0-9a-f]+|\d+)", part) for part in parts):
        return True
    return False


def _classify_blocked_ip(host: str) -> bool:
    """Return True when the host is an IP literal.

    Every IP literal is rejected. Private, loopback, link-local, and the
    metadata address are covered because they are IP literals.
    """
    if not _is_ip_literal(host):
        return False
    token = host.strip("[]")
    try:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = ipaddress.ip_address(token)
    except ValueError:
        ip = None
        if re.fullmatch(r"\d+", token):
            try:
                ip = ipaddress.IPv4Address(int(token))
            except (ValueError, OverflowError):
                ip = None
        elif re.fullmatch(r"0x[0-9a-f]+", token):
            try:
                ip = ipaddress.IPv4Address(int(token, 16))
            except (ValueError, OverflowError):
                ip = None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip is not None:
        # Touch the categories the slice must reject so the check is explicit.
        _ = (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
            or not ip.is_global
            or str(ip) == "169.254.169.254"
        )
    return True


def validate_https_url(value: object) -> str:
    """Return a canonical https URL or raise ``UnsafeMediaUrl``.

    The result has no userinfo, port, query, or fragment. Callers still have
    to match an in-process allowlist before a fixture id is chosen.
    """
    if not isinstance(value, str) or not value or len(value) > 500:
        _reject()
    if any(ord(ch) < 33 or ord(ch) == 127 for ch in value):
        _reject()
    if "\\" in value or "@" in value or ".." in value:
        _reject()
    decoded = _decode(value.strip())
    if any(ord(ch) < 33 or ord(ch) == 127 for ch in decoded):
        _reject()
    if "\\" in decoded or "@" in decoded or ".." in decoded or "\x00" in decoded:
        _reject()
    if decoded.lower().count("://") != 1:
        _reject()
    parts = urlsplit(decoded)
    if parts.scheme.lower() != "https":
        _reject()
    if parts.username or parts.password or "@" in parts.netloc or parts.port is not None:
        _reject()
    if parts.query or parts.fragment:
        _reject()
    host = parts.hostname
    if not host or not host.isascii():
        _reject()
    host = host.lower()
    if host.endswith(".") or host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        _reject()
    if _classify_blocked_ip(host):
        _reject()
    if not _HOST_RE.fullmatch(host):
        _reject()
    path = parts.path or ""
    if not path.startswith("/") or "//" in path:
        _reject()
    segments = [segment for segment in path.split("/") if segment]
    if any(segment.lower() in _REDIRECT_SEGMENTS for segment in segments):
        _reject()
    return f"https://{host}{path}"
