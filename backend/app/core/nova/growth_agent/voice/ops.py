"""Service-backed GrowthVoiceOps — wires the voice simulator through real GA services.

Transports remain hard-off; callers inject fake calendar/email providers via
GrowthAgentService construction. Simulation shortcuts are never exposed on the
unauthenticated Twilio webhook (that path uses RejectOps in receptionist_router).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.faq_engine import answer_from_faqs
from app.core.nova.growth_agent.service import GrowthAgentService


class ServiceBackedGrowthVoiceOps:
    """FAQ → lead → availability → book → reschedule → cancel → notify → handoff."""

    def __init__(
        self,
        db: Session,
        *,
        actor_user_id: str | None = None,
        svc: GrowthAgentService | None = None,
    ) -> None:
        self.db = db
        self.actor_user_id = actor_user_id
        self.svc = svc or GrowthAgentService(db)

    def faq_answer(self, *, organization_id: str, question: str) -> dict[str, Any]:
        profile = self.svc._require_profile(organization_id)
        reply = answer_from_faqs(
            question,
            list(profile.faqs_json or []),
            business_name=profile.business_name or "this business",
        )
        return {
            **reply,
            "organization_id": organization_id,
            "simulated": True,
            "live_phone": False,
        }

    def capture_lead(
        self,
        *,
        organization_id: str,
        phone: str | None,
        name: str | None,
        notes: str | None,
    ) -> dict[str, Any]:
        contact = self.svc._upsert_contact(
            organization_id,
            name=name or "Voice caller",
            phone=phone,
            channel="phone",
            source="voice_simulator",
            consent_transactional=True,
        )
        if notes:
            contact.notes = (contact.notes or "") + f"\n[voice] {notes}"
        self.db.flush()
        return {
            "contact_id": contact.id,
            "organization_id": organization_id,
            "lead_state": contact.lead_state,
            "simulated": True,
            "live_phone": False,
        }

    def check_availability(
        self, *, organization_id: str, service_code: str | None
    ) -> dict[str, Any]:
        code = (service_code or "consult").strip() or "consult"
        day = (datetime.now(timezone.utc) + timedelta(days=1)).date()
        # Prefer next weekday
        while day.weekday() > 4:
            day += timedelta(days=1)
        result = self.svc.list_availability(
            organization_id, service_code=code, day=day.isoformat()
        )
        result["simulated"] = True
        result["live_phone"] = False
        return result

    def book(
        self,
        *,
        organization_id: str,
        contact_id: str | None,
        service_code: str,
        slot_start: str,
    ) -> dict[str, Any]:
        if not contact_id:
            raise GrowthAgentError(
                "VOICE_CONTACT_REQUIRED",
                "Capture a lead before booking",
                http_status=400,
            )
        if not slot_start:
            avail = self.check_availability(
                organization_id=organization_id, service_code=service_code
            )
            slots = avail.get("slots") or []
            if not slots:
                raise GrowthAgentError(
                    "VOICE_NO_SLOTS",
                    "No available slots",
                    http_status=409,
                )
            slot_start = slots[0].get("starts_at_utc") or slots[0].get("start") or ""
        result = self.svc.book_appointment(
            organization_id,
            contact_id=contact_id,
            service_code=service_code or "consult",
            starts_at_utc=slot_start,
            idempotency_key=f"voice-book:{uuid4().hex}",
            actor_user_id=self.actor_user_id,
            is_synthetic_demo=True,
        )
        return {
            "appointment_id": result.get("id"),
            "status": result.get("status"),
            "starts_at_utc": result.get("starts_at_utc"),
            "calendar_sync": result.get("calendar_sync"),
            "owner_notification": result.get("owner_notification"),
            "externally_confirmed": False,
            "simulated": True,
            "live_phone": False,
            "raw": result,
        }

    def reschedule(
        self, *, organization_id: str, appointment_id: str, slot_start: str
    ) -> dict[str, Any]:
        result = self.svc.reschedule_appointment(
            organization_id,
            appointment_id,
            starts_at_utc=slot_start,
            idempotency_key=f"voice-reschedule:{uuid4().hex}",
            actor_user_id=self.actor_user_id,
        )
        return {
            "appointment_id": result.get("id") or appointment_id,
            "status": result.get("status"),
            "externally_confirmed": False,
            "simulated": True,
            "live_phone": False,
            "calendar_sync": result.get("calendar_sync"),
            "owner_notification": result.get("owner_notification"),
        }

    def cancel(self, *, organization_id: str, appointment_id: str) -> dict[str, Any]:
        result = self.svc.cancel_appointment(
            organization_id,
            appointment_id,
            actor_user_id=self.actor_user_id,
        )
        return {
            "appointment_id": result.get("id") or appointment_id,
            "status": result.get("status"),
            "externally_confirmed": False,
            "simulated": True,
            "live_phone": False,
            "calendar_sync": result.get("calendar_sync"),
            "owner_notification": result.get("owner_notification"),
        }

    def create_handoff(
        self,
        *,
        organization_id: str,
        contact_id: str | None,
        reason: str,
        summary: str,
    ) -> dict[str, Any]:
        from app.core.nova.growth_agent import handoff_queue as hq

        row = hq.create_handoff(
            self.db,
            org_id=organization_id,
            reason=reason or "voice_escalation",
            summary=summary or "Voice simulator requested human help",
            channel="voice",
            contact_id=contact_id,
        )
        self.db.flush()
        return {
            **(row if isinstance(row, dict) else {"id": getattr(row, "id", None)}),
            "simulated": True,
            "live_phone": False,
        }


def intent_to_event_type(intent: str | None, utterance: str | None = None) -> str:
    """Map UI intent/utterance strings to inbound event_type labels."""
    raw = (intent or "").strip().lower()
    text = f"{raw} {(utterance or '').lower()}"
    if any(k in text for k in ("cancel", "cancellation")):
        return "cancel"
    if any(k in text for k in ("reschedule", "move", "change appointment")):
        return "reschedule"
    if any(k in text for k in ("book", "schedule", "appointment", "reserve")):
        return "book"
    if any(k in text for k in ("available", "availability", "slot", "open time")):
        return "check_availability"
    if any(k in text for k in ("lead", "callback", "call me", "leave my")):
        return "capture_lead"
    if any(k in text for k in ("human", "handoff", "agent", "representative", "person")):
        return "create_handoff"
    if any(k in text for k in ("hour", "faq", "price", "cost", "where", "what", "when", "general")):
        return "faq_answer"
    if raw in {
        "faq_answer",
        "capture_lead",
        "check_availability",
        "book",
        "reschedule",
        "cancel",
        "create_handoff",
    }:
        return raw
    return "faq_answer"
