"""Secure customer forgot/reset password flow. Does not change plan, role, or tenant."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.helpers import now
from app.password_reset import PasswordResetToken, default_reset_expiry, token_is_expired

logger = logging.getLogger("amicor.auth.password_reset")

GENERIC_REQUEST_MESSAGE = (
    "If an account exists for that email, password reset instructions have been sent."
)
RESET_TOKEN_BYTES = 32
_TEST_CAPTURE: dict[str, str] = {}


def ensure_password_reset_schema(engine=None) -> None:
    from sqlalchemy import inspect

    from app.db.session import engine as default_engine

    bind = engine or default_engine
    inspector = inspect(bind)
    if "password_reset_tokens" not in set(inspector.get_table_names()):
        PasswordResetToken.__table__.create(bind=bind, checkfirst=True)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def clear_test_reset_capture() -> None:
    _TEST_CAPTURE.clear()


def get_test_reset_token(email: str | None = None) -> str | None:
    """Test-only helper. Returns None unless AMICOR_PASSWORD_RESET_TEST_CAPTURE is enabled."""
    if not _test_capture_enabled():
        return None
    if email:
        return _TEST_CAPTURE.get(str(email).strip().lower())
    if len(_TEST_CAPTURE) == 1:
        return next(iter(_TEST_CAPTURE.values()))
    return None


def _test_capture_enabled() -> bool:
    # This diagnostic captures plaintext one-time links; never allow it in production.
    # Render itself is not a production signal (staging previews also run on Render).
    production_names = ("APP_ENV", "AMICOR_ENVIRONMENT", "ENVIRONMENT", "FLASK_ENV")
    if any((os.getenv(name) or "").strip().lower() in {"production", "prod"} for name in production_names):
        return False
    return (os.getenv("AMICOR_PASSWORD_RESET_TEST_CAPTURE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _sendgrid_configured() -> bool:
    return bool(
        (os.getenv("SENDGRID_API_KEY") or "").strip()
        and (os.getenv("SENDGRID_FROM_EMAIL") or "").strip()
    )


def password_reset_email_configured() -> bool:
    if _sendgrid_configured():
        return True
    host = (os.getenv("AUTH_SMTP_HOST") or os.getenv("MARKETING_SMTP_HOST") or "").strip()
    mail_from = (os.getenv("AUTH_SMTP_FROM") or os.getenv("MARKETING_SMTP_FROM") or "").strip()
    return bool(host and mail_from)


def _send_reset_via_sendgrid(*, to_email: str, reset_url: str) -> dict[str, Any]:
    """Send only through SendGrid's HTTPS API; never log keys, links, or tokens."""
    mail_from = (os.getenv("SENDGRID_FROM_EMAIL") or "").strip()
    api_key = (os.getenv("SENDGRID_API_KEY") or "").strip()
    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": mail_from},
        "subject": "AMICOR password reset",
        "content": [{
            "type": "text/plain",
            "value": (
                "Use this one-time link to set a new password. "
                "It expires in one hour.\n\n"
                + reset_url
                + "\n\nIf you did not request a reset, you can ignore this message."
            ),
        }],
    }
    request = Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            status = response.status
        if status != 202:
            logger.warning("password_reset_email_failed provider=sendgrid reason=unexpected_status")
            return {"attempted": True, "sent": False, "reason": "send_failed"}
        logger.info("password_reset_email_accepted provider=sendgrid")
        return {"attempted": True, "sent": True, "reason": "accepted"}
    except Exception:
        # Never log exception details: provider errors could contain sensitive headers.
        logger.warning("password_reset_email_failed provider=sendgrid")
        return {"attempted": True, "sent": False, "reason": "send_failed"}


def _public_base_url() -> str:
    return (
        os.getenv("AMICOR_PUBLIC_BASE_URL")
        or os.getenv("NOVA_SIGNUP_PUBLIC_BASE_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or os.getenv("AMICOR_PUBLIC_URL")
        or "https://amicor-health-isf-py.onrender.com"
    ).rstrip("/")


def _send_reset_email(*, to_email: str, reset_url: str) -> dict[str, Any]:
    if _sendgrid_configured():
        return _send_reset_via_sendgrid(to_email=to_email, reset_url=reset_url)
    if (os.getenv("SENDGRID_API_KEY") or "").strip() or (os.getenv("SENDGRID_FROM_EMAIL") or "").strip():
        # Partial HTTPS configuration must not silently fall back to SMTP.
        logger.warning("password_reset_email_skipped reason=incomplete_https_config")
        return {"attempted": False, "sent": False, "reason": "not_configured"}
    if not password_reset_email_configured():
        logger.info("password_reset_email_skipped reason=not_configured")
        return {"attempted": False, "sent": False, "reason": "not_configured"}

    host = (os.getenv("AUTH_SMTP_HOST") or os.getenv("MARKETING_SMTP_HOST") or "").strip()
    port_raw = (os.getenv("AUTH_SMTP_PORT") or os.getenv("MARKETING_SMTP_PORT") or "587").strip()
    mail_from = (os.getenv("AUTH_SMTP_FROM") or os.getenv("MARKETING_SMTP_FROM") or "").strip()
    username = (os.getenv("AUTH_SMTP_USER") or os.getenv("MARKETING_SMTP_USER") or "").strip()
    password = os.getenv("AUTH_SMTP_PASSWORD") or os.getenv("MARKETING_SMTP_PASSWORD") or ""
    try:
        port = int(port_raw)
    except ValueError:
        port = 587

    message = EmailMessage()
    message["Subject"] = "AMICOR password reset"
    message["From"] = mail_from
    message["To"] = to_email
    message.set_content(
        "Use this one-time link to set a new password. It expires in one hour.\n\n"
        f"{reset_url}\n\n"
        "If you did not request a reset, you can ignore this message."
    )
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls(context=context)
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
        logger.info("password_reset_email_sent")
        return {"attempted": True, "sent": True, "reason": "sent"}
    except Exception:
        logger.exception("password_reset_email_failed")
        return {"attempted": True, "sent": False, "reason": "send_failed"}


def _finalize_reset_delivery(
    db: Session, *, new_token: PasswordResetToken, accepted: bool,
) -> None:
    """Serialize accepted sends by account; preserve prior links on failure.

    Provider acceptance means queued, not delivered. The account row lock makes
    overlapping PostgreSQL finalizations execute in sequence, so the latest
    accepted request revokes earlier outstanding reset tokens atomically.
    """
    from app.db.models import User as UserModel

    if not accepted:
        db.delete(new_token)
        db.commit()
        return

    account = (
        db.query(UserModel)
        .filter(func.lower(UserModel.email) == new_token.email.lower())
        .with_for_update()
        .one_or_none()
    )
    if account is None:
        # The account disappeared before the email provider accepted the mail.
        db.delete(new_token)
        db.commit()
        return

    db.query(PasswordResetToken).filter(
        PasswordResetToken.email == new_token.email,
        PasswordResetToken.token_hash != new_token.token_hash,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now()}, synchronize_session=False)
    db.commit()


