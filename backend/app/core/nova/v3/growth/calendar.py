"""Synthetic calendar adapter. No live calendar writes."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags


def require_timezone(name: str | None) -> str:
    token = str(name or "").strip()
    if not token:
        raise V3Error("TIMEZONE_REQUIRED", "explicit IANA timezone is required", http_status=400)
    try:
        ZoneInfo(token)
    except ZoneInfoNotFoundError as exc:
        raise V3Error("TIMEZONE_INVALID", "timezone must be an explicit IANA name", http_status=400) from exc
    return token


def availability_placeholder(timezone_name: str, now: datetime) -> list[str]:
    tz = require_timezone(timezone_name)
    local = now.astimezone(ZoneInfo(tz))
    slots = []
    for days in (1, 2, 3):
        slot = (local + timedelta(days=days)).replace(hour=15, minute=0, second=0, microsecond=0)
        slots.append(slot.isoformat())
    return slots


def assert_synthetic() -> None:
    if live_flags().get("REAL_CALENDAR_WRITE"):
        raise V3Error("LIVE_DISABLED", "real calendar write is off")
