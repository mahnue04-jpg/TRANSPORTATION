"""Local caregiver notification outbox. No Twilio, SES, SendGrid, or SMS send."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.lifesaver.constants import (
    NOTIFICATION_CHANNELS,
    NOTIFICATION_SIM_LABEL,
    NOTIFICATION_STATUSES,
    NOTIFICATION_TYPES,
)
from app.modules.lifesaver.models import LifesaverNotificationOutbox


class LocalNotificationProvider:
    """Fake provider used only for local queue/simulate/suppress/retry."""

    name = "local_fake"

    def deliver(self, row: LifesaverNotificationOutbox, *, succeed: bool) -> str:
        if succeed:
            return "delivered_simulated"
        return "failed_simulated"


def serialize_notice(row: LifesaverNotificationOutbox) -> dict:
    return {
        "id": row.id,
        "notification_type": row.notification_type,
        "channel": row.channel,
        "status": row.status,
        "title": row.title,
        "reason": row.reason,
        "recipient_role": row.recipient_role,
        "recipient_profile_id": row.recipient_profile_id,
        "redacted": bool(row.redacted),
        "retry_count": row.retry_count,
        "external_message_sent": False,
        "label": NOTIFICATION_SIM_LABEL,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def queue(
    db: Session,
    *,
    organization_id: str,
    profile_id: str,
    recipient_profile_id: str | None,
    recipient_role: str,
    notification_type: str,
    channel: str,
    title: str,
    reason: str | None,
    redacted: bool = True,
) -> LifesaverNotificationOutbox:
    if notification_type not in NOTIFICATION_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported notification type.")
    if channel not in NOTIFICATION_CHANNELS:
        raise HTTPException(status_code=422, detail="Unsupported notification channel.")
    row = LifesaverNotificationOutbox(
        organization_id=organization_id,
        profile_id=profile_id,
        recipient_profile_id=recipient_profile_id,
        recipient_role=recipient_role[:32],
        notification_type=notification_type,
        channel=channel,
        status="queued_local",
        title=title.strip()[:160],
        reason=(reason or "").strip()[:256] or None,
        redacted=bool(redacted),
        retry_count=0,
        updated_at=now(),
    )
    db.add(row)
    db.flush()
    return row


def simulate(db: Session, row: LifesaverNotificationOutbox, *, succeed: bool) -> LifesaverNotificationOutbox:
    if row.status not in {"queued_local", "failed_simulated"}:
        raise HTTPException(status_code=409, detail="Only queued or failed-simulated notices can be simulated.")
    provider = LocalNotificationProvider()
    row.status = provider.deliver(row, succeed=succeed)
    if not succeed:
        row.retry_count = int(row.retry_count or 0) + 1
        row.reason = "simulated_failure"
    else:
        row.reason = "simulated_delivery"
    row.updated_at = now()
    return row


def suppress(db: Session, row: LifesaverNotificationOutbox) -> LifesaverNotificationOutbox:
    row.status = "suppressed"
    row.reason = "suppressed_local"
    row.updated_at = now()
    return row


def retry(db: Session, row: LifesaverNotificationOutbox) -> LifesaverNotificationOutbox:
    if row.status != "failed_simulated":
        raise HTTPException(status_code=409, detail="Only failed-simulated notices can be retried locally.")
    row.status = "queued_local"
    row.reason = "retry_queued"
    row.updated_at = now()
    return row


def list_notices(db: Session, *, organization_id: str, profile_ids: list[str]) -> list[LifesaverNotificationOutbox]:
    return (
        db.query(LifesaverNotificationOutbox)
        .filter(
            LifesaverNotificationOutbox.organization_id == organization_id,
            or_(
                LifesaverNotificationOutbox.profile_id.in_(profile_ids),
                LifesaverNotificationOutbox.recipient_profile_id.in_(profile_ids),
            ),
        )
        .order_by(LifesaverNotificationOutbox.created_at.desc())
        .limit(60)
        .all()
    )


def get_notice(db: Session, *, organization_id: str, notice_id: str) -> LifesaverNotificationOutbox:
    row = (
        db.query(LifesaverNotificationOutbox)
        .filter(
            LifesaverNotificationOutbox.id == notice_id,
            LifesaverNotificationOutbox.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Notification was not found.")
    if row.status not in NOTIFICATION_STATUSES:
        raise HTTPException(status_code=409, detail="Unsupported notification status.")
    return row
