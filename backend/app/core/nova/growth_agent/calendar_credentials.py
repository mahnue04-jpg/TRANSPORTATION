"""Gated credential access for Google Calendar — decrypt/refresh without exposing tokens.

Live network refresh remains hard-off unless an HTTP client is injected (tests) or
REAL_CALENDAR_WRITE is somehow true (it is hard-coded False). Application booking and
sync can construct a GoogleCalendarTransport with ``access_token_provider_for(db)``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.nova.growth_agent.models import GaCalendarConnection
from app.core.nova.growth_agent.providers.credential_crypto import decrypt_secret, encrypt_secret
from app.core.nova.growth_agent.providers.google_oauth_http import (
    OAuthHttpError,
    refresh_access_token,
)

_SKEW = timedelta(seconds=60)


def _utcnow() -> datetime:
    return datetime.utcnow()


def get_connection(db: Session, *, org_id: str) -> GaCalendarConnection | None:
    return (
        db.query(GaCalendarConnection)
        .filter(GaCalendarConnection.organization_id == org_id)
        .one_or_none()
    )


def credential_health(conn: GaCalendarConnection | None) -> dict[str, Any]:
    """Safe health summary — never includes token material."""
    if conn is None:
        return {
            "state": "missing_connection",
            "has_refresh_credential": False,
            "has_access_credential": False,
            "access_expires_at": None,
            "refresh_needed": False,
        }
    has_refresh = bool(conn.refresh_token_encrypted)
    has_access = bool(conn.access_token_encrypted)
    expires = conn.access_token_expires_at
    refresh_needed = False
    if expires is not None:
        refresh_needed = expires <= _utcnow() + _SKEW
    elif has_refresh and not has_access:
        refresh_needed = True
    status = (conn.status or "").lower()
    if status in {"not_connected", "revoked"}:
        state = status
    elif not has_refresh:
        state = "missing_refresh"
    elif status == "needs_reconnect":
        state = "needs_reconnect"
    elif status == "connected":
        state = "healthy" if has_refresh else "missing_refresh"
    else:
        state = status or "unknown"
    return {
        "state": state,
        "has_refresh_credential": has_refresh,
        "has_access_credential": has_access,
        "access_expires_at": expires.isoformat() + "Z" if expires else None,
        "refresh_needed": refresh_needed,
        "last_error_code": conn.last_error_code,
        "calendar_id": conn.calendar_id,
        "calendar_summary": conn.calendar_summary,
        "provider": conn.provider or "google",
        "connection_status": conn.status,
    }


def resolve_access_token(
    db: Session,
    *,
    org_id: str,
    http_client: Any | None = None,
    force_refresh: bool = False,
) -> str:
    """Return a usable access token for org calendar calls.

    Raises OAuthHttpError with safe codes. Never logs token values.
    """
    conn = get_connection(db, org_id=org_id)
    if conn is None or (conn.status or "").lower() != "connected":
        raise OAuthHttpError("CALENDAR_NOT_CONNECTED")
    if not conn.refresh_token_encrypted and not conn.access_token_encrypted:
        raise OAuthHttpError("CREDENTIALS_MISSING")

    expires = conn.access_token_expires_at
    access_fresh = (
        bool(conn.access_token_encrypted)
        and expires is not None
        and expires > _utcnow() + _SKEW
        and not force_refresh
    )
    if access_fresh:
        return decrypt_secret(conn.access_token_encrypted)

    if not conn.refresh_token_encrypted:
        conn.status = "needs_reconnect"
        conn.last_error_code = "REFRESH_TOKEN_MISSING"
        db.flush()
        raise OAuthHttpError("REFRESH_TOKEN_MISSING")

    refresh = decrypt_secret(conn.refresh_token_encrypted)
    try:
        payload = refresh_access_token(refresh_token=refresh, http_client=http_client)
    except OAuthHttpError as exc:
        if exc.code in {"INVALID_GRANT", "UNAUTHORIZED_CLIENT", "invalid_grant"}:
            conn.status = "needs_reconnect"
            conn.last_error_code = "CREDENTIALS_EXPIRED"
            db.flush()
        raise

    access = str(payload.get("access_token") or "").strip()
    if not access:
        raise OAuthHttpError("REFRESH_FAILED")
    expires_in = int(payload.get("expires_in") or 0)
    conn.access_token_encrypted = encrypt_secret(access)
    if expires_in > 0:
        conn.access_token_expires_at = _utcnow() + timedelta(seconds=expires_in)
    new_refresh = str(payload.get("refresh_token") or "").strip()
    if new_refresh:
        conn.refresh_token_encrypted = encrypt_secret(new_refresh)
    conn.last_error_code = None
    db.flush()
    return access


def access_token_provider_for(
    db: Session,
    *,
    http_client: Any | None = None,
) -> Callable[[str], str]:
    """Build a ``get_access_token(organization_id)`` callback for GoogleCalendarTransport."""

    def _provider(organization_id: str) -> str:
        return resolve_access_token(db, org_id=organization_id, http_client=http_client)

    return _provider


def list_calendars_for_org(
    db: Session,
    *,
    org_id: str,
    http_client: Any | None = None,
    calendar_list_fetcher: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """List calendars for a connected org. Injectable fetcher for tests; live hard-off."""
    conn = get_connection(db, org_id=org_id)
    health = credential_health(conn)
    if conn is None or health["state"] in {"missing_connection", "not_connected", "revoked"}:
        return {
            "connected": False,
            "calendars": [],
            "error_code": "CALENDAR_NOT_CONNECTED",
            "credential_health": health,
        }

    if calendar_list_fetcher is not None:
        calendars = calendar_list_fetcher(org_id)
        return {
            "connected": True,
            "calendars": calendars,
            "selected_calendar_id": conn.calendar_id,
            "credential_health": health,
            "live": False,
        }

    # Without injection, do not hit Google — surface readiness honestly.
    return {
        "connected": True,
        "calendars": (
            [
                {
                    "id": conn.calendar_id or "primary",
                    "summary": conn.calendar_summary or "primary",
                    "primary": True,
                    "selected": True,
                }
            ]
            if conn.calendar_id
            else []
        ),
        "selected_calendar_id": conn.calendar_id,
        "credential_health": health,
        "live": False,
        "note": "Calendar list is local/selected only until an injected or authorized client is used",
    }


def select_calendar(
    db: Session,
    *,
    org_id: str,
    owner_user_id: str,
    calendar_id: str,
    calendar_summary: str | None = None,
) -> dict[str, Any]:
    """Persist the owner's selected calendar id after OAuth (no live Google call)."""
    from app.core.nova.growth_agent.calendar_oauth import get_calendar_connection_status

    conn = get_connection(db, org_id=org_id)
    if conn is None or (conn.status or "").lower() != "connected":
        return {
            "connected": False,
            "status": "Not connected",
            "error_code": "CALENDAR_NOT_CONNECTED",
        }
    if conn.owner_user_id != owner_user_id:
        return {
            "connected": False,
            "status": "Not connected",
            "error_code": "OWNER_MISMATCH",
        }
    cal_id = (calendar_id or "").strip()
    if not cal_id or len(cal_id) > 320:
        return {
            "connected": True,
            "status": "connected",
            "error_code": "INVALID_CALENDAR_ID",
            "calendar_id": conn.calendar_id,
        }
    conn.calendar_id = cal_id
    if calendar_summary is not None:
        conn.calendar_summary = (calendar_summary or "").strip()[:200] or None
    db.commit()
    status = get_calendar_connection_status(db, org_id=org_id)
    status["credential_health"] = credential_health(conn)
    return status
