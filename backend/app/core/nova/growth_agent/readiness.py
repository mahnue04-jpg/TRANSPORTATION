"""Owner readiness snapshot for the receptionist pilot — no secrets, honest labels."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.nova.growth_agent import calendar_oauth
from app.core.nova.growth_agent.calendar_credentials import credential_health, get_connection
from app.core.nova.growth_agent.flags import (
    REAL_EMAIL_SEND,
    REAL_VOICE,
    calendar_sync_worker_enabled,
    google_oauth_configured,
    live_flags,
    owner_notification_worker_enabled,
    voice_simulator_enabled,
)
from app.core.nova.growth_agent.models import (
    GaCalendarSyncJob,
    GaOwnerNotification,
    GaVoiceAgentMapping,
)


def _sync_queue(db: Session, org_id: str) -> dict[str, Any]:
    rows = (
        db.query(GaCalendarSyncJob.status, func.count(GaCalendarSyncJob.id))
        .filter(GaCalendarSyncJob.organization_id == org_id)
        .group_by(GaCalendarSyncJob.status)
        .all()
    )
    counts = {str(status): int(count) for status, count in rows}
    pending = counts.get("pending", 0) + counts.get("retrying", 0) + counts.get("running", 0)
    failed = counts.get("failed", 0)
    recoverable = (
        db.query(GaCalendarSyncJob)
        .filter(
            GaCalendarSyncJob.organization_id == org_id,
            GaCalendarSyncJob.status.in_(("failed", "stale", "pending", "retrying")),
        )
        .order_by(GaCalendarSyncJob.updated_at.desc())
        .limit(10)
        .all()
    )
    empty = sum(counts.values()) == 0
    if empty:
        queue_state = "empty"
        label = "Empty queue (not a failure)"
    elif failed and pending == 0:
        queue_state = "failed"
        label = "Recoverable sync errors present"
    elif pending:
        queue_state = "active"
        label = "Sync jobs pending or in progress"
    else:
        queue_state = "healthy"
        label = "No pending sync work"
    pending_only = counts.get("pending", 0) + counts.get("retrying", 0)
    running_only = counts.get("running", 0)
    return {
        "state": queue_state,
        "label": label,
        "counts": counts,
        # Flat counters for owner UI readiness panel
        "pending": pending_only,
        "running": running_only,
        "failed": failed,
        "empty": empty,
        "pending_or_running": pending,
        "worker_enabled": calendar_sync_worker_enabled(),
        "recoverable_errors": [
            {
                "id": r.id,
                "status": r.status,
                "action": r.action,
                "last_error_code": r.last_error_code,
                "appointment_id": r.appointment_id,
                "message": r.last_error_code,
            }
            for r in recoverable
            if r.status in {"failed", "stale"}
        ],
    }


def _notifications(db: Session, org_id: str) -> dict[str, Any]:
    rows = (
        db.query(GaOwnerNotification.status, func.count(GaOwnerNotification.id))
        .filter(GaOwnerNotification.organization_id == org_id)
        .group_by(GaOwnerNotification.status)
        .all()
    )
    counts = {str(status): int(count) for status, count in rows}
    empty = sum(counts.values()) == 0
    return {
        "state": "empty" if empty else "active",
        "label": (
            "Empty queue (not a failure)"
            if empty
            else "Notifications queued or processed"
        ),
        "counts": counts,
        "worker_enabled": owner_notification_worker_enabled(),
        "live_email": REAL_EMAIL_SEND,
        "honesty": {
            "provider_accepted_is_not_inbox_receipt": True,
            "channel": "transactional_email_mock",
        },
        "configuration": {
            "purpose": "transactional_only",
            "marketing_rejected": True,
            "adapter": "mock_email" if not REAL_EMAIL_SEND else "blocked_live",
        },
    }


def _voice(db: Session, org_id: str) -> dict[str, Any]:
    mappings = (
        db.query(GaVoiceAgentMapping)
        .filter(GaVoiceAgentMapping.organization_id == org_id)
        .all()
    )
    active = [m for m in mappings if m.active and not m.kill_switch]
    twilio_token = bool(str(os.getenv("TWILIO_AUTH_TOKEN") or "").strip())
    public_base = str(os.getenv("AMICOR_PUBLIC_URL") or "").strip()
    if not mappings:
        mapping_state = "unmapped"
        label = "No Twilio number mapped for this organization"
    elif not active:
        mapping_state = "inactive_or_kill_switch"
        label = "Mapped numbers inactive or kill switch on"
    else:
        mapping_state = "mapped"
        label = f"{len(active)} active mapped number(s)"
    webhook_ready = bool(public_base) and twilio_token and mapping_state == "mapped"
    return {
        "mapping_state": mapping_state,
        "label": label,
        "mapped_count": len(mappings),
        "active_count": len(active),
        "numbers_redacted": [
            {
                "provider": m.provider,
                "external_number_suffix": (m.external_number or "")[-4:],
                "active": m.active,
                "kill_switch": m.kill_switch,
                "agent_label": m.agent_label,
            }
            for m in mappings[:10]
        ],
        "webhook": {
            "auth_token_configured": twilio_token,
            "public_base_configured": bool(public_base),
            "ready": webhook_ready,
            "live_voice": REAL_VOICE,
            "simulator_enabled": voice_simulator_enabled(),
            "label": (
                "SIMULATED — live voice hard-off"
                if not REAL_VOICE
                else "LIVE VOICE (unexpected — hard-off violated)"
            ),
        },
        "honesty": {
            "voice_simulator_is_not_live_phone": True,
            "unsigned_simulator_not_on_public_webhook": True,
        },
    }


def build_readiness(db: Session, *, org_id: str) -> dict[str, Any]:
    calendar = calendar_oauth.get_calendar_connection_status(db, org_id=org_id)
    conn = get_connection(db, org_id=org_id)
    health = credential_health(conn)
    oauth_cfg = google_oauth_configured()

    if not oauth_cfg:
        calendar_config = {
            "state": "missing_config",
            "label": "OAuth client / redirect / encryption key not configured",
        }
        connection_state = "missing_config"
        configured = False
    elif not calendar.get("connected"):
        raw_status = str(calendar.get("status") or "Not connected")
        connection_state = (
            "revoked"
            if raw_status.lower() == "revoked"
            else "needs_reconnect"
            if raw_status.lower() in {"needs_reconnect", "error"}
            else "disconnected"
        )
        calendar_config = {
            "state": connection_state,
            "label": (
                "Connection failed or disconnected"
                if calendar.get("last_error_code") or calendar.get("error_code")
                else "Not connected — owner must authorize Google Calendar"
            ),
        }
        configured = True
    else:
        calendar_config = {
            "state": "connected",
            "label": "Google Calendar connected (live writes still hard-off)",
        }
        connection_state = "connected"
        configured = True

    voice = _voice(db, org_id)
    notifications = _notifications(db, org_id)
    # Flatten notification fields the UI panel expects
    notifications = {
        **notifications,
        "configured": True,
        "config_state": "configured",
        "delivery_state": (
            "empty"
            if notifications["state"] == "empty"
            else next(iter(notifications.get("counts") or {"active": 1}), "active")
        ),
        "honesty_note": "provider_accepted is not inbox receipt — delivery acknowledged by provider only",
    }

    return {
        "organization_id": org_id,
        "flags": live_flags(),
        "calendar": {
            **calendar,
            "configuration": calendar_config,
            "connection_state": connection_state,
            "configured": configured,
            "selected_calendar_id": calendar.get("calendar_id"),
            "selected_calendar_summary": calendar.get("calendar_summary"),
            # String for UI + details object (no token material)
            "credential_health": health.get("state"),
            "credential_details": health,
            "labels": {
                "connected": bool(calendar.get("connected")),
                "unverified_live_grant": True,
                "live_writes": False,
            },
        },
        "sync_queue": _sync_queue(db, org_id),
        "notifications": notifications,
        "voice": voice,
        "twilio": {
            "mapping": voice["mapping_state"] if voice["mapping_state"] in {"mapped", "unmapped"} else "unverified",
            "number_mapping": voice["mapping_state"],
            "webhook_ready": voice["webhook"]["ready"],
            "mode": "simulator" if not REAL_VOICE else "live",
            "simulated": True,
            "live": False,
        },
        "honesty": {
            "internal_booking_is_not_google_confirmation": True,
            "provider_accepted_is_not_inbox_receipt": True,
            "voice_simulator_is_not_live_phone": True,
            "fake_provider_is_not_real_google_acceptance": True,
            "empty_queue_is_not_failure": True,
        },
        "pilot_ready_for_owner_authorization": bool(
            oauth_cfg
            and calendar.get("connected")
            and health.get("has_refresh_credential")
        ),
        "pilot_live_ready": False,
    }
