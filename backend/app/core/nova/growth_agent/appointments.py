"""First-party appointment availability and double-book prevention."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.core.nova.growth_agent.errors import DoubleBookError, GrowthAgentError
from app.core.nova.growth_agent.quiet_hours import parse_tz


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def slots_for_day(
    *,
    day_local: datetime,
    rules: list[dict[str, Any]],
    duration_minutes: int,
    buffer_minutes: int,
    existing: list[dict[str, Any]],
    tz_name: str,
) -> list[dict[str, str]]:
    tz = parse_tz(tz_name)
    weekday = day_local.weekday()  # Mon=0
    date_s = day_local.strftime("%Y-%m-%d")
    day_rules = [r for r in rules if int(r.get("day_of_week", -1)) == weekday]
    exceptions = [r for r in rules if r.get("exception_date") == date_s]
    if any(r.get("is_closed") for r in exceptions):
        return []
    active_rules = exceptions or day_rules
    slots: list[dict[str, str]] = []
    step = max(5, int(duration_minutes))
    occupied = []
    for appt in existing:
        if str(appt.get("status")) == "cancelled":
            continue
        occupied.append(
            (
                _as_utc(appt["starts_at_utc"]),
                _as_utc(appt["ends_at_utc"]) + timedelta(minutes=int(buffer_minutes)),
            )
        )
    for rule in active_rules:
        if rule.get("is_closed"):
            continue
        start_m = int(rule["start_minute"])
        end_m = int(rule["end_minute"])
        cursor = start_m
        while cursor + duration_minutes <= end_m:
            local_start = day_local.replace(
                hour=cursor // 60,
                minute=cursor % 60,
                second=0,
                microsecond=0,
                tzinfo=tz,
            )
            local_end = local_start + timedelta(minutes=duration_minutes)
            start_utc = local_start.astimezone(timezone.utc)
            end_utc = local_end.astimezone(timezone.utc)
            conflict = any(not (end_utc <= a or start_utc >= b) for a, b in occupied)
            if not conflict:
                slots.append(
                    {
                        "starts_at_utc": start_utc.isoformat().replace("+00:00", "Z"),
                        "ends_at_utc": end_utc.isoformat().replace("+00:00", "Z"),
                        "local_start": local_start.isoformat(),
                    }
                )
            cursor += step
    return slots


def assert_no_overlap(
    *,
    starts_at_utc: datetime,
    ends_at_utc: datetime,
    existing: list[dict[str, Any]],
    buffer_minutes: int = 0,
) -> None:
    start = _as_utc(starts_at_utc)
    end = _as_utc(ends_at_utc) + timedelta(minutes=int(buffer_minutes))
    for appt in existing:
        if str(appt.get("status")) == "cancelled":
            continue
        a = _as_utc(appt["starts_at_utc"])
        b = _as_utc(appt["ends_at_utc"])
        if not (end <= a or start >= b):
            raise DoubleBookError("Requested slot overlaps an existing appointment")


def parse_iso_utc(value: str) -> datetime:
    raw = (value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise GrowthAgentError("INVALID_DATETIME", "Invalid ISO datetime") from exc
    return _as_utc(dt)
