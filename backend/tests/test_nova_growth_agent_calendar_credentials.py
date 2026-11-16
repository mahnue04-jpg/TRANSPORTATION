"""Calendar credential provider + select calendar — no live Google."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"
os.environ["NOVA_GA_CREDENTIAL_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["NOVA_GA_GOOGLE_OAUTH_CLIENT_ID"] = "test-client"
os.environ["NOVA_GA_GOOGLE_OAUTH_CLIENT_SECRET"] = "test-secret"
os.environ["NOVA_GA_GOOGLE_OAUTH_REDIRECT_URI"] = "https://example.invalid/oauth/callback"

from app.core.nova.growth_agent import calendar_credentials as creds
from app.core.nova.growth_agent.models import GaCalendarConnection
from app.core.nova.growth_agent.providers.credential_crypto import encrypt_secret, clear_crypto_cache
from app.core.nova.growth_agent.providers.google_oauth_http import OAuthHttpError
from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema
from app.db.session import Base


@pytest.fixture(autouse=True)
def _crypto():
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


def _conn(db, org="org-cred", *, status="connected", refresh=True, access=True):
    row = GaCalendarConnection(
        id="conn-1",
        organization_id=org,
        owner_user_id="owner-1",
        provider="google",
        status=status,
        calendar_id="primary",
        calendar_summary="Primary",
        refresh_token_encrypted=encrypt_secret("refresh-secret") if refresh else None,
        access_token_encrypted=encrypt_secret("access-secret") if access else None,
        access_token_expires_at=datetime.utcnow() + timedelta(hours=1) if access else None,
        connected_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    return row


def test_credential_health_never_leaks_tokens(db):
    _conn(db)
    health = creds.credential_health(creds.get_connection(db, org_id="org-cred"))
    blob = repr(health)
    assert "refresh-secret" not in blob
    assert "access-secret" not in blob
    assert health["state"] == "healthy"
    assert health["has_refresh_credential"] is True


def test_resolve_access_token_uses_cached_access(db):
    _conn(db)
    token = creds.resolve_access_token(db, org_id="org-cred")
    assert token == "access-secret"


def test_resolve_refreshes_when_expired(db):
    row = _conn(db)
    row.access_token_expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    class FakeHttp:
        def post(self, url, *, data, timeout=15.0):
            class R:
                def json(self_inner):
                    return {"access_token": "new-access", "expires_in": 3600}

            return R()

    token = creds.resolve_access_token(db, org_id="org-cred", http_client=FakeHttp())
    assert token == "new-access"
    health = creds.credential_health(creds.get_connection(db, org_id="org-cred"))
    assert health["has_access_credential"] is True


def test_select_calendar(db):
    _conn(db)
    out = creds.select_calendar(
        db,
        org_id="org-cred",
        owner_user_id="owner-1",
        calendar_id="cal-test@group.calendar.google.com",
        calendar_summary="Pilot test",
    )
    assert out["connected"] is True
    assert out["calendar_id"] == "cal-test@group.calendar.google.com"
    assert out["calendar_summary"] == "Pilot test"


def test_access_token_provider_for_transport(db):
    _conn(db)
    provider = creds.access_token_provider_for(db)
    assert provider("org-cred") == "access-secret"
    with pytest.raises(OAuthHttpError):
        provider("org-missing")
