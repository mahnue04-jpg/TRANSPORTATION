"""Google Calendar OAuth start/complete — PKCE, encrypted tokens, tenant-bound state."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.nova.growth_agent.flags import google_oauth_configured
from app.core.nova.growth_agent.models import GaCalendarConnection, GaCalendarOAuthState
from app.core.nova.growth_agent.providers.credential_crypto import decrypt_secret, encrypt_secret
from app.core.nova.growth_agent.providers.google_oauth_http import (
    OAuthHttpError,
    build_google_authorize_query,
    exchange_authorization_code,
)

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_OAUTH_TTL = timedelta(minutes=10)
_SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
)


def _now() -> datetime:
    return datetime.utcnow()


def _id() -> str:
    return uuid4().hex


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _approved_redirect_uri() -> str:
    return str(os.getenv("NOVA_GA_GOOGLE_OAUTH_REDIRECT_URI") or "").strip()


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _not_connected_payload(**extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "Not connected",
        "calendar_id": None,
        "last_error_code": extra.pop("last_error_code", None),
        "connected_at": None,
    }
    payload.update(extra)
    return payload


def get_calendar_connection_status(db: Session, *, org_id: str) -> dict[str, Any]:
    if not google_oauth_configured():
        return _not_connected_payload(error_code="OAUTH_NOT_CONFIGURED")

    row = (
        db.query(GaCalendarConnection)
        .filter(GaCalendarConnection.organization_id == org_id)
        .one_or_none()
    )
    if row is None or row.status in {"not_connected", "revoked"}:
        return _not_connected_payload(
            last_error_code=row.last_error_code if row else None,
            disconnected_at=row.disconnected_at.isoformat() if row and row.disconnected_at else None,
        )

    status = row.status
    if status == "not_connected":
        display = "Not connected"
    else:
        display = status

    return {
        "status": display,
        "calendar_id": row.calendar_id,
        "last_error_code": row.last_error_code,
        "connected_at": row.connected_at.isoformat() if row.connected_at else None,
        "disconnected_at": row.disconnected_at.isoformat() if row.disconnected_at else None,
        "provider": row.provider,
    }


def start_oauth(
    db: Session,
    *,
    org_id: str,
    owner_user_id: str,
    session_fingerprint: str,
    redirect_uri: str,
) -> dict[str, Any]:
    if not google_oauth_configured():
        return _not_connected_payload(error_code="OAUTH_NOT_CONFIGURED")

    approved = _approved_redirect_uri()
    if not approved or redirect_uri != approved:
        return {
            "status": "Not connected",
            "error_code": "REDIRECT_URI_MISMATCH",
            "authorization_url": None,
            "state": None,
            "expires_at": None,
        }

    client_id = str(os.getenv("NOVA_GA_GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    expires_at = _now() + _OAUTH_TTL

    oauth_row = GaCalendarOAuthState(
        id=_id(),
        organization_id=org_id,
        owner_user_id=owner_user_id,
        session_fingerprint=session_fingerprint,
        state_hash=_state_hash(state),
        code_verifier_encrypted=encrypt_secret(verifier),
        redirect_uri=approved,
        expires_at=expires_at,
    )
    db.add(oauth_row)
    db.commit()

    query = build_google_authorize_query(
        client_id=client_id,
        redirect_uri=approved,
        state=state,
        code_challenge=challenge,
        scopes=_SCOPES,
    )
    authorization_url = f"{_GOOGLE_AUTH_URL}?{query}"

    return {
        "authorization_url": authorization_url,
        "state": state,
        "expires_at": expires_at.isoformat() + "Z",
        "status": "oauth_pending",
    }


def reconnect_start(
    db: Session,
    *,
    org_id: str,
    owner_user_id: str,
    session_fingerprint: str,
    redirect_uri: str,
) -> dict[str, Any]:
    return start_oauth(
        db,
        org_id=org_id,
        owner_user_id=owner_user_id,
        session_fingerprint=session_fingerprint,
        redirect_uri=redirect_uri,
    )


def _load_oauth_state(db: Session, *, state: str) -> GaCalendarOAuthState | None:
    return (
        db.query(GaCalendarOAuthState)
        .filter(GaCalendarOAuthState.state_hash == _state_hash(state))
        .one_or_none()
    )


def _oauth_failure(error_code: str) -> dict[str, Any]:
    return {"status": "Not connected", "error_code": error_code}


def complete_oauth(
    db: Session,
    *,
    org_id: str,
    owner_user_id: str,
    session_fingerprint: str,
    state: str,
    code: str,
    http_exchange: Callable[[str, str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not google_oauth_configured():
        return _oauth_failure("OAUTH_NOT_CONFIGURED")

    oauth_row = _load_oauth_state(db, state=state)
    if oauth_row is None:
        return _oauth_failure("OAUTH_STATE_INVALID")

    if oauth_row.organization_id != org_id:
        return _oauth_failure("TENANT_MISMATCH")

    if oauth_row.owner_user_id != owner_user_id:
        return _oauth_failure("OWNER_MISMATCH")

    if oauth_row.session_fingerprint != session_fingerprint:
        return _oauth_failure("SESSION_MISMATCH")

    if oauth_row.consumed_at is not None:
        return _oauth_failure("OAUTH_STATE_CONSUMED")

    if oauth_row.expires_at < _now():
        return _oauth_failure("OAUTH_STATE_EXPIRED")

    oauth_row.consumed_at = _now()
    db.add(oauth_row)
    db.flush()

    verifier = decrypt_secret(oauth_row.code_verifier_encrypted or "")
    redirect_uri = oauth_row.redirect_uri

    exchange = http_exchange
    if exchange is None:

        def exchange(c: str, v: str, r: str) -> dict[str, Any]:
            return exchange_authorization_code(code=c, code_verifier=v, redirect_uri=r)

    try:
        token_payload = exchange(code, verifier, redirect_uri)
    except OAuthHttpError as exc:
        db.commit()
        return _oauth_failure(exc.code)

    refresh = str(token_payload.get("refresh_token") or "").strip()
    access = str(token_payload.get("access_token") or "").strip()
    expires_in = int(token_payload.get("expires_in") or 0)
    scope_raw = str(token_payload.get("scope") or "")
    scopes = [s for s in scope_raw.split() if s] if scope_raw else list(_SCOPES)

    conn = (
        db.query(GaCalendarConnection)
        .filter(GaCalendarConnection.organization_id == org_id)
        .one_or_none()
    )
    if conn is None:
        conn = GaCalendarConnection(
            id=_id(),
            organization_id=org_id,
            owner_user_id=owner_user_id,
        )
        db.add(conn)
    else:
        conn.owner_user_id = owner_user_id

    conn.provider = "google"
    conn.scopes_json = scopes
    conn.access_token_encrypted = encrypt_secret(access) if access else None
    if expires_in > 0:
        conn.access_token_expires_at = _now() + timedelta(seconds=expires_in)
    else:
        conn.access_token_expires_at = None

    if refresh:
        conn.refresh_token_encrypted = encrypt_secret(refresh)
        conn.status = "connected"
        conn.calendar_id = conn.calendar_id or "primary"
        conn.last_error_code = None
        conn.connected_at = conn.connected_at or _now()
        conn.disconnected_at = None
    else:
        conn.status = "needs_reconnect"
        conn.last_error_code = "REFRESH_TOKEN_MISSING"
        if access:
            conn.refresh_token_encrypted = conn.refresh_token_encrypted
        else:
            conn.refresh_token_encrypted = None

    db.commit()

    if conn.status == "needs_reconnect":
        return {
            "status": "needs_reconnect",
            "error_code": "REFRESH_TOKEN_MISSING",
            "calendar_id": conn.calendar_id,
        }

    return {
        "status": "connected",
        "calendar_id": conn.calendar_id,
        "connected_at": conn.connected_at.isoformat() + "Z" if conn.connected_at else None,
        "last_error_code": None,
    }


def disconnect_calendar(db: Session, *, org_id: str, owner_user_id: str) -> dict[str, Any]:
    conn = (
        db.query(GaCalendarConnection)
        .filter(GaCalendarConnection.organization_id == org_id)
        .one_or_none()
    )
    if conn is None:
        return _not_connected_payload()

    if conn.owner_user_id != owner_user_id:
        return _oauth_failure("OWNER_MISMATCH")

    conn.refresh_token_encrypted = None
    conn.access_token_encrypted = None
    conn.access_token_expires_at = None
    conn.status = "not_connected"
    conn.disconnected_at = _now()
    conn.last_error_code = None
    db.commit()

    return _not_connected_payload(disconnected_at=conn.disconnected_at.isoformat() + "Z")