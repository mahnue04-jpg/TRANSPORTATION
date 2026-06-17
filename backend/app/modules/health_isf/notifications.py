"""
Outbound notifications for Health ISF (SMS, email, rider contact).

Uses Twilio when TWILIO_* env vars are set; otherwise logs and persists audit entries
so workflows remain testable without external providers.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.models import HealthISFDispatchLog

logger = logging.getLogger("amicor.health_isf.notifications")


def _twilio_enabled() -> bool:
    return bool(
        os.getenv("TWILIO_ACCOUNT_SID")
        and os.getenv("TWILIO_AUTH_TOKEN")
        and os.getenv("TWILIO_FROM_NUMBER")
    )


def _smtp_enabled() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"))


def _normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(digits) == 10:
        return "+1" + digits
    if digits.startswith("1") and len(digits) == 11:
        return "+" + digits
    if str(phone or "").startswith("+"):
        return str(phone).strip()
    return "+" + digits if digits else ""


def _record_notification_log(
    db: Session,
    *,
    ride_id: Optional[str],
    driver_id: Optional[str],
    channel: str,
    recipient: str,
    message: str,
    status: str,
    provider: str,
    provider_reference: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    if not ride_id:
        return
    note = f"[{channel}/{status}/{provider}] to {recipient}"
    if provider_reference:
        note += f" ref={provider_reference}"
    entry = HealthISFDispatchLog(
        id=uuid4(),
        ride_id=ride_id,
        driver_id=driver_id,
        action=f"notification_{channel}",
        note=note[:1024],
        transition_reason=json.dumps(metadata or {})[:256] if metadata else None,
        created_at=now(),
    )
    db.add(entry)
    db.commit()


def send_sms(
    db: Session,
    *,
    to_phone: str,
    message: str,
    ride_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    recipient = _normalize_phone(to_phone)
    if not recipient:
        raise ValueError("Recipient phone number is required")

    body = str(message or "").strip()
    if not body:
        raise ValueError("SMS message body is required")

    if _twilio_enabled():
        account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        from_number = os.getenv("TWILIO_FROM_NUMBER", "")
        payload = urllib.parse.urlencode(
            {"To": recipient, "From": from_number, "Body": body}
        ).encode("utf-8")
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        request = urllib.request.Request(url, data=payload, method="POST")
        credentials = f"{account_sid}:{auth_token}".encode("utf-8")
        import base64

        request.add_header(
            "Authorization",
            "Basic " + base64.b64encode(credentials).decode("ascii"),
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = json.loads(response.read().decode("utf-8"))
            sid = str(raw.get("sid") or "")
            _record_notification_log(
                db,
                ride_id=ride_id,
                driver_id=driver_id,
                channel="sms",
                recipient=recipient,
                message=body,
                status="sent",
                provider="twilio",
                provider_reference=sid,
                metadata=metadata,
            )
            return {"ok": True, "channel": "sms", "provider": "twilio", "reference": sid}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            logger.error("Twilio SMS failed: %s", detail)
            raise ValueError("SMS delivery failed") from exc

    logger.info("Simulated SMS to %s: %s", recipient, body)
    reference = f"sim_{uuid4().replace('-', '')[:16]}"
    _record_notification_log(
        db,
        ride_id=ride_id,
        driver_id=driver_id,
        channel="sms",
        recipient=recipient,
        message=body,
        status="simulated",
        provider="simulated",
        provider_reference=reference,
        metadata=metadata,
    )
    return {"ok": True, "channel": "sms", "provider": "simulated", "reference": reference}


def send_email(
    db: Session,
    *,
    to_email: str,
    subject: str,
    body: str,
    ride_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    recipient = str(to_email or "").strip()
    if not recipient or "@" not in recipient:
        raise ValueError("Valid recipient email is required")

    subject_text = str(subject or "Amicor Nova notification").strip()
    body_text = str(body or "").strip()
    if not body_text:
        raise ValueError("Email body is required")

    if _smtp_enabled():
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = subject_text
        msg["From"] = os.getenv("SMTP_FROM", "")
        msg["To"] = recipient
        msg.set_content(body_text)

        host = os.getenv("SMTP_HOST", "")
        port = int(os.getenv("SMTP_PORT", "587"))
        username = os.getenv("SMTP_USERNAME", "")
        password = os.getenv("SMTP_PASSWORD", "")

        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            if username:
                server.login(username, password)
            server.send_message(msg)

        reference = f"smtp_{uuid4().replace('-', '')[:16]}"
        _record_notification_log(
            db,
            ride_id=ride_id,
            driver_id=driver_id,
            channel="email",
            recipient=recipient,
            message=body_text[:1024],
            status="sent",
            provider="smtp",
            provider_reference=reference,
            metadata={"subject": subject_text, **(metadata or {})},
        )
        return {"ok": True, "channel": "email", "provider": "smtp", "reference": reference}

    logger.info("Simulated email to %s: %s", recipient, subject_text)
    reference = f"sim_{uuid4().replace('-', '')[:16]}"
    _record_notification_log(
        db,
        ride_id=ride_id,
        driver_id=driver_id,
        channel="email",
        recipient=recipient,
        message=body_text[:1024],
        status="simulated",
        provider="simulated",
        provider_reference=reference,
        metadata={"subject": subject_text, **(metadata or {})},
    )
    return {"ok": True, "channel": "email", "provider": "simulated", "reference": reference}


def build_rider_tracking_message(*, ride_id: str, tracking_url: str) -> str:
    return (
        f"Your Amicor transport (ride {ride_id[:8]}) is confirmed. "
        f"Track your driver live: {tracking_url}"
    )
