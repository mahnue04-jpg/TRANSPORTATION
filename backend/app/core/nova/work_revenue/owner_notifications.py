"""Best-effort owner approval email notifications for Nova Work & Revenue.

Notifications are queued on the SQLAlchemy session and sent only after a
successful commit. Rollbacks discard pending notifications.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger("amicor.nova.owner_notifications")
_PENDING_KEY = "nova_owner_approval_notifications"


def _env(primary: str, fallback: str | None = None, default: str = "") -> str:
    value = (os.getenv(primary) or "").strip()
    if value:
        return value
    if fallback:
        return (os.getenv(fallback) or "").strip()
    return default


def queue_owner_approval_notification(
    db: Session,
    action: Any,
    *,
    owner_email: str | None = None,
) -> None:
    """Queue one owner-action notification for delivery after commit."""
    recipient = _env("NOVA_OWNER_APPROVAL_NOTIFY_TO", "MARKETING_LEAD_NOTIFY_TO") or str(owner_email or "").strip()
    if "@" not in recipient:
        return
    payload = {
        "to": recipient,
        "action_id": str(getattr(action, "action_id", "") or ""),
        "action_type": str(getattr(action, "action_type", "") or "OWNER_ACTION"),
        "explanation": str(getattr(action, "explanation", "") or "Owner approval or action is required."),
        "opportunity_id": str(getattr(action, "opportunity_id", "") or ""),
        "application_id": str(getattr(action, "application_id", "") or ""),
        "engagement_id": str(getattr(action, "engagement_id", "") or ""),
        "ref_type": str(getattr(action, "ref_type", "") or ""),
        "ref_id": str(getattr(action, "ref_id", "") or ""),
    }
    pending = db.info.setdefault(_PENDING_KEY, [])
    if any(item.get("action_id") == payload["action_id"] for item in pending):
        return
    pending.append(payload)


def _send(payload: dict[str, str]) -> None:
    host = _env("NOVA_OWNER_SMTP_HOST", "MARKETING_SMTP_HOST")
    mail_from = _env("NOVA_OWNER_SMTP_FROM", "MARKETING_SMTP_FROM")
    if not host or not mail_from:
        logger.info("owner_approval_email_skipped reason=not_configured action_id=%s", payload.get("action_id"))
        return

    port_raw = _env("NOVA_OWNER_SMTP_PORT", "MARKETING_SMTP_PORT", "587") or "587"
    user = _env("NOVA_OWNER_SMTP_USER", "MARKETING_SMTP_USER")
    password = os.getenv("NOVA_OWNER_SMTP_PASSWORD") or os.getenv("MARKETING_SMTP_PASSWORD") or ""
    tls_raw = _env("NOVA_OWNER_SMTP_USE_TLS", "MARKETING_SMTP_USE_TLS", "1").lower()
    use_tls = tls_raw in {"1", "true", "yes", "on"}
    try:
        port = int(port_raw)
    except ValueError:
        logger.warning("owner_approval_email_failed reason=invalid_port action_id=%s", payload.get("action_id"))
        return

    action_type = payload.get("action_type") or "OWNER_ACTION"
    subject = f"[Nova Approval Required] {action_type.replace('_', ' ').title()}"
    lines = [
        "Nova needs your approval or action.",
        "",
        f"Action: {action_type}",
        f"Action ID: {payload.get('action_id') or '-'}",
        f"Why: {payload.get('explanation') or '-'}",
    ]
    for label, key in (
        ("Opportunity", "opportunity_id"),
        ("Application", "application_id"),
        ("Engagement", "engagement_id"),
        ("Reference type", "ref_type"),
        ("Reference", "ref_id"),
    ):
        if payload.get(key):
            lines.append(f"{label}: {payload[key]}")
    lines += [
        "",
        "Open Nova Work & Revenue / Nova Today to review and approve.",
        "This email is a notification only. No external action was executed by sending it.",
    ]

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail_from
    message["To"] = payload["to"]
    message.set_content("\n".join(lines))

    try:
        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                if user:
                    smtp.login(user, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(message)
        logger.info("owner_approval_email_sent action_id=%s", payload.get("action_id"))
    except Exception as exc:
        logger.warning(
            "owner_approval_email_failed reason=smtp_error action_id=%s exc_type=%s",
            payload.get("action_id"),
            type(exc).__name__,
        )


@event.listens_for(Session, "after_commit")
def _flush_owner_notifications(session: Session) -> None:
    pending = list(session.info.pop(_PENDING_KEY, []) or [])
    for payload in pending:
        _send(payload)


@event.listens_for(Session, "after_rollback")
def _discard_owner_notifications(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)
