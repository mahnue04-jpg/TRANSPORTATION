"""Local-LAN address and timeout guards. No public-internet device calls."""
from __future__ import annotations

import ipaddress
import os
from typing import Any

from fastapi import HTTPException

DEFAULT_TIMEOUT_MS = 1500
DEFAULT_RETRY_CEILING = 2
FORBIDDEN_COMMAND_LOG_KEYS = frozenset({
    "password",
    "token",
    "secret",
    "email",
    "phone",
    "body",
    "journal",
    "value",
    "video",
    "audio",
    "frame",
})


def configured_allowlist() -> list[str]:
    raw = os.getenv("LIFESAVER_LOCAL_DEVICE_ALLOWLIST", "127.0.0.1,localhost,::1")
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_host(value: str | None) -> str:
    host = (value or "").strip().split("%")[0]
    if host.startswith("[") and "]" in host:
        host = host[1:host.index("]")]
    if ":" in host and host.count(":") == 1 and not host.startswith(":"):
        host = host.split(":", 1)[0]
    return host.lower()


def is_loopback_or_private(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(addr.is_loopback or addr.is_private or addr.is_link_local)


def reject_public_device_host(host: str | None) -> str:
    cleaned = parse_host(host)
    if not cleaned:
        raise HTTPException(status_code=422, detail="A local test address is required.")
    allow = {item.lower() for item in configured_allowlist()}
    if cleaned in allow and is_loopback_or_private(cleaned):
        return cleaned
    if cleaned in allow and not is_loopback_or_private(cleaned):
        raise HTTPException(status_code=403, detail="Public internet device addresses are rejected by default.")
    if not is_loopback_or_private(cleaned):
        raise HTTPException(status_code=403, detail="Only loopback or private LAN addresses are allowed.")
    if cleaned not in allow:
        raise HTTPException(status_code=403, detail="Host is not on the local device allowlist.")
    return cleaned


def timeout_ms() -> int:
    try:
        return max(200, min(5000, int(os.getenv("LIFESAVER_DEVICE_TIMEOUT_MS", str(DEFAULT_TIMEOUT_MS)))))
    except ValueError:
        return DEFAULT_TIMEOUT_MS


def retry_ceiling() -> int:
    try:
        return max(0, min(3, int(os.getenv("LIFESAVER_DEVICE_RETRY_CEILING", str(DEFAULT_RETRY_CEILING)))))
    except ValueError:
        return DEFAULT_RETRY_CEILING


def sanitize_command_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if key in FORBIDDEN_COMMAND_LOG_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
    return clean
