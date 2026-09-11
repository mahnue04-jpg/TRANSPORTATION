"""Deterministic, non-clinical Care Coordination priority cards.

Priorities are operational display ranks only. They do not score medical
risk, infer disease severity, or recommend treatment.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app.helpers import now
from app.modules.lifesaver.constants import PRODUCT_DISCLAIMER

COORDINATION_FILTERS = (
    "all",
    "today",
    "appointments",
    "reminders",
    "transportation",
    "care_circle",
    "tasks",
    "alerts",
)

PRIORITY_HIGH = "HIGH"
PRIORITY_MEDIUM = "MEDIUM"
PRIORITY_LOW = "LOW"


def _as_dt(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    parsed = value
    if not isinstance(value, datetime):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _same_calendar_day(left: datetime, right: datetime) -> bool:
    return left.date() == right.date()


def assign_priority(
    *,
    kind: str,
    status: str,
    due_at: datetime | str | None = None,
    extra: dict[str, Any] | None = None,
    clock: datetime | None = None,
) -> dict[str, Any]:
    """Return a deterministic priority decision with an explainable why."""
    current = _as_dt(clock or now()) or now()
    due = _as_dt(due_at)
    extra = extra or {}
    status = (status or "").lower()
    kind = (kind or "").lower()

    if status in {"completed", "acknowledged", "cancelled", "closed", "declined", "handed_off_simulated"}:
        return {
            "priority": PRIORITY_LOW,
            "why": f"This {kind} is {status}, so it is shown as a low-priority completed item.",
            "needs_human_review": False,
        }

    if kind == "task" and status == "open" and due is not None and due <= current:
        return {
            "priority": PRIORITY_HIGH,
            "why": "An open shared care task is overdue.",
            "needs_human_review": True,
        }

    if kind == "appointment" and extra.get("unresolved_transport"):
        if due is not None and due <= current + timedelta(hours=48):
            return {
                "priority": PRIORITY_HIGH,
                "why": "An upcoming appointment has an unresolved transportation request.",
                "needs_human_review": True,
            }

    if kind == "reminder" and status == "due":
        return {
            "priority": PRIORITY_HIGH,
            "why": "A reminder is overdue and still open.",
            "needs_human_review": False,
        }

    if kind == "sos" and status == "confirmed":
        return {
            "priority": PRIORITY_HIGH,
            "why": "An SOS demonstration is confirmed and still waiting for acknowledgment.",
            "needs_human_review": True,
        }

    if kind == "handoff" and status == "pending":
        return {
            "priority": PRIORITY_MEDIUM,
            "why": "A caregiver handoff is pending human acceptance.",
            "needs_human_review": True,
        }

    if kind == "transport" and status in {"requested", "needs_review"}:
        return {
            "priority": PRIORITY_MEDIUM,
            "why": "Transportation coordination is waiting for explicit human confirmation.",
            "needs_human_review": True,
        }

    if kind == "transport" and status == "ready_for_handoff":
        return {
            "priority": PRIORITY_MEDIUM,
            "why": "Transportation is ready for a simulated handoff and still needs a human action.",
            "needs_human_review": True,
        }

    if kind == "reminder" and status == "scheduled" and due is not None and _same_calendar_day(due, current):
        return {
            "priority": PRIORITY_MEDIUM,
            "why": "A reminder is due later today.",
            "needs_human_review": False,
        }

    if kind == "alert" and status == "open":
        return {
            "priority": PRIORITY_MEDIUM,
            "why": "An alert is open and has not been acknowledged.",
            "needs_human_review": True,
        }

    if extra.get("missing_consent"):
        return {
            "priority": PRIORITY_MEDIUM,
            "why": "A required consent is still off, so this item needs human review.",
            "needs_human_review": True,
        }

    if kind == "appointment" and due is not None and due <= current + timedelta(hours=48):
        return {
            "priority": PRIORITY_MEDIUM,
            "why": "An appointment is coming up within 48 hours.",
            "needs_human_review": False,
        }

    return {
        "priority": PRIORITY_LOW,
        "why": f"This {kind} is scheduled or informational and does not need immediate review.",
        "needs_human_review": False,
    }


def _card(
    *,
    kind: str,
    title: str,
    status: str,
    due_at: datetime | str | None = None,
    extra: dict[str, Any] | None = None,
    clock: datetime | None = None,
    resource_id: str | None = None,
    filter_keys: Iterable[str] = (),
) -> dict[str, Any]:
    decision = assign_priority(kind=kind, status=status, due_at=due_at, extra=extra, clock=clock)
    keys = {"all", kind, *filter_keys}
    due = _as_dt(due_at)
    current = clock or now()
    if due is not None and (_same_calendar_day(due, current) or due <= current):
        keys.add("today")
    return {
        "kind": kind,
        "title": title,
        "status": status,
        "resource_id": resource_id,
        "due_at": due.isoformat() if due else None,
        "priority": decision["priority"],
        "why": decision["why"],
        "needs_human_review": decision["needs_human_review"],
        "filters": sorted(keys),
        "clinical": False,
    }


def matches_filter(card: dict[str, Any], selected: str) -> bool:
    selected = (selected or "all").lower()
    if selected not in COORDINATION_FILTERS:
        selected = "all"
    if selected == "all":
        return True
    if selected == "care_circle":
        return card["kind"] in {"care_circle", "handoff"}
    if selected == "transportation":
        return card["kind"] == "transport"
    return selected in card.get("filters", []) or selected == card.get("kind")


def build_coordination_cards(
    *,
    appointments: list[Any],
    reminders: list[Any],
    tasks: list[Any],
    handoffs: list[Any],
    alerts: list[Any],
    transport_requests: list[Any],
    circle_members: list[Any],
    journal_count: int,
    latest_journal_at: datetime | None,
    wellness: Any | None,
    reading_summaries: list[dict[str, Any]],
    sos_rows: list[Any],
    consents: list[dict[str, Any]],
    notification_status: dict[str, int],
    device_status: dict[str, Any],
    can_view_readings: bool,
    clock: datetime | None = None,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    current = _as_dt(clock or now()) or now()
    transport_by_appt = {
        row.appointment_id: row
        for row in transport_requests
        if getattr(row, "appointment_id", None) and getattr(row, "status", "") in {"requested", "needs_review"}
    }

    for row in appointments:
        unresolved = bool(row.id in transport_by_appt)
        cards.append(
            _card(
                kind="appointment",
                title=row.title,
                status=row.status,
                due_at=row.starts_at,
                extra={"unresolved_transport": unresolved},
                clock=current,
                resource_id=row.id,
                filter_keys=("appointments", "today") if unresolved else ("appointments",),
            )
        )

    for row in reminders:
        cards.append(
            _card(
                kind="reminder",
                title=row.title,
                status=row.status,
                due_at=row.due_at,
                clock=current,
                resource_id=row.id,
                filter_keys=("reminders",),
            )
        )

    for row in tasks:
        cards.append(
            _card(
                kind="task",
                title=row.title,
                status=row.status,
                due_at=row.due_at,
                clock=current,
                resource_id=row.id,
                filter_keys=("tasks",),
            )
        )

    for row in handoffs:
        cards.append(
            _card(
                kind="handoff",
                title="Pending caregiver handoff" if row.status == "pending" else f"Handoff {row.status}",
                status=row.status,
                due_at=row.created_at,
                clock=current,
                resource_id=row.id,
                filter_keys=("care_circle",),
            )
        )

    for row in alerts:
        cards.append(
            _card(
                kind="alert",
                title=row.title,
                status=row.status,
                due_at=row.created_at,
                clock=current,
                resource_id=row.id,
                filter_keys=("alerts",),
            )
        )

    for row in transport_requests:
        cards.append(
            _card(
                kind="transport",
                title=f"{row.pickup_label} → {row.destination_label}",
                status=row.status,
                due_at=row.pickup_at or row.created_at,
                clock=current,
                resource_id=row.id,
                filter_keys=("transportation",),
            )
        )

    active_circle = [row for row in circle_members if getattr(row, "status", "") == "active"]
    if active_circle:
        cards.append(
            _card(
                kind="care_circle",
                title=f"{len(active_circle)} active Care Circle member(s)",
                status="active",
                clock=current,
                filter_keys=("care_circle",),
            )
        )

    if wellness is not None:
        cards.append(
            _card(
                kind="wellness",
                title=f"Latest wellness check-in · mood {wellness.mood}",
                status="recorded",
                due_at=wellness.created_at,
                clock=current,
                resource_id=wellness.id,
                filter_keys=("today",),
            )
        )

    if journal_count:
        cards.append(
            {
                **_card(
                    kind="journal",
                    title=f"{journal_count} recent journal entr{'y' if journal_count == 1 else 'ies'}",
                    status="recorded",
                    due_at=latest_journal_at,
                    clock=current,
                    filter_keys=("today",),
                ),
                "body_included": False,
            }
        )

    if reading_summaries:
        cards.append(
            {
                **_card(
                    kind="readings",
                    title=f"{len(reading_summaries)} user-entered or simulated reading type(s) on file",
                    status="recorded",
                    clock=current,
                    filter_keys=("today",),
                ),
                "types": [item["reading_type"] for item in reading_summaries],
                "sources": [item["source"] for item in reading_summaries],
                "values_included": False,
                "can_view_readings": bool(can_view_readings),
            }
        )

    for row in sos_rows:
        cards.append(
            _card(
                kind="sos",
                title="SOS demonstration",
                status=row.status,
                due_at=row.created_at,
                clock=current,
                resource_id=row.id,
                filter_keys=("alerts",),
            )
        )

    missing = [row["consent_type"] for row in consents if not row.get("granted")]
    cards.append(
        _card(
            kind="consent",
            title=f"{len(consents) - len(missing)}/{len(consents)} consents granted" if consents else "No consents",
            status="ready" if not missing else "incomplete",
            extra={"missing_consent": bool(missing)},
            clock=current,
            filter_keys=("today",),
        )
    )

    cards.append(
        _card(
            kind="notifications",
            title=(
                f"Notification outbox · queued {notification_status.get('queued_local', 0)}, "
                f"simulated {notification_status.get('delivered_simulated', 0)}"
            ),
            status="local_only",
            clock=current,
            filter_keys=("alerts",),
        )
    )
    cards.append(
        _card(
            kind="device",
            title=device_status.get("label") or "No connected medical devices",
            status=device_status.get("status") or "none",
            clock=current,
        )
    )

    rank = {PRIORITY_HIGH: 0, PRIORITY_MEDIUM: 1, PRIORITY_LOW: 2}
    cards.sort(key=lambda item: (rank.get(item["priority"], 9), item.get("kind") or "", item.get("title") or ""))
    return cards


def summarize_counts(cards: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "high": sum(1 for card in cards if card["priority"] == PRIORITY_HIGH),
        "medium": sum(1 for card in cards if card["priority"] == PRIORITY_MEDIUM),
        "low": sum(1 for card in cards if card["priority"] == PRIORITY_LOW),
        "needs_review": sum(1 for card in cards if card.get("needs_human_review")),
        "total": len(cards),
    }


def coordination_disclaimer() -> str:
    return (
        "Care Coordination is an organizational summary. Priorities are not clinical "
        "risk scores and do not diagnose or treat. " + PRODUCT_DISCLAIMER
    )
