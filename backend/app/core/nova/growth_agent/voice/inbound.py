"""Inbound Twilio voice webhook handling — tenant mapping, dedupe, session gates."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.models import (
    GaContactIdentity,
    GaVoiceAgentMapping,
    GaVoiceSession,
    GaVoiceWebhookEvent,
)
from app.core.nova.growth_agent.redact import redact_mapping
from app.core.nova.growth_agent.voice.twilio_signature import validate_twilio_signature
from app.helpers import now, uuid4

PROVIDER_TWILIO = "twilio"
_ALLOWED_EVENT_TYPES = frozenset(
    {
        "faq_answer",
        "capture_lead",
        "check_availability",
        "book",
        "reschedule",
        "cancel",
        "create_handoff",
    }
)
_MUTATION_EVENT_TYPES = frozenset({"reschedule", "cancel"})


@runtime_checkable
class GrowthVoiceOps(Protocol):
    """Injected growth operations so voice tests avoid GrowthAgentService."""

    def faq_answer(self, *, organization_id: str, question: str) -> dict[str, Any]: ...

    def capture_lead(
        self,
        *,
        organization_id: str,
        phone: str | None,
        name: str | None,
        notes: str | None,
    ) -> dict[str, Any]: ...

    def check_availability(
        self,
        *,
        organization_id: str,
        service_code: str | None,
    ) -> dict[str, Any]: ...

    def book(
        self,
        *,
        organization_id: str,
        contact_id: str | None,
        service_code: str,
        slot_start: str,
    ) -> dict[str, Any]: ...

    def reschedule(
        self,
        *,
        organization_id: str,
        appointment_id: str,
        slot_start: str,
    ) -> dict[str, Any]: ...

    def cancel(
        self,
        *,
        organization_id: str,
        appointment_id: str,
    ) -> dict[str, Any]: ...

    def create_handoff(
        self,
        *,
        organization_id: str,
        contact_id: str | None,
        reason: str,
        summary: str,
    ) -> dict[str, Any]: ...


def normalize_e164(phone: str | None) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        return "+1" + digits
    if digits.startswith("1") and len(digits) == 11:
        return "+" + digits
    if str(phone or "").strip().startswith("+"):
        return str(phone).strip()
    return "+" + digits if digits else ""


def phone_identity_hash(phone: str) -> str:
    normalized = re.sub(r"\D", "", phone or "")
    return hashlib.sha256(f"phone:{normalized}".encode("utf-8")).hexdigest()


def resolve_tenant_from_called_number(
    db: Session,
    *,
    provider: str,
    called_number: str,
) -> GaVoiceAgentMapping | None:
    """Map dialed number → tenant via server-controlled rows (never webhook org ids)."""
    raw = str(called_number or "").strip()
    number = normalize_e164(called_number)
    if not number and not raw:
        return None
    candidates = []
    for candidate in (number, raw):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        row = (
            db.query(GaVoiceAgentMapping)
            .filter_by(provider=provider, external_number=candidate)
            .one_or_none()
        )
        if row is not None:
            return row
    return None


def _utc_start_of_day() -> datetime:
    today = datetime.now(timezone.utc).date()
    return datetime(today.year, today.month, today.day, tzinfo=timezone.utc).replace(tzinfo=None)


def count_calls_today(db: Session, *, organization_id: str, provider: str) -> int:
    start = _utc_start_of_day()
    q = (
        db.query(func.count(GaVoiceWebhookEvent.id))
        .filter(
            GaVoiceWebhookEvent.organization_id == organization_id,
            GaVoiceWebhookEvent.provider == provider,
            GaVoiceWebhookEvent.status.in_(("accepted", "processed")),
            GaVoiceWebhookEvent.created_at >= start,
        )
    )
    return int(q.scalar() or 0)


def assert_mapping_allows_inbound(mapping: GaVoiceAgentMapping, db: Session) -> None:
    if not mapping.active:
        raise GrowthAgentError("VOICE_MAPPING_INACTIVE", "Voice line is inactive", http_status=403)
    if mapping.kill_switch:
        raise GrowthAgentError("VOICE_KILL_SWITCH", "Voice receptionist kill switch is on", http_status=503)
    if count_calls_today(db, organization_id=mapping.organization_id, provider=mapping.provider) >= int(
        mapping.daily_call_limit
    ):
        raise GrowthAgentError("VOICE_DAILY_LIMIT", "Daily voice call limit exceeded", http_status=429)


def extract_event_id(provider: str, payload: dict[str, Any]) -> str:
    if payload.get("event_id"):
        return str(payload["event_id"])
    call_sid = str(payload.get("CallSid") or payload.get("call_sid") or "unknown")
    seq = payload.get("SequenceNumber") or payload.get("CallStatus") or "0"
    return f"{provider}:{call_sid}:{seq}"


def extract_call_sid(payload: dict[str, Any]) -> str:
    return str(payload.get("CallSid") or payload.get("call_sid") or payload.get("event_id") or uuid4())


def record_webhook_event(
    db: Session,
    *,
    organization_id: str,
    provider: str,
    event_id: str,
    event_type: str,
    call_sid: str | None,
    payload: dict[str, Any],
    signature_valid: bool,
) -> tuple[GaVoiceWebhookEvent, str]:
    """Persist webhook; dedupe on (provider, event_id).

    Returns ``(row, status)`` where status is ``duplicate`` or ``accepted``.

    Primary replay guard: unique (provider, event_id). Timestamp skew is secondary
    (see ``twilio_signature.check_timestamp_replay_skew``).
    """
    existing = (
        db.query(GaVoiceWebhookEvent)
        .filter_by(provider=provider, event_id=event_id)
        .one_or_none()
    )
    if existing is not None:
        return existing, "duplicate"

    row = GaVoiceWebhookEvent(
        id=uuid4(),
        organization_id=organization_id,
        provider=provider,
        event_id=event_id,
        event_type=event_type,
        call_sid=call_sid,
        status="accepted",
        signature_valid=signature_valid,
        payload_redacted_json=redact_mapping(payload),
        result_json={},
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        dup = (
            db.query(GaVoiceWebhookEvent)
            .filter_by(provider=provider, event_id=event_id)
            .one()
        )
        return dup, "duplicate"
    return row, "accepted"


def get_or_create_session(
    db: Session,
    *,
    organization_id: str,
    provider: str,
    call_sid: str,
    caller_phone: str | None,
) -> GaVoiceSession:
    session = (
        db.query(GaVoiceSession)
        .filter_by(provider=provider, call_sid=call_sid)
        .one_or_none()
    )
    fingerprint = phone_identity_hash(caller_phone) if caller_phone else None
    if session:
        if fingerprint and not session.caller_fingerprint:
            session.caller_fingerprint = fingerprint
        return session

    session = GaVoiceSession(
        id=uuid4(),
        organization_id=organization_id,
        provider=provider,
        call_sid=call_sid,
        caller_fingerprint=fingerprint,
        status="active",
        authorized_appointment_ids_json=[],
        meta_json={},
    )
    db.add(session)
    db.flush()
    return session


def _contact_matches_caller(db: Session, session: GaVoiceSession) -> bool:
    if not session.caller_fingerprint or not session.contact_id:
        return False
    ident = (
        db.query(GaContactIdentity)
        .filter_by(
            organization_id=session.organization_id,
            contact_id=session.contact_id,
            channel="phone",
        )
        .one_or_none()
    )
    if ident is None:
        return False
    return hmac_compare(ident.external_id, session.caller_fingerprint)


def hmac_compare(a: str, b: str) -> bool:
    import hmac as _hmac

    return _hmac.compare_digest(str(a), str(b))


def assert_appointment_authorized(
    db: Session,
    session: GaVoiceSession,
    appointment_id: str,
) -> None:
    """Authorize appointment mutations only via session-bound ownership.

    Rules (all required):
    1. Appointment must exist in the session's organization (tenant isolation).
    2. Appointment id must already be in session.authorized_appointment_ids_json
       (e.g. from a book in this call) OR appointment.contact_id must equal
       session.contact_id with a verified caller fingerprint match.

    Caller recognition alone must never authorize an arbitrary appointment ID.
    """
    from app.core.nova.growth_agent.models import GaAppointment

    appt_id = (appointment_id or "").strip()
    if not appt_id:
        raise GrowthAgentError(
            "VOICE_APPOINTMENT_UNAUTHORIZED",
            "Appointment id required",
            http_status=403,
        )

    appt = (
        db.query(GaAppointment)
        .filter_by(id=appt_id, organization_id=session.organization_id)
        .one_or_none()
    )
    if appt is None:
        raise GrowthAgentError(
            "VOICE_APPOINTMENT_UNAUTHORIZED",
            "Appointment not found for this tenant",
            http_status=403,
        )

    authorized = list(session.authorized_appointment_ids_json or [])
    if appt_id in authorized:
        return

    # Contact-bound path: session must already be linked to this contact AND
    # the caller fingerprint must match that contact's phone identity.
    if (
        session.contact_id
        and appt.contact_id == session.contact_id
        and _contact_matches_caller(db, session)
    ):
        authorized.append(appt_id)
        session.authorized_appointment_ids_json = authorized
        db.flush()
        return

    raise GrowthAgentError(
        "VOICE_APPOINTMENT_UNAUTHORIZED",
        "Caller is not authorized to change this appointment",
        http_status=403,
    )


def process_inbound_event(
    db: Session,
    *,
    mapping: GaVoiceAgentMapping,
    session: GaVoiceSession,
    event_type: str,
    payload: dict[str, Any],
    growth_ops: GrowthVoiceOps,
) -> dict[str, Any]:
    """Dispatch a single labeled intent through injected growth ops only."""
    action = (event_type or "").strip().lower()
    if action not in _ALLOWED_EVENT_TYPES:
        raise GrowthAgentError("VOICE_EVENT_UNSUPPORTED", f"Unsupported voice event: {action}")

    org_id = mapping.organization_id
    meta = {"simulated": bool((payload.get("meta") or {}).get("simulated"))}

    if action == "faq_answer":
        question = str(payload.get("question") or payload.get("SpeechResult") or "")
        result = growth_ops.faq_answer(organization_id=org_id, question=question)
    elif action == "capture_lead":
        result = growth_ops.capture_lead(
            organization_id=org_id,
            phone=payload.get("From") or payload.get("caller_phone"),
            name=payload.get("caller_name"),
            notes=payload.get("notes"),
        )
        contact_id = result.get("contact_id")
        if contact_id:
            session.contact_id = str(contact_id)
    elif action == "check_availability":
        result = growth_ops.check_availability(
            organization_id=org_id,
            service_code=payload.get("service_code"),
        )
    elif action == "book":
        result = growth_ops.book(
            organization_id=org_id,
            contact_id=session.contact_id,
            service_code=str(payload.get("service_code") or "consult"),
            slot_start=str(payload.get("slot_start") or ""),
        )
        appt_id = result.get("appointment_id")
        if appt_id:
            ids = list(session.authorized_appointment_ids_json or [])
            if appt_id not in ids:
                ids.append(str(appt_id))
            session.authorized_appointment_ids_json = ids
    elif action == "reschedule":
        appointment_id = str(payload.get("appointment_id") or "")
        assert_appointment_authorized(db, session, appointment_id)
        result = growth_ops.reschedule(
            organization_id=org_id,
            appointment_id=appointment_id,
            slot_start=str(payload.get("slot_start") or ""),
        )
    elif action == "cancel":
        appointment_id = str(payload.get("appointment_id") or "")
        assert_appointment_authorized(db, session, appointment_id)
        result = growth_ops.cancel(organization_id=org_id, appointment_id=appointment_id)
    elif action == "create_handoff":
        result = growth_ops.create_handoff(
            organization_id=org_id,
            contact_id=session.contact_id,
            reason=str(payload.get("reason") or "caller_requested_human"),
            summary=str(payload.get("summary") or ""),
        )
        session.status = "handed_off"
    else:
        raise GrowthAgentError("VOICE_EVENT_UNSUPPORTED", f"Unsupported voice event: {action}")

    session.usage_count = int(session.usage_count or 0) + 1
    session.updated_at = now()
    db.flush()
    return {"event_type": action, "result": result, "meta": meta}


def receive_inbound_webhook(
    db: Session,
    *,
    url: str,
    params: dict[str, Any],
    signature_header: str | None,
    auth_token: str | None,
    growth_ops: GrowthVoiceOps,
    provider: str = PROVIDER_TWILIO,
    simulator_mode: bool = False,
) -> dict[str, Any]:
    """Full inbound pipeline: signature → tenant → gates → dedupe → process."""
    validate_twilio_signature(
        url=url,
        params=params,
        signature_header=signature_header,
        auth_token=auth_token,
        simulator_mode=simulator_mode,
    )

    called = params.get("To") or params.get("called_number") or ""
    mapping = resolve_tenant_from_called_number(db, provider=provider, called_number=str(called))
    if mapping is None:
        raise GrowthAgentError("VOICE_UNKNOWN_NUMBER", "Called number is not mapped", http_status=404)

    webhook_org = params.get("organization_id") or params.get("OrganizationId")
    if webhook_org and str(webhook_org) != mapping.organization_id:
        raise GrowthAgentError(
            "VOICE_TENANT_MISMATCH",
            "Webhook organization_id does not match called-number mapping",
            http_status=403,
        )

    assert_mapping_allows_inbound(mapping, db)

    event_type = str(params.get("event_type") or params.get("GatherAction") or "faq_answer")
    event_id = extract_event_id(provider, params)
    call_sid = extract_call_sid(params)

    ledger, status = record_webhook_event(
        db,
        organization_id=mapping.organization_id,
        provider=provider,
        event_id=event_id,
        event_type=event_type,
        call_sid=call_sid,
        payload=params,
        signature_valid=True,
    )
    if status == "duplicate":
        return {
            "status": "duplicate",
            "organization_id": mapping.organization_id,
            "event_id": event_id,
            "ledger_id": ledger.id,
        }

    caller_phone = params.get("From") or params.get("caller_phone")
    session = get_or_create_session(
        db,
        organization_id=mapping.organization_id,
        provider=provider,
        call_sid=call_sid,
        caller_phone=str(caller_phone) if caller_phone else None,
    )

    outcome = process_inbound_event(
        db,
        mapping=mapping,
        session=session,
        event_type=event_type,
        payload=params,
        growth_ops=growth_ops,
    )
    ledger.status = "processed"
    ledger.result_json = {
        "organization_id": mapping.organization_id,
        "session_id": session.id,
        **outcome,
    }
    db.flush()
    return {
        "status": "processed",
        "organization_id": mapping.organization_id,
        "event_id": event_id,
        "session_id": session.id,
        **outcome,
    }