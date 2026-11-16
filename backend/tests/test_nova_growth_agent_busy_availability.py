"""External busy filtering wired into availability + booking paths."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

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

from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.models import (
    GaAppointmentService,
    GaAvailabilityRule,
    GaBusinessProfile,
    GaCalendarConnection,
    GaContact,
)
from app.core.nova.growth_agent.providers.credential_crypto import encrypt_secret
from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema
from app.core.nova.growth_agent.service import GrowthAgentService
from app.db.session import Base


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


def _seed(db, org: str = "org-busy") -> None:
    db.add(
        GaBusinessProfile(
            id=uuid4().hex,
            organization_id=org,
            owner_user_id="owner-1",
            business_name="Busy Biz",
            timezone="America/Chicago",
            activated=True,
            plan_code="starter",
            faqs_json=[],
            operating_hours_json={"mon_fri": "09:00-17:00"},
            escalation_settings_json={},
        )
    )
    svc_id = uuid4().hex
    db.add(
        GaAppointmentService(
            id=svc_id,
            organization_id=org,
            code="consult",
            name="Consult",
            duration_minutes=30,
            buffer_minutes=0,
            active=True,
        )
    )
    for dow in range(5):
        db.add(
            GaAvailabilityRule(
                id=uuid4().hex,
                organization_id=org,
                day_of_week=dow,
                start_minute=9 * 60,
                end_minute=12 * 60,
            )
        )
    db.add(
        GaContact(
            id="contact-busy",
            organization_id=org,
            display_name="Pat",
            lead_state="new",
            dedupe_fingerprint="fp-busy",
        )
    )
    db.commit()
    return svc_id


def _connect(db, org: str) -> None:
    db.add(
        GaCalendarConnection(
            id=uuid4().hex,
            organization_id=org,
            owner_user_id="owner-1",
            provider="google",
            status="connected",
            calendar_id="primary",
            refresh_token_encrypted=encrypt_secret("rt"),
            access_token_encrypted=encrypt_secret("at"),
            connected_at=datetime.utcnow(),
        )
    )
    db.commit()


def _next_weekday() -> str:
    day = datetime.now(timezone.utc).date() + timedelta(days=1)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day.isoformat()


def test_disconnected_state_skips_external_filter(db):
    org = "org-disc"
    _seed(db, org)
    svc = GrowthAgentService(db)
    day = _next_weekday()
    out = svc.list_availability(org, service_code="consult", day=day)
    assert out["external_calendar"]["state"] == "disconnected"
    assert out["slots"]


def test_provider_unavailable_when_connected_without_live_freebusy(db):
    org = "org-unavail"
    _seed(db, org)
    _connect(db, org)
    svc = GrowthAgentService(db)  # no injected provider → hard-off freebusy
    day = _next_weekday()
    out = svc.list_availability(org, service_code="consult", day=day)
    assert out["external_calendar"]["state"] == "provider_unavailable"
    # Internal slots still returned; booking remains internal-only
    assert out["slots"]


def test_available_busy_filters_slots_and_blocks_book(db):
    org = "org-filter"
    _seed(db, org)
    _connect(db, org)
    day = _next_weekday()

    def provider(_org, time_min, time_max):
        # Mark entire morning busy in UTC loosely — use first slot window
        start = datetime.strptime(day, "%Y-%m-%d").replace(
            hour=15, minute=0, tzinfo=timezone.utc
        )  # ~9am Chicago CST/CDT approx
        end = start + timedelta(hours=6)
        return {"state": "available", "busy": [(start, end)]}

    svc = GrowthAgentService(db, external_busy_provider=provider)
    out = svc.list_availability(org, service_code="consult", day=day)
    assert out["external_calendar"]["state"] == "available"
    # Most/all morning slots filtered
    unfiltered = GrowthAgentService(db, external_busy_provider=lambda *a: {"state": "disconnected", "busy": []})
    baseline = unfiltered.list_availability(org, service_code="consult", day=day)
    assert len(out["slots"]) < len(baseline["slots"])

    if baseline["slots"]:
        start = baseline["slots"][0]["starts_at_utc"]
        with pytest.raises(GrowthAgentError) as exc:
            svc.book_appointment(
                org,
                contact_id="contact-busy",
                service_code="consult",
                starts_at_utc=start,
                idempotency_key="busy-block-1",
                is_synthetic_demo=True,
            )
        assert exc.value.code == "EXTERNAL_BUSY_CONFLICT"
