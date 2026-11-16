"""Merge internal and external busy windows for slot filtering (non-atomic reads)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo("America/Chicago")


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    from datetime import timezone

    return dt.astimezone(timezone.utc)


def merge_busy_intervals(
    internal_existing: list[tuple[datetime, datetime]],
    external_busy: list[tuple[datetime, datetime]],
    buffer_minutes: int = 0,
) -> list[tuple[datetime, datetime]]:
    """Union busy intervals with optional symmetric buffer, sorted and merged."""
    buf = max(0, int(buffer_minutes))
    expanded: list[tuple[datetime, datetime]] = []
    for start, end in list(internal_existing) + list(external_busy):
        s, e = _to_utc(start), _to_utc(end)
        if e <= s:
            continue
        if buf:
            s = s - timedelta(minutes=buf)
            e = e + timedelta(minutes=buf)
        expanded.append((s, e))
    if not expanded:
        return []
    expanded.sort(key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = [expanded[0]]
    for start, end in expanded[1:]:
        last_s, last_e = merged[-1]
        if start <= last_e:
            merged[-1] = (last_s, max(last_e, end))
        else:
            merged.append((start, end))
    return merged


def _slot_conflicts(
    slot_start: datetime,
    slot_end: datetime,
    busy: tuple[datetime, datetime],
    buffer_minutes: int,
) -> bool:
    b_start, b_end = busy
    buf = timedelta(minutes=max(0, int(buffer_minutes)))
    # Treat availability read as advisory: overlap if buffered busy intersects slot.
    return not (slot_end <= b_start - buf or slot_start >= b_end + buf)


def filter_slots_against_busy(
    slots: list[tuple[datetime, datetime]],
    busy: list[tuple[datetime, datetime]],
    buffer_minutes: int = 0,
) -> list[tuple[datetime, datetime]]:
    """Remove slots overlapping merged busy windows (not a reservation lock)."""
    if not busy:
        return list(slots)
    normalized_busy = merge_busy_intervals([], busy, buffer_minutes=0)
    kept: list[tuple[datetime, datetime]] = []
    for slot_start, slot_end in slots:
        s, e = _to_utc(slot_start), _to_utc(slot_end)
        if any(_slot_conflicts(s, e, b, buffer_minutes) for b in normalized_busy):
            continue
        kept.append((slot_start, slot_end))
    return kept


def local_slot_boundaries(
    local_date: datetime,
    start_minute: int,
    end_minute: int,
    tz: ZoneInfo | None = None,
) -> tuple[datetime, datetime]:
    """Build aware slot edges in America/Chicago (handles DST transitions)."""
    zone = tz or CHICAGO
    if local_date.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    local_day = local_date.astimezone(zone).date()
    start_local = datetime(
        local_day.year,
        local_day.month,
        local_day.day,
        start_minute // 60,
        start_minute % 60,
        tzinfo=zone,
    )
    end_local = datetime(
        local_day.year,
        local_day.month,
        local_day.day,
        end_minute // 60,
        end_minute % 60,
        tzinfo=zone,
    )
    return start_local, end_local