"""Offline Google Calendar request planning; no OAuth, transport or activation.

Only trusted backend code may construct CalendarBinding after verifying the
signed-in owner and resolving that owner's stored calendar connection.
This module is deliberately NOT imported by GrowthAgentService.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import quote


class CalendarRequestError(ValueError):
    """Safe validation code; never includes calendar/customer input."""


def _required(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CalendarRequestError(code)
    if len(value) > 1024 or any(ord(c) < 32 for c in value):
        raise CalendarRequestError(code)
    return value


@dataclass(frozen=True)
class CalendarBinding:
    organization_id: str
    calendar_id: str

    def __post_init__(self) -> None:
        _required(self.organization_id, "INVALID_BINDING")
        _required(self.calendar_id, "INVALID_BINDING")
        if self.organization_id.lower() in {"*", "global", "all"}:
            raise CalendarRequestError("INVALID_BINDING")


@dataclass(frozen=True)
class CalendarRequest:
    method: str
    path: str
    body_json: str | None

    # Explicitly contains neither credentials nor attendee notifications.
    send_updates: str = "none"


def event_id_for(organization_id: str, appointment_id: str) -> str:
    """Stable Google-compatible ID; changing time does not create a new event."""
    _required(organization_id, "INVALID_ORGANIZATION")
    _required(appointment_id, "INVALID_APPOINTMENT")
    # JSON framing prevents collisions caused by delimiter-containing IDs.
    framed = json.dumps(["nova-calendar-v1", organization_id, appointment_id])
    return hashlib.sha256(framed.encode("utf-8")).hexdigest()


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CalendarRequestError("TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def prepare_calendar_request(
    *,
    binding: CalendarBinding,
    organization_id: str,
    appointment_id: str,
    action: str,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> CalendarRequest:
    """Prepare create/reschedule/cancel against one trusted tenant/calendar.

    Output is a plan, never evidence of a successful remote booking. A future
    dispatcher must enforce auth, availability, durable sync state and retries.
    """
    if organization_id != binding.organization_id:
        raise CalendarRequestError("TENANT_MISMATCH")
    if action not in {"create", "reschedule", "cancel"}:
        raise CalendarRequestError("INVALID_ACTION")
    event_id = event_id_for(organization_id, appointment_id)
    collection = "/calendars/" + quote(binding.calendar_id, safe="") + "/events"
    if action == "cancel":
        if starts_at is not None or ends_at is not None:
            raise CalendarRequestError("UNEXPECTED_TIME_RANGE")
        return CalendarRequest("DELETE", collection + "/" + event_id, None)

    start, end = _instant(starts_at), _instant(ends_at)
    if end <= start:
        raise CalendarRequestError("INVALID_TIME_RANGE")
    body = {
        "start": {"dateTime": start.isoformat().replace("+00:00", "Z")},
        "end": {"dateTime": end.isoformat().replace("+00:00", "Z")},
    }
    if action == "create":
        # Minimize calendar PII; owner dashboard retains appointment details.
        body.update({"id": event_id, "summary": "Nova appointment"})
        return CalendarRequest("POST", collection, json.dumps(body, sort_keys=True))
    # PATCH changes only times, preserving owner-added notes and other fields.
    return CalendarRequest("PATCH", collection + "/" + event_id, json.dumps(body, sort_keys=True))
