"""Consent-gated workflow primitives with dry-run preview and approval gates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.nova.growth_agent.consent import assert_can_message
from app.core.nova.growth_agent.errors import ConsentRequiredError, GrowthAgentError
from app.core.nova.growth_agent.quiet_hours import in_quiet_hours, next_send_after_quiet_hours

DEFAULT_WORKFLOWS = (
    {
        "code": "inquiry_ack",
        "name": "Inquiry acknowledgement",
        "purpose": "transactional",
        "steps": [
            {
                "id": "ack",
                "channel": "email",
                "template": "Thanks for contacting {business_name}. We received your inquiry.",
                "delay_minutes": 0,
            }
        ],
    },
    {
        "code": "appointment_reminder",
        "name": "Appointment reminder",
        "purpose": "transactional",
        "steps": [
            {
                "id": "reminder",
                "channel": "sms",
                "template": "Reminder: your appointment with {business_name} is coming up.",
                "delay_minutes": 60,
            }
        ],
    },
    {
        "code": "post_service_followup",
        "name": "Post-service follow-up",
        "purpose": "marketing",
        "steps": [
            {
                "id": "followup",
                "channel": "email",
                "template": "Thanks for visiting {business_name}. Reply STOP to opt out of marketing.",
                "delay_minutes": 1440,
            }
        ],
    },
)


def build_preview(
    *,
    workflow: dict[str, Any],
    business_name: str,
    contact_id: str,
    channel_override: str | None = None,
    quiet_hours: dict[str, Any] | None = None,
    tz_name: str = "America/Chicago",
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    messages = []
    for step in workflow.get("steps") or workflow.get("steps_json") or []:
        channel = channel_override or step.get("channel") or "email"
        body = str(step.get("template") or "").format(business_name=business_name)
        scheduled = now
        delay = int(step.get("delay_minutes") or 0)
        if delay:
            from datetime import timedelta

            scheduled = now + timedelta(minutes=delay)
        if in_quiet_hours(scheduled, quiet_hours, tz_name=tz_name):
            scheduled = next_send_after_quiet_hours(scheduled, quiet_hours, tz_name=tz_name)
        # Rough cost estimates — mock only.
        cost = 0.0 if channel in {"email", "web"} else 0.0075
        messages.append(
            {
                "step_id": step.get("id"),
                "channel": channel,
                "recipient_contact_id": contact_id,
                "body_preview": body,
                "scheduled_for_utc": scheduled.isoformat().replace("+00:00", "Z"),
                "cost_estimate_usd": cost,
                "quiet_hours_adjusted": scheduled != now,
            }
        )
    return {
        "workflow_code": workflow.get("code"),
        "purpose": workflow.get("purpose"),
        "requires_approval": True,
        "messages": messages,
        "total_cost_estimate_usd": round(sum(m["cost_estimate_usd"] for m in messages), 6),
        "dry_run": True,
    }


def validate_send_allowed(
    *,
    purpose: str,
    channel: str,
    consent_records: list[dict[str, Any]],
    do_not_contact: bool,
    agent_paused: bool,
    agent_disabled: bool,
) -> None:
    if agent_disabled:
        raise GrowthAgentError("AGENT_DISABLED", "Agent is disabled by owner", http_status=403)
    if agent_paused:
        raise GrowthAgentError("AGENT_PAUSED", "Agent is paused; hand off to human", http_status=403)
    try:
        assert_can_message(
            consent_records,
            channel=channel,
            purpose=purpose,
            do_not_contact=do_not_contact,
        )
    except ConsentRequiredError:
        raise
