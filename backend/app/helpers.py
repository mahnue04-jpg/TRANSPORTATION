"""Shared utility helpers across the Amicor platform.

Consolidates common functions used across ecosystem, models, and other modules
to reduce duplication and improve maintainability.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException


def now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def uuid4() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


def ensure_user_id(user_id: str) -> str:
    """Validate and normalize user_id. Raises HTTPException if invalid."""
    uid = (user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=422, detail="user_id is required")
    return uid


def json_loads_or(value: str | None, fallback: Any) -> Any:
    """Safely parse JSON string with fallback. Returns fallback on error or if value is None."""
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def json_dumps(value: Any) -> str:
    """Safely serialize value to JSON string with ASCII encoding."""
    return json.dumps(value, ensure_ascii=True)
