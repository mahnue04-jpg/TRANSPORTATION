"""Internal recurring-work templates. No calendars, emails, or external schedules."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.helpers import now

RECURRING_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "template_id": "weekly_client_report",
        "label": "Weekly client report",
        "frequency": "weekly",
        "kind": "deliverable",
        "deliverable_type": "REPORT",
        "task_title": "Prepare weekly report draft",
        "owner_review_required": True,
        "external_send": False,
    },
    {
        "template_id": "monthly_status_pack",
        "label": "Monthly status pack",
        "frequency": "monthly",
        "kind": "deliverable",
        "deliverable_type": "FOLLOW_UP_PACKAGE",
        "task_title": "Assemble monthly status pack",
        "owner_review_required": True,
        "external_send": False,
    },
    {
        "template_id": "weekly_admin_tasks",
        "label": "Weekly administrative tasks",
        "frequency": "weekly",
        "kind": "task",
        "deliverable_type": "DOCUMENT",
        "task_title": "Complete weekly administrative checklist",
        "owner_review_required": True,
        "external_send": False,
    },
)


def next_due_date(frequency: str, *, from_time: datetime | None = None) -> datetime:
    start = from_time or now()
    token = str(frequency or "weekly").strip().lower()
    if token == "monthly":
        return start + timedelta(days=30)
    if token in {"daily", "day"}:
        return start + timedelta(days=1)
    if token in {"one_time", "once"}:
        return start
    return start + timedelta(days=7)


def reporting_period(frequency: str, *, from_time: datetime | None = None) -> dict[str, str]:
    start = from_time or now()
    due = next_due_date(frequency, from_time=start)
    return {
        "frequency": str(frequency or "weekly"),
        "period_start": start.isoformat(),
        "period_end": due.isoformat(),
        "next_due_date": due.isoformat(),
        "notifications_enabled": False,
        "external_schedule_created": False,
    }


def list_recurring_templates() -> list[dict[str, Any]]:
    return [dict(item) for item in RECURRING_TEMPLATES]
