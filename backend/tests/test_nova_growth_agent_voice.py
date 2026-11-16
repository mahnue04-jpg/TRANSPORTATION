"""Inbound voice: Twilio signature, dedupe, tenant mapping, session gates, simulator labels."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"
os.environ["NOVA_GROWTH_AGENT_VOICE_SIMULATOR"] = "true"

from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.models import GaVoiceAgentMapping, GaVoiceSession
from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema
from app.core.nova.growth_agent.voice.inbound import (
    GrowthVoiceOps,
    assert_appointment_authorized,
    get_or_create_session,
    phone_identity_hash,
    process_inbound_event,
    receive_inbound_webhook,
    resolve_tenant_from_called_number,
)
from app.core.nova.growth_agent.voice.simulator import (
    SIMULATOR_LABEL,
    craft_signed_simulator_webhook,
    run_labeled_simulator_journey,
)
from app.core.nova.growth_agent.voice.twilio_signature import (
    SIMULATOR_AUTH,
    TwilioSignatureError,
    compute_twilio_signature,
    validate_twilio_signature,
)
from app.db.session import Base
from app.helpers import uuid4


WEBHOOK_URL = "https://example.test/voice/inbound"


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


class MockVoiceOps:
    def __init__(self, org_id: str) -> None:
        self.org_id = org_id
        self.calls: list[tuple[str, dict]] = []

    def faq_answer(self, *, organization_id: str, question: str) -> dict[str, Any]:
        self.calls.append(("faq_answer", {"question": question}))
        return {"grounded": True, "answer": "9-5"}

    def capture_lead(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("capture_lead", kwargs))
        return {"contact_id": "contact-1"}

    def check_availability(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("check_availability", kwargs))
        return {"slots": ["2026-11-17T15:00:00Z"]}

    def book(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("book", kwargs))
        return {"appointment_id": "appt-authorized-1", "status": "confirmed"}

    def reschedule(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("reschedule", kwargs))
        return {"appointment_id": kwargs["appointment_id"], "status": "rescheduled"}

    def cancel(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("cancel", kwargs))
        return {"appointment_id": kwargs["appointment_id"], "status": "cancelled"}

    def create_handoff(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_handoff", kwargs))
        return {"handoff_id": "handoff-1"}


def _mapping(
    db,
    *,
    org: str,
    number: str = "+15555550111",
    daily_limit: int = 50,
    kill_switch: bool = False,
    active: bool = True,
) -> GaVoiceAgentMapping:
    row = GaVoiceAgentMapping(
        id=uuid4(),
        organization_id=org,
        provider="twilio",
        external_number=number,
        daily_call_limit=daily_limit,
        kill_switch=kill_switch,
        active=active,
    )
    db.add(row)
    db.commit()
    return row


def _signed_params(url: str, params: dict, token: str = "test-auth-token") -> str:
    return compute_twilio_signature(url=url, params=params, auth_token=token)


def test_forged_signature_rejected():
    params = {"To": "+15555550111", "From": "+15555550999", "CallSid": "CA forged"}
    good = _signed_params(WEBHOOK_URL, params)
    with pytest.raises(TwilioSignatureError) as exc:
        validate_twilio_signature(
            url=WEBHOOK_URL,
            params=params,
            signature_header=good,
            auth_token="wrong-token",
        )
    assert exc.value.code == "VOICE_SIGNATURE_INVALID"


def test_timestamp_skew_rejected():
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    params = {"To": "+1", "Timestamp": old}
    sig = _signed_params(WEBHOOK_URL, params)
    with pytest.raises(TwilioSignatureError) as exc:
        validate_twilio_signature(url=WEBHOOK_URL, params=params, signature_header=sig, auth_token="t")
    assert exc.value.code == "VOICE_TIMESTAMP_SKEW"


def test_replay_duplicate_rejected(db):
    org = "org-voice-dedupe"
    _mapping(db, org=org)
    ops = MockVoiceOps(org)
    params = {
        "To": "+15555550111",
        "From": "+15555550999",
        "CallSid": "CA-dedupe-1",
        "event_type": "faq_answer",
        "event_id": "evt-dedupe-1",
        "question": "hours?",
    }
    sig = _signed_params(WEBHOOK_URL, params)
    first = receive_inbound_webhook(
        db,
        url=WEBHOOK_URL,
        params=params,
        signature_header=sig,
        auth_token="test-auth-token",
        growth_ops=ops,
    )
    assert first["status"] == "processed"

    second = receive_inbound_webhook(
        db,
        url=WEBHOOK_URL,
        params=params,
        signature_header=sig,
        auth_token="test-auth-token",
        growth_ops=ops,
    )
    assert second["status"] == "duplicate"
    assert len(ops.calls) == 1


def test_cross_tenant_number_mapping(db):
    org_real = "org-mapping-real"
    _mapping(db, org=org_real, number="+15555550111")
    row = resolve_tenant_from_called_number(db, provider="twilio", called_number="+15555550111")
    assert row is not None
    assert row.organization_id == org_real

    ops = MockVoiceOps(org_real)
    params = {
        "To": "+15555550111",
        "From": "+15555550999",
        "CallSid": "CA-tenant",
        "event_type": "faq_answer",
        "event_id": "evt-tenant-1",
        "organization_id": "org-attacker",
        "question": "hours?",
    }
    sig = _signed_params(WEBHOOK_URL, params)
    with pytest.raises(GrowthAgentError) as exc:
        receive_inbound_webhook(
            db,
            url=WEBHOOK_URL,
            params=params,
            signature_header=sig,
            auth_token="test-auth-token",
            growth_ops=ops,
        )
    assert exc.value.code == "VOICE_TENANT_MISMATCH"


def test_cross_tenant_resolves_without_spoofed_org(db):
    org_real = "org-mapping-clean"
    _mapping(db, org=org_real)
    ops = MockVoiceOps(org_real)
    params = {
        "To": "+15555550111",
        "From": "+15555550999",
        "CallSid": "CA-clean",
        "event_type": "faq_answer",
        "event_id": "evt-clean-1",
        "question": "hours?",
    }
    sig = _signed_params(WEBHOOK_URL, params)
    out = receive_inbound_webhook(
        db,
        url=WEBHOOK_URL,
        params=params,
        signature_header=sig,
        auth_token="test-auth-token",
        growth_ops=ops,
    )
    assert out["organization_id"] == org_real


def test_kill_switch_blocks(db):
    org = "org-kill"
    _mapping(db, org=org, kill_switch=True)
    ops = MockVoiceOps(org)
    params = {
        "To": "+15555550111",
        "event_type": "faq_answer",
        "event_id": "evt-kill-1",
        "CallSid": "CA-kill",
    }
    sig = _signed_params(WEBHOOK_URL, params)
    with pytest.raises(GrowthAgentError) as exc:
        receive_inbound_webhook(
            db,
            url=WEBHOOK_URL,
            params=params,
            signature_header=sig,
            auth_token="test-auth-token",
            growth_ops=ops,
        )
    assert exc.value.code == "VOICE_KILL_SWITCH"


def test_daily_usage_limit_blocks(db):
    org = "org-limit"
    _mapping(db, org=org, daily_limit=1)
    ops = MockVoiceOps(org)
    for idx in range(2):
        params = {
            "To": "+15555550111",
            "event_type": "faq_answer",
            "event_id": f"evt-limit-{idx}",
            "CallSid": f"CA-limit-{idx}",
        }
        sig = _signed_params(WEBHOOK_URL, params)
        if idx == 0:
            receive_inbound_webhook(
                db,
                url=WEBHOOK_URL,
                params=params,
                signature_header=sig,
                auth_token="test-auth-token",
                growth_ops=ops,
            )
        else:
            with pytest.raises(GrowthAgentError) as exc:
                receive_inbound_webhook(
                    db,
                    url=WEBHOOK_URL,
                    params=params,
                    signature_header=sig,
                    auth_token="test-auth-token",
                    growth_ops=ops,
                )
            assert exc.value.code == "VOICE_DAILY_LIMIT"


def test_unauthorized_appointment_change_denied(db):
    org = "org-unauth-appt"
    mapping = _mapping(db, org=org)
    ops = MockVoiceOps(org)
    session = get_or_create_session(
        db,
        organization_id=org,
        provider="twilio",
        call_sid="CA-unauth",
        caller_phone="+15555550999",
    )
    session.authorized_appointment_ids_json = []
    db.commit()

    with pytest.raises(GrowthAgentError) as exc:
        process_inbound_event(
            db,
            mapping=mapping,
            session=session,
            event_type="cancel",
            payload={"appointment_id": "appt-other"},
            growth_ops=ops,
        )
    assert exc.value.code == "VOICE_APPOINTMENT_UNAUTHORIZED"


def test_authorized_book_reschedule_cancel_via_injected_ops(db):
    org = "org-auth-flow"
    mapping = _mapping(db, org=org)
    ops = MockVoiceOps(org)
    session = get_or_create_session(
        db,
        organization_id=org,
        provider="twilio",
        call_sid="CA-auth-flow",
        caller_phone="+15555550999",
    )

    book_out = process_inbound_event(
        db,
        mapping=mapping,
        session=session,
        event_type="book",
        payload={"service_code": "consult", "slot_start": "2026-11-17T15:00:00Z"},
        growth_ops=ops,
    )
    assert book_out["result"]["appointment_id"] == "appt-authorized-1"
    db.refresh(session)
    assert "appt-authorized-1" in session.authorized_appointment_ids_json

    process_inbound_event(
        db,
        mapping=mapping,
        session=session,
        event_type="reschedule",
        payload={"appointment_id": "appt-authorized-1", "slot_start": "2026-11-18T15:00:00Z"},
        growth_ops=ops,
    )
    process_inbound_event(
        db,
        mapping=mapping,
        session=session,
        event_type="cancel",
        payload={"appointment_id": "appt-authorized-1"},
        growth_ops=ops,
    )
    assert [c[0] for c in ops.calls] == ["book", "reschedule", "cancel"]


def test_simulator_labeled_and_signed(db):
    org = "org-sim"
    _mapping(db, org=org, number="+15555550222")
    crafted = craft_signed_simulator_webhook(
        url=WEBHOOK_URL,
        to_number="+15555550222",
        event_type="faq_answer",
        extra={"question": "hours?"},
    )
    assert crafted["meta"]["simulated"] is True
    assert crafted["params"]["meta"]["simulated"] is True
    assert crafted["params"]["simulated"] is True
    assert crafted["auth_token"] == SIMULATOR_AUTH

    ops = MockVoiceOps(org)
    journey = run_labeled_simulator_journey(
        db,
        url=WEBHOOK_URL,
        to_number="+15555550222",
        growth_ops=ops,
        steps=[
            {"event_type": "faq_answer", "question": "hours?", "event_id": "sim-step-1"},
            {"event_type": "book", "service_code": "consult", "slot_start": "2026-11-17T16:00:00Z", "event_id": "sim-step-2"},
        ],
    )
    assert all(step["meta"]["simulated"] is True for step in journey)
    assert journey[0]["meta"]["label"] == SIMULATOR_LABEL
    assert journey[0]["status"] == "processed"