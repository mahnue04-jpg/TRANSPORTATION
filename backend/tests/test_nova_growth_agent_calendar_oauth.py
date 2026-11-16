"""Google Calendar OAuth boundary: PKCE state, encrypted tokens, no token leakage."""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.nova.growth_agent.calendar_oauth import (
    complete_oauth,
    disconnect_calendar,
    get_calendar_connection_status,
    reconnect_start,
    start_oauth,
)
from app.core.nova.growth_agent.flags import google_oauth_configured
from app.core.nova.growth_agent.models import GaCalendarConnection, GaCalendarOAuthState
from app.core.nova.growth_agent.providers.credential_crypto import (
    clear_crypto_cache,
    decrypt_secret,
    encrypt_secret,
)
from app.core.nova.growth_agent.providers.google_oauth_http import (
    OAuthHttpError,
    exchange_authorization_code,
)
from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema
from app.db.session import Base

_APPROVED_REDIRECT = "https://app.example/oauth/google-calendar"
_FERNET_KEY = Fernet.generate_key().decode("ascii")


@pytest.fixture(autouse=True)
def oauth_env(monkeypatch):
    monkeypatch.setenv("NOVA_GA_GOOGLE_OAUTH_CLIENT_ID", "test-google-client-id")
    monkeypatch.setenv("NOVA_GA_GOOGLE_OAUTH_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.setenv("NOVA_GA_GOOGLE_OAUTH_REDIRECT_URI", _APPROVED_REDIRECT)
    monkeypatch.setenv("NOVA_GA_CREDENTIAL_ENCRYPTION_KEY", _FERNET_KEY)
    clear_crypto_cache()
    yield
    clear_crypto_cache()


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    ensure_growth_agent_schema(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _start(db, **overrides):
    defaults = dict(
        org_id="org-oauth-1",
        owner_user_id="owner-1",
        session_fingerprint="sess-fp-abc",
        redirect_uri=_APPROVED_REDIRECT,
    )
    defaults.update(overrides)
    return start_oauth(db, **defaults)


def test_missing_config_shows_not_connected(monkeypatch, db):
    monkeypatch.delenv("NOVA_GA_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    assert google_oauth_configured() is False
    payload = _start(db)
    assert payload["status"] == "Not connected"
    assert payload["error_code"] == "OAUTH_NOT_CONFIGURED"
    status = get_calendar_connection_status(db, org_id="org-oauth-1")
    assert status["status"] == "Not connected"
    assert status.get("error_code") == "OAUTH_NOT_CONFIGURED"


def test_redirect_mismatch_denied(db):
    payload = _start(db, redirect_uri="https://evil.example/callback")
    assert payload["status"] == "Not connected"
    assert payload["error_code"] == "REDIRECT_URI_MISMATCH"
    assert payload.get("authorization_url") is None


def test_pkce_verifier_stored_encrypted(db):
    payload = _start(db)
    assert payload["status"] == "oauth_pending"
    row = db.query(GaCalendarOAuthState).one()
    assert row.code_verifier_encrypted
    assert row.code_verifier_encrypted != decrypt_secret(row.code_verifier_encrypted)
    verifier = decrypt_secret(row.code_verifier_encrypted)
    assert 43 <= len(verifier) <= 128
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode(
        "ascii"
    )
    assert f"code_challenge={challenge}" in payload["authorization_url"]


def test_successful_injected_exchange_stores_encrypted_tokens(db):
    started = _start(db)
    state = started["state"]
    secret_refresh = "refresh-token-value-xyz"
    secret_access = "access-token-value-abc"

    def fake_exchange(code, verifier, redirect_uri):
        assert code == "auth-code-1"
        assert redirect_uri == _APPROVED_REDIRECT
        assert verifier == decrypt_secret(db.query(GaCalendarOAuthState).one().code_verifier_encrypted)
        return {
            "access_token": secret_access,
            "refresh_token": secret_refresh,
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/calendar.events",
        }

    result = complete_oauth(
        db,
        org_id="org-oauth-1",
        owner_user_id="owner-1",
        session_fingerprint="sess-fp-abc",
        state=state,
        code="auth-code-1",
        http_exchange=fake_exchange,
    )
    assert result["status"] == "connected"
    assert result["connected"] is True
    assert result["calendar_id"] == "primary"

    conn = db.query(GaCalendarConnection).one()
    assert decrypt_secret(conn.refresh_token_encrypted) == secret_refresh
    assert decrypt_secret(conn.access_token_encrypted) == secret_access
    assert conn.status == "connected"
    status = get_calendar_connection_status(db, org_id="org-oauth-1")
    assert status["connected"] is True
    assert status["status"] == "connected"


def test_tokens_never_in_status_or_safe_errors(db):
    started = _start(db)

    def fake_exchange(code, verifier, redirect_uri):
        return {
            "access_token": "super-secret-access",
            "refresh_token": "super-secret-refresh",
            "expires_in": 60,
        }

    complete_oauth(
        db,
        org_id="org-oauth-1",
        owner_user_id="owner-1",
        session_fingerprint="sess-fp-abc",
        state=started["state"],
        code="c1",
        http_exchange=fake_exchange,
    )
    status = get_calendar_connection_status(db, org_id="org-oauth-1")
    blob = repr(status)
    assert "super-secret-access" not in blob
    assert "super-secret-refresh" not in blob
    assert "refresh_token" not in status
    assert "access_token" not in status

    with pytest.raises(OAuthHttpError) as exc:
        exchange_authorization_code(code="x", code_verifier="y", redirect_uri=_APPROVED_REDIRECT)
    assert exc.value.code == "OAUTH_LIVE_DISABLED"
    assert "super-secret" not in str(exc.value)


def test_oauth_http_enabled_flag_allows_live_gate_without_calendar_writes(monkeypatch):
    """Token HTTP may be opted in without REAL_CALENDAR_WRITE."""
    from app.core.nova.growth_agent import flags
    from app.core.nova.growth_agent.providers import google_oauth_http as goh

    assert flags.REAL_CALENDAR_WRITE is False
    monkeypatch.setenv("NOVA_GROWTH_AGENT_ENABLED", "true")
    monkeypatch.setenv("NOVA_GA_GOOGLE_OAUTH_HTTP_ENABLED", "true")
    # Credentials already set by module fixtures / env in this file
    assert flags.google_oauth_http_enabled() is True
    assert goh._live_allowed(http_client=None) is True
    monkeypatch.setenv("NOVA_GA_GOOGLE_OAUTH_HTTP_ENABLED", "false")
    assert goh._live_allowed(http_client=None) is False


def test_state_single_use(db):
    started = _start(db)
    state = started["state"]

    def fake_exchange(code, verifier, redirect_uri):
        return {"access_token": "a1", "refresh_token": "r1", "expires_in": 10}

    complete_oauth(
        db,
        org_id="org-oauth-1",
        owner_user_id="owner-1",
        session_fingerprint="sess-fp-abc",
        state=state,
        code="c1",
        http_exchange=fake_exchange,
    )
    again = complete_oauth(
        db,
        org_id="org-oauth-1",
        owner_user_id="owner-1",
        session_fingerprint="sess-fp-abc",
        state=state,
        code="c2",
        http_exchange=fake_exchange,
    )
    assert again["error_code"] == "OAUTH_STATE_CONSUMED"


def test_session_mismatch(db):
    started = _start(db)
    out = complete_oauth(
        db,
        org_id="org-oauth-1",
        owner_user_id="owner-1",
        session_fingerprint="wrong-fingerprint",
        state=started["state"],
        code="c1",
        http_exchange=lambda *a: {"access_token": "a", "refresh_token": "r", "expires_in": 1},
    )
    assert out["error_code"] == "SESSION_MISMATCH"


def test_tenant_mismatch(db):
    started = _start(db)
    out = complete_oauth(
        db,
        org_id="org-other",
        owner_user_id="owner-1",
        session_fingerprint="sess-fp-abc",
        state=started["state"],
        code="c1",
        http_exchange=lambda *a: {"access_token": "a", "refresh_token": "r", "expires_in": 1},
    )
    assert out["error_code"] == "TENANT_MISMATCH"


def test_expired_state(db):
    started = _start(db)
    row = db.query(GaCalendarOAuthState).one()
    row.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    out = complete_oauth(
        db,
        org_id="org-oauth-1",
        owner_user_id="owner-1",
        session_fingerprint="sess-fp-abc",
        state=started["state"],
        code="c1",
        http_exchange=lambda *a: {"access_token": "a", "refresh_token": "r", "expires_in": 1},
    )
    assert out["error_code"] == "OAUTH_STATE_EXPIRED"


def test_disconnect_clears_tokens(db):
    started = _start(db)
    complete_oauth(
        db,
        org_id="org-oauth-1",
        owner_user_id="owner-1",
        session_fingerprint="sess-fp-abc",
        state=started["state"],
        code="c1",
        http_exchange=lambda *a: {"access_token": "a", "refresh_token": "r", "expires_in": 1},
    )
    disconnect_calendar(db, org_id="org-oauth-1", owner_user_id="owner-1")
    conn = db.query(GaCalendarConnection).one()
    assert conn.refresh_token_encrypted is None
    assert conn.access_token_encrypted is None
    assert conn.status == "not_connected"
    assert conn.disconnected_at is not None
    status = get_calendar_connection_status(db, org_id="org-oauth-1")
    assert status["status"] == "Not connected"
    assert status["connected"] is False


def test_missing_refresh_token_needs_reconnect(db):
    started = _start(db)
    out = complete_oauth(
        db,
        org_id="org-oauth-1",
        owner_user_id="owner-1",
        session_fingerprint="sess-fp-abc",
        state=started["state"],
        code="c1",
        http_exchange=lambda *a: {"access_token": "only-access", "expires_in": 30},
    )
    assert out["status"] == "needs_reconnect"
    assert out["error_code"] == "REFRESH_TOKEN_MISSING"


def test_reconnect_start_matches_start(db):
    a = reconnect_start(
        db,
        org_id="org-r",
        owner_user_id="owner-r",
        session_fingerprint="fp-r",
        redirect_uri=_APPROVED_REDIRECT,
    )
    b = start_oauth(
        db,
        org_id="org-r2",
        owner_user_id="owner-r",
        session_fingerprint="fp-r",
        redirect_uri=_APPROVED_REDIRECT,
    )
    assert a["status"] == b["status"] == "oauth_pending"
    assert "authorization_url" in a and "state" in a


def test_injected_http_client_exchange():
    mock = Mock()
    mock.post.return_value = Mock(
        json=lambda: {"access_token": "from-mock", "refresh_token": "from-mock-r", "expires_in": 10}
    )
    payload = exchange_authorization_code(
        code="code",
        code_verifier="verifier-long-enough-for-pkce-test-value",
        redirect_uri=_APPROVED_REDIRECT,
        http_client=mock,
    )
    assert payload["access_token"] == "from-mock"
    mock.post.assert_called_once()