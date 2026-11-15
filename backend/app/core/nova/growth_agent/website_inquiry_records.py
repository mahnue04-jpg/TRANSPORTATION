"""Pure website inquiry normalization for Growth Agent; no network or secrets.

This server-side adapter recognizes both known Cloudflare KV key shapes.
It must not classify real submissions as synthetic based on customer-controlled
message text; only trusted fixture invocation can mark a test record synthetic.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any

_LEGACY = re.compile(r"^lead:(?P<date>\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z):[a-fA-F0-9-]{36}$")
_REFERENCE = re.compile(r"^lead:(AMQ-[A-Z0-9]{8})$")


def normalize_website_inquiry(key: str, record: Any, *, trusted_synthetic_fixture: bool = False) -> dict[str, Any] | None:
    if not isinstance(key, str) or not isinstance(record, dict):
        return None
    legacy = _LEGACY.fullmatch(key)
    reference = _REFERENCE.fullmatch(key)
    if not (legacy or reference):
        return None
    if record.get("consent") is not True:
        return None
    for field in ("name", "company", "email", "receivedAt"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            return None
    try:
        datetime.fromisoformat(record["receivedAt"].replace("Z", "+00:00"))
    except ValueError:
        return None
    if reference and record.get("referenceId") not in (None, reference.group(1)):
        return None
    if not isinstance(record.get("product", ""), str) or not isinstance(record.get("message", ""), str):
        return None
    return {
        "source_system": "amicor_cloudflare_kv",
        "source_key": key,
        "reference_id": reference.group(1) if reference else None,
        "received_at": record["receivedAt"],
        "name": record["name"].strip(),
        "company": record["company"].strip(),
        "email": record["email"].strip(),
        "product": record.get("product", ""),
        "message": record.get("message", ""),
        "consent": True,
        "is_synthetic": trusted_synthetic_fixture,
        "status": "needs_owner_review",
    }


def normalize_inquiry_entries(entries: Any, *, trusted_synthetic_fixture: bool = False) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise ValueError("Complete lead entry list required")
    normalized = []
    seen = set()
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            continue
        key = item["key"]
        if key in seen:
            continue
        result = normalize_website_inquiry(key, item.get("value"), trusted_synthetic_fixture=trusted_synthetic_fixture)
        if result is not None:
            seen.add(key)
            normalized.append(result)
    return normalized
