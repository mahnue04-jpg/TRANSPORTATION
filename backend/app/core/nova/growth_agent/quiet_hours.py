"""Quiet hours / timezone scheduling helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


def parse_tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "America/Chicago")
    except Exception:
        return ZoneInfo("America/Chicago")


def in_quiet_hours(
    when: datetime,
    quiet_hours: dict[str, Any] | None,
    *,
    tz_name: str = "America/Chicago",
) -> bool:
    """quiet_hours example: {"start": "21:00", "end": "08:00", "enabled": true}"""
    cfg = quiet_hours or {}
    if not cfg.get("enabled", True):
        return False
    tz = parse_tz(tz_name)
    local = when.astimezone(tz) if when.tzinfo else when.replace(tzinfo=timezone.utc).astimezone(tz)
    start = str(cfg.get("start") or "21:00")
    end = str(cfg.get("end") or "08:00")
    sh, sm = [int(x) for x in start.split(":")[:2]]
    eh, em = [int(x) for x in end.split(":")[:2]]
    minutes = local.hour * 60 + local.minute
    start_m = sh * 60 + sm
    end_m = eh * 60 + em
    if start_m == end_m:
        return False
    if start_m < end_m:
        return start_m <= minutes < end_m
    # wraps midnight
    return minutes >= start_m or minutes < end_m


def next_send_after_quiet_hours(
    when: datetime,
    quiet_hours: dict[str, Any] | None,
    *,
    tz_name: str = "America/Chicago",
) -> datetime:
    if not in_quiet_hours(when, quiet_hours, tz_name=tz_name):
        return when
    cfg = quiet_hours or {}
    tz = parse_tz(tz_name)
    local = when.astimezone(tz) if when.tzinfo else when.replace(tzinfo=timezone.utc).astimezone(tz)
    end = str(cfg.get("end") or "08:00")
    eh, em = [int(x) for x in end.split(":")[:2]]
    candidate = local.replace(hour=eh, minute=em, second=0, microsecond=0)
    if candidate <= local:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc)
