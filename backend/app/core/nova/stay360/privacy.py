"""Privacy projections for Stay360 staff and guest operational views."""

from __future__ import annotations

import json
from typing import Any

from .constants import FORBIDDEN_PUBLIC_KEYS
from .errors import Stay360Error
from .fixtures import sensitive_corpus

PUBLIC_RESERVATION_KEYS = (
    "reservation_reference",
    "guest_label",
    "room_number",
    "arrival_date",
    "departure_date",
    "arrival_mode",
    "arrival_status",
    "arrival_detail",
    "eta_local",
    "housekeeping_status",
    "room_readiness",
    "check_in_eligibility",
    "check_in_blockers",
    "check_in_status",
)

PUBLIC_ROOM_KEYS = (
    "room_number",
    "housekeeping_status",
    "room_readiness",
    "reservation_reference",
    "guest_label",
)


def project(view: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: view[key] for key in keys}


def forbidden_keys(payload: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            here = f"{path}.{key}" if path else str(key)
            if key in FORBIDDEN_PUBLIC_KEYS:
                found.append(here)
            found.extend(forbidden_keys(value, here))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(forbidden_keys(value, f"{path}[{index}]"))
    return found


def leaked_secrets(payload: Any, extra: tuple[str, ...] = ()) -> list[str]:
    blob = json.dumps(payload, ensure_ascii=False, default=str)
    leaked = [secret for secret in sensitive_corpus() if secret and secret in blob]
    leaked.extend(secret for secret in extra if secret and secret in blob)
    return leaked


def assert_safe(payload: Any, extra: tuple[str, ...] = ()) -> None:
    """Block a response that carries a raw sensitive field or a known fixture secret."""
    keys = forbidden_keys(payload)
    secrets = leaked_secrets(payload, extra)
    if keys or secrets:
        raise Stay360Error(
            500,
            "payload_guard_failed",
            "Response blocked by the Stay360 privacy guard.",
        )
