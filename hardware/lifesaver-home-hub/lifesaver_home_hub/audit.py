"""Metadata-only local audit. Tokens, PHI, media, and secrets are stripped."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FORBIDDEN = frozenset({
    "password",
    "secret",
    "token",
    "device_token",
    "pairing_token",
    "jwt",
    "authorization",
    "journal",
    "medication",
    "reading",
    "video",
    "audio",
    "frame",
    "body",
    "email",
    "phone",
    "credential",
})


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_secret(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if len(raw) <= 6:
        return "***"
    return raw[:3] + "…" + raw[-2:]


def sanitize(metadata: dict[str, Any] | None) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        lowered = str(key).lower()
        if lowered in FORBIDDEN or any(part in lowered for part in ("token", "secret", "password", "journal")):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            text = str(value).lower() if value is not None else ""
            if "sk_" + "live_" in text or "bearer " in text:
                continue
            clean[key] = value
    return clean


class AuditLog:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def write(self, action: str, **metadata: Any) -> dict[str, Any]:
        row = {
            "action": action,
            "timestamp": now_iso(),
            "metadata": sanitize(metadata),
        }
        self.rows.append(row)
        return row

    def recent(self, limit: int = 40) -> list[dict[str, Any]]:
        return list(reversed(self.rows[-limit:]))
