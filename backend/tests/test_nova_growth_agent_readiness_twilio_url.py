"""Readiness snapshot + Twilio public URL reconstruction."""

from __future__ import annotations

import os
from datetime import datetime

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"
os.environ.setdefault("TESTING", "true")
os.environ["NOVA_GA_CREDENTIAL_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["NOVA_GA_GOOGLE_OAUTH_CLIENT_ID"] = "test-client"
os.environ["NOVA_GA_GOOGLE_OAUTH_CLIENT_SECRET"] = "test-secret"
os.environ["NOVA_GA_GOOGLE_OAUTH_REDIRECT_URI"] = "https://example.invalid/oauth/callback"

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.growth_agent.readiness import build_readiness
from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema
from app.core.nova.growth_agent.voice.twilio_signature import (
    compute_twilio_signature,
    public_request_url,
    validate_twilio_signature,
)
from app.db.session import Base
from app.main import app


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


@pytest.fixture()
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def test_public_request_url_prefers_amicor_public_and_forwarded_headers(monkeypatch):
    monkeypatch.setenv("AMICOR_PUBLIC_URL", "https://growth.example.invalid")
    url = public_request_url(
        request_url="http://127.0.0.1:8000/api/nova/growth-agent/voice/twilio/webhook?x=1",
        headers={"host": "127.0.0.1:8000"},
    )
    assert url.startswith("https://growth.example.invalid/")
    assert "webhook" in url
    assert "x=1" in url

    monkeypatch.delenv("AMICOR_PUBLIC_URL", raising=False)
    url2 = public_request_url(
        request_url="http://10.0.0.5/api/hook",
        headers={
            "x-forwarded-proto": "https",
            "x-forwarded-host": "public.example.invalid",
        },
        public_base=None,
    )
    assert url2 == "https://public.example.invalid/api/hook"


def test_readiness_distinguishes_missing_config_empty_queue(db, monkeypatch):
    monkeypatch.delenv("NOVA_GA_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    snap = build_readiness(db, org_id="org-ready-1")
    assert snap["calendar"]["configuration"]["state"] == "missing_config"
    assert snap["calendar"]["connection_state"] == "missing_config"
    assert snap["twilio"]["mode"] == "simulator"
    assert snap["sync_queue"]["state"] == "empty"
    assert "not a failure" in snap["sync_queue"]["label"].lower()
    assert snap["notifications"]["honesty"]["provider_accepted_is_not_inbox_receipt"] is True
    assert snap["voice"]["webhook"]["live_voice"] is False
    assert snap["pilot_live_ready"] is False
    blob = repr(snap)
    assert "refresh_token" not in blob
    assert "access_token_encrypted" not in blob
    assert "Bearer " not in blob
    # Field names like access_expires_at are OK; raw token material is not.
    assert "ya29." not in blob


def test_readiness_http_owner_only(client: TestClient):
    login = client.post(
        "/api/auth/login",
        json={"email": "admin@amicor.local", "password": SEED_PASSWORD},
    )
    assert login.status_code == 200
    token = login.json().get("access_token") or login.json().get("token")
    headers = {"Authorization": f"Bearer {token}"}
    res = client.get("/api/nova/growth-agent/receptionist/readiness", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert "calendar" in body and "sync_queue" in body and "voice" in body
    assert body["honesty"]["fake_provider_is_not_real_google_acceptance"] is True
    assert "rt-secret" not in res.text.lower()

    denied = client.get("/api/nova/growth-agent/receptionist/readiness")
    assert denied.status_code in {401, 403}


def test_unsigned_simulated_flag_still_requires_signature():
    params = {"To": "+15555550100", "From": "+1", "CallSid": "CA1", "simulated": "true"}
    with pytest.raises(Exception) as exc:
        validate_twilio_signature(
            url="https://example.invalid/hook",
            params=params,
            signature_header=None,
            auth_token="real-token",
            simulator_mode=False,
        )
    assert "SIGNATURE" in str(exc.value.code).upper() or "signature" in str(exc.value).lower()

    sig = compute_twilio_signature(
        url="https://example.invalid/hook", params=params, auth_token="real-token"
    )
    validate_twilio_signature(
        url="https://example.invalid/hook",
        params=params,
        signature_header=sig,
        auth_token="real-token",
        simulator_mode=False,
    )
