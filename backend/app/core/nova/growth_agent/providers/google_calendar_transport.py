"""Google Calendar HTTP transport — injectable client; live writes default-off."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from urllib.parse import urljoin

from app.core.nova.growth_agent.flags import REAL_CALENDAR_WRITE
from app.core.nova.growth_agent.providers.google_calendar_requests import (
    CalendarBinding,
    CalendarRequest,
    prepare_calendar_request,
)

logger = logging.getLogger("amicor.nova.growth_agent.calendar_transport")

CALENDAR_API_ROOT = "https://www.googleapis.com/calendar/v3"
FREEBUSY_PATH = "/freeBusy"


class HttpResponse(Protocol):
    status_code: int

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


class HttpClient(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: str | None = None,
        timeout: float | None = None,
    ) -> HttpResponse: ...


@dataclass
class CalendarTransportResult:
    """Outcome of one Calendar API attempt (never contains tokens or customer PII)."""

    ok: bool
    outcome: str
    # success|suppressed|retryable|credentials_expired|conflict_resolved|timeout_after_write|error
    error_code: str | None = None
    http_status: int | None = None
    etag: str | None = None
    event_id: str | None = None
    starts_at_utc: datetime | None = None
    ends_at_utc: datetime | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def _parse_event_times(event: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    start_raw = (event.get("start") or {}).get("dateTime")
    end_raw = (event.get("end") or {}).get("dateTime")
    if not start_raw or not end_raw:
        return None, None

    def _parse_iso(value: str) -> datetime:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).astimezone(timezone.utc)

    return _parse_iso(start_raw), _parse_iso(end_raw)


def _times_match(
    expected_start: datetime | None,
    expected_end: datetime | None,
    actual_start: datetime | None,
    actual_end: datetime | None,
) -> bool:
    if expected_start is None or expected_end is None or actual_start is None or actual_end is None:
        return False
    exp_s = expected_start.astimezone(timezone.utc).replace(microsecond=0)
    exp_e = expected_end.astimezone(timezone.utc).replace(microsecond=0)
    act_s = actual_start.astimezone(timezone.utc).replace(microsecond=0)
    act_e = actual_end.astimezone(timezone.utc).replace(microsecond=0)
    return exp_s == act_s and exp_e == act_e


class GoogleCalendarTransport:
    """Executes prepared Calendar requests with credential refresh via callback."""

    def __init__(
        self,
        *,
        http_client: HttpClient | None = None,
        get_access_token: Callable[[str], str] | None = None,
        api_root: str = CALENDAR_API_ROOT,
        request_timeout: float = 30.0,
    ) -> None:
        self.http_client = http_client
        self.get_access_token = get_access_token
        self.api_root = api_root.rstrip("/") + "/"
        self.request_timeout = request_timeout

    def _live_allowed(self) -> bool:
        return bool(self.http_client) or bool(REAL_CALENDAR_WRITE)

    def _suppressed(self, *, reason: str) -> CalendarTransportResult:
        return CalendarTransportResult(
            ok=False,
            outcome="suppressed",
            error_code="LIVE_CALENDAR_DISABLED",
            meta={"reason": reason},
        )

    def _auth_headers(self, organization_id: str) -> dict[str, str] | None:
        if not self.get_access_token:
            return None
        try:
            token = self.get_access_token(organization_id)
        except Exception:  # noqa: BLE001
            logger.warning("calendar access token fetch failed org=%s", organization_id)
            return None
        if not token:
            return None
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        *,
        organization_id: str,
        method: str,
        path: str,
        body: str | None = None,
    ) -> CalendarTransportResult | tuple[int, dict[str, Any] | None, str | None]:
        if not self._live_allowed():
            return self._suppressed(reason="REAL_CALENDAR_WRITE is false and no http_client injected")
        client = self.http_client
        if client is None:
            return self._suppressed(reason="no http client")

        headers = self._auth_headers(organization_id)
        if headers is None:
            return CalendarTransportResult(
                ok=False,
                outcome="credentials_expired",
                error_code="CREDENTIALS_EXPIRED",
            )

        url = urljoin(self.api_root, path.lstrip("/"))
        try:
            resp = client.request(
                method,
                url,
                headers=headers,
                data=body,
                timeout=self.request_timeout,
            )
        except TimeoutError:
            return CalendarTransportResult(
                ok=False,
                outcome="timeout_after_write",
                error_code="TIMEOUT_AFTER_WRITE",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "calendar transport error org=%s method=%s path=%s err=%s",
                organization_id,
                method,
                path.split("/")[-1][:32],
                type(exc).__name__,
            )
            return CalendarTransportResult(
                ok=False,
                outcome="error",
                error_code="TRANSPORT_ERROR",
                meta={"exception": type(exc).__name__},
            )

        status = int(getattr(resp, "status_code", 0) or 0)
        etag: str | None = None
        payload: dict[str, Any] | None = None
        if status in (200, 201):
            try:
                payload = resp.json() if hasattr(resp, "json") else None
            except Exception:  # noqa: BLE001
                payload = None
            if isinstance(payload, dict):
                etag = payload.get("etag")
            return status, payload, etag

        if status == 401:
            return CalendarTransportResult(
                ok=False,
                outcome="credentials_expired",
                error_code="CREDENTIALS_EXPIRED",
                http_status=status,
            )
        if status == 429:
            return CalendarTransportResult(
                ok=False,
                outcome="retryable",
                error_code="RATE_LIMITED",
                http_status=status,
            )
        if status == 404 and method == "DELETE":
            return CalendarTransportResult(
                ok=True,
                outcome="success",
                http_status=status,
                meta={"already_deleted": True},
            )
        return status, payload, etag

    def get_event(
        self,
        *,
        binding: CalendarBinding,
        organization_id: str,
        event_id: str,
    ) -> CalendarTransportResult:
        path = f"/calendars/{binding.calendar_id}/events/{event_id}"
        raw = self._request(organization_id=organization_id, method="GET", path=path)
        if isinstance(raw, CalendarTransportResult):
            return raw
        status, payload, etag = raw
        if status == 200 and isinstance(payload, dict):
            start, end = _parse_event_times(payload)
            return CalendarTransportResult(
                ok=True,
                outcome="success",
                http_status=status,
                etag=etag,
                event_id=str(payload.get("id") or event_id),
                starts_at_utc=start,
                ends_at_utc=end,
            )
        if status == 404:
            return CalendarTransportResult(
                ok=False,
                outcome="error",
                error_code="EVENT_NOT_FOUND",
                http_status=status,
            )
        return CalendarTransportResult(
            ok=False,
            outcome="error",
            error_code=f"HTTP_{status}",
            http_status=status,
        )

    def _execute_planned(
        self,
        *,
        binding: CalendarBinding,
        organization_id: str,
        appointment_id: str,
        action: str,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
    ) -> CalendarTransportResult:
        planned = prepare_calendar_request(
            binding=binding,
            organization_id=organization_id,
            appointment_id=appointment_id,
            action=action,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        raw = self._request(
            organization_id=organization_id,
            method=planned.method,
            path=planned.path,
            body=planned.body_json,
        )
        if isinstance(raw, CalendarTransportResult):
            return raw

        status, payload, etag = raw
        event_id = None
        if isinstance(payload, dict):
            event_id = str(payload.get("id") or "")
        if status in (200, 201):
            start, end = _parse_event_times(payload) if isinstance(payload, dict) else (None, None)
            return CalendarTransportResult(
                ok=True,
                outcome="success",
                http_status=status,
                etag=etag,
                event_id=event_id,
                starts_at_utc=start or (starts_at.astimezone(timezone.utc) if starts_at else None),
                ends_at_utc=end or (ends_at.astimezone(timezone.utc) if ends_at else None),
            )

        if action == "create" and status in (409, 412):
            from app.core.nova.growth_agent.providers.google_calendar_requests import event_id_for

            expected_id = event_id_for(organization_id, appointment_id)
            verified = self.get_event(
                binding=binding,
                organization_id=organization_id,
                event_id=expected_id,
            )
            if verified.ok and verified.event_id == expected_id:
                if _times_match(starts_at, ends_at, verified.starts_at_utc, verified.ends_at_utc):
                    return CalendarTransportResult(
                        ok=True,
                        outcome="conflict_resolved",
                        http_status=status,
                        etag=verified.etag,
                        event_id=expected_id,
                        starts_at_utc=verified.starts_at_utc,
                        ends_at_utc=verified.ends_at_utc,
                        meta={"conflict_status": status},
                    )
            return CalendarTransportResult(
                ok=False,
                outcome="error",
                error_code="CONFLICT",
                http_status=status,
            )

        return CalendarTransportResult(
            ok=False,
            outcome="retryable" if status >= 500 else "error",
            error_code=f"HTTP_{status}",
            http_status=status,
        )

    def create_event(
        self,
        *,
        binding: CalendarBinding,
        organization_id: str,
        appointment_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> CalendarTransportResult:
        return self._execute_planned(
            binding=binding,
            organization_id=organization_id,
            appointment_id=appointment_id,
            action="create",
            starts_at=starts_at,
            ends_at=ends_at,
        )

    def patch_event(
        self,
        *,
        binding: CalendarBinding,
        organization_id: str,
        appointment_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> CalendarTransportResult:
        return self._execute_planned(
            binding=binding,
            organization_id=organization_id,
            appointment_id=appointment_id,
            action="reschedule",
            starts_at=starts_at,
            ends_at=ends_at,
        )

    def delete_event(
        self,
        *,
        binding: CalendarBinding,
        organization_id: str,
        appointment_id: str,
    ) -> CalendarTransportResult:
        return self._execute_planned(
            binding=binding,
            organization_id=organization_id,
            appointment_id=appointment_id,
            action="cancel",
        )

    def list_freebusy(
        self,
        *,
        binding: CalendarBinding,
        organization_id: str,
        time_min: datetime,
        time_max: datetime,
    ) -> CalendarTransportResult:
        if not self._live_allowed():
            return self._suppressed(reason="freebusy read requires client or REAL_CALENDAR_WRITE")
        time_min_z = time_min.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        time_max_z = time_max.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        body = json.dumps(
            {
                "timeMin": time_min_z,
                "timeMax": time_max_z,
                "items": [{"id": binding.calendar_id}],
            },
            sort_keys=True,
        )
        raw = self._request(
            organization_id=organization_id,
            method="POST",
            path=FREEBUSY_PATH,
            body=body,
        )
        if isinstance(raw, CalendarTransportResult):
            return raw
        status, payload, _etag = raw
        if status != 200 or not isinstance(payload, dict):
            return CalendarTransportResult(
                ok=False,
                outcome="error",
                error_code=f"HTTP_{status}",
                http_status=status,
            )
        return CalendarTransportResult(
            ok=True,
            outcome="success",
            http_status=status,
            meta={"freebusy": payload.get("calendars") or {}},
        )

    def list_busy_events(
        self,
        *,
        binding: CalendarBinding,
        organization_id: str,
        time_min: datetime,
        time_max: datetime,
    ) -> list[tuple[datetime, datetime]]:
        """Normalize freeBusy response into UTC busy intervals."""
        result = self.list_freebusy(
            binding=binding,
            organization_id=organization_id,
            time_min=time_min,
            time_max=time_max,
        )
        if not result.ok:
            return []
        calendars = (result.meta.get("freebusy") or {}).get(binding.calendar_id) or {}
        busy: list[tuple[datetime, datetime]] = []
        for block in calendars.get("busy") or []:
            start_raw, end_raw = block.get("start"), block.get("end")
            if not start_raw or not end_raw:
                continue
            if start_raw.endswith("Z"):
                start_raw = start_raw[:-1] + "+00:00"
            if end_raw.endswith("Z"):
                end_raw = end_raw[:-1] + "+00:00"
            busy.append(
                (
                    datetime.fromisoformat(start_raw).astimezone(timezone.utc),
                    datetime.fromisoformat(end_raw).astimezone(timezone.utc),
                )
            )
        return busy