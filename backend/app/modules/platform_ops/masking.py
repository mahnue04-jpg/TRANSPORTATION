"""Field masking for sensitive onboarding identifiers."""
from __future__ import annotations

import re


def mask_license_number(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if len(raw) <= 4:
        return "*" * len(raw)
    return f"{'*' * (len(raw) - 4)}{raw[-4:]}"


def mask_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 4:
        return "***"
    return f"***-***-{digits[-4:]}"


def mask_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return value
    local, domain = value.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[0] + ("*" * (len(local) - 2)) + local[-1]
    return f"{masked_local}@{domain}"


def safe_log_identifier(label: str, value: str | None) -> str:
    if label.lower() in {"license", "drivers_license", "drivers_license_number"}:
        return mask_license_number(value) or ""
    if label.lower() in {"phone", "mobile_phone"}:
        return mask_phone(value) or ""
    if label.lower() == "email":
        return mask_email(value) or ""
    return "[redacted]"