def request_password_reset(db: Session, *, email: str) -> dict[str, Any]:
    """Always returns a generic message. Never reveals whether the email exists."""
    from app.auth import _validate_email
    from app.db.models import User as UserModel

    ensure_password_reset_schema(engine=db.get_bind())
    public_response = {"status": "ok", "message": GENERIC_REQUEST_MESSAGE}
    try:
        normalized = _validate_email(email)
    except Exception:
        return public_response

    user = (
        db.query(UserModel)
        .filter(func.lower(UserModel.email) == normalized)
        .first()
    )
    if user is None or not bool(getattr(user, "is_active", True)):
        return public_response

    plain = secrets.token_urlsafe(RESET_TOKEN_BYTES)
    token_hash = hash_reset_token(plain)
    # Keep older usable links until the replacement email is accepted.
    new_token = PasswordResetToken(
        email=normalized,
        token_hash=token_hash,
        expires_at=default_reset_expiry(),
    )
    db.add(new_token)
    db.commit()

    reset_url = f"{_public_base_url()}/nova/reset-password?token={quote(plain)}"
    send_result = _send_reset_email(to_email=normalized, reset_url=reset_url)
    _finalize_reset_delivery(db, new_token=new_token, accepted=send_result["sent"])
    # Test-only capture also covers configured-but-offline mail transports.
    # This flag is explicitly denied in production by _test_capture_enabled().
    if _test_capture_enabled():
        _TEST_CAPTURE[normalized] = plain
    return public_response


def apply_password_reset(db: Session, *, token: str, new_password: str) -> dict[str, Any]:
    """Consume a one-time token, set a new password, and revoke existing sessions."""
    from app.auth import _validate_password, hash_password
    from app.core.nova.signup.models import NovaSignupAccount
    from app.core.nova.signup.schema_ensure import ensure_nova_signup_schema
    from app.db.models import RefreshToken as RefreshTokenModel, User as UserModel

    ensure_password_reset_schema(engine=db.get_bind())
    _validate_password(new_password)
    raw = str(token or "").strip()
    if not raw:
        raise ValueError("Invalid or expired reset link")
    token_hash = hash_reset_token(raw)
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .first()
    )
    if row is None or row.used_at is not None or token_is_expired(row.expires_at):
        raise ValueError("Invalid or expired reset link")

    # Serialize resets for the same account on PostgreSQL. A concurrent
    # request must re-check its token after the account row lock is obtained.
    users = (
        db.query(UserModel)
        .filter(func.lower(UserModel.email) == str(row.email).lower())
        .with_for_update()
        .all()
    )
    if len(users) != 1:
        raise ValueError("Invalid or expired reset link")
    user = users[0]
    db.refresh(row)
    if row.used_at is not None or token_is_expired(row.expires_at):
        raise ValueError("Invalid or expired reset link")
    # Snapshot identity fields so callers can assert they did not change.
    before = {
        "role": user.role,
        "organization_id": getattr(user, "organization_id", None),
        "organization_name": getattr(user, "organization_name", None),
        "authorized_roles": getattr(user, "authorized_roles", None),
        "is_active": user.is_active,
    }
    user.hashed_password = hash_password(new_password)
    user.auth_version = int(getattr(user, "auth_version", 0) or 0) + 1
    db.query(RefreshTokenModel).filter(
        RefreshTokenModel.user_id == user.id,
        RefreshTokenModel.revoked == False,  # noqa: E712
    ).update({RefreshTokenModel.revoked: True}, synchronize_session=False)
    # Consumption of one link revokes every other outstanding link for
    # the account, in the same transaction as the password change.
    db.query(PasswordResetToken).filter(
        PasswordResetToken.email == str(row.email).lower(),
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now()}, synchronize_session=False)

    ensure_nova_signup_schema(engine=db.get_bind())
    signup = (
        db.query(NovaSignupAccount)
        .filter(func.lower(NovaSignupAccount.email) == str(row.email).lower())
        .first()
    )
    if signup is not None:
        signup.password_hash = user.hashed_password
        signup.updated_at = now()

    db.commit()
    after = {
        "role": user.role,
        "organization_id": getattr(user, "organization_id", None),
        "organization_name": getattr(user, "organization_name", None),
        "authorized_roles": getattr(user, "authorized_roles", None),
        "is_active": user.is_active,
    }
    if before != after:
        raise RuntimeError("Password reset unexpectedly altered account identity")
    return {"status": "ok", "message": "Password updated. You can sign in with your new password."}
