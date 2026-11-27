"""PII redaction for logs, errors, and observability. Never log raw contact PII."""

from __future__ import annotations

import re
from typing import Any

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}")
_SECRETISH = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|authorization)\s*[:=]\s*\S+"
)


def redact_text(value: str | None) -> str:
    if not value:
        return ""
    text = str(value)
    text = _EMAIL.sub("[REDACTED_EMAIL]", text)
    text = _PHONE.sub("[REDACTED_PHONE]", text)
    text = _SECRETISH.sub(r"\1=[REDACTED]", text)
    return text


def redact_mapping(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    out: dict[str, Any] = {}
    sensitive = {
        "email",
        "phone",
        "phone_number",
        "full_name",
        "name",
        "contact_email",
        "contact_phone",
        "secret",
        "token",
        "api_key",
        "password",
        "access_token",
        "refresh_token",
    }
    for key, value in data.items():
        lowered = str(key).lower()
        if lowered in sensitive or "secret" in lowered or "token" in lowered:
            out[key] = "[REDACTED]"
        elif isinstance(value, dict):
            out[key] = redact_mapping(value)
        elif isinstance(value, str):
            out[key] = redact_text(value)
        else:
            out[key] = value
    return out


def safe_log_extra(**kwargs: Any) -> dict[str, Any]:
    return redact_mapping(dict(kwargs))
