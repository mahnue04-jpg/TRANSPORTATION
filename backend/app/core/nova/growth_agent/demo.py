"""Synthetic end-to-end demo for a fictitious local service business.

No real prospects. All records labeled is_synthetic_demo=True.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.nova.growth_agent.models import GaDeliveryAttempt
from app.core.nova.growth_agent.service import GrowthAgentService

SYNTHETIC_BUSINESS = {
    "business_name": "Cedar Ridge Home Services (SYNTHETIC DEMO)",
    "website": "https://demo.cedar-ridge.example",
    "timezone": "America/Chicago",
    "operating_hours": {
        "mon_fri": "09:00-17:00",
        "sat": "closed",
        "sun": "closed",
    },
    "services": [
        {"code": "inspect", "name": "Home inspection consult", "duration_minutes": 30, "buffer_minutes": 10},
        {"code": "repair_quote", "name": "Repair quote visit", "duration_minutes": 45, "buffer_minutes": 15},
    ],
    "faqs": [
        {
            "id": "faq_hours",
            "question": "What are your hours?",
            "keywords": ["hours", "open", "schedule"],
            "answer": "We are open Monday–Friday 9:00–17:00 America/Chicago. Weekends closed.",
        },
        {
            "id": "faq_areas",
            "question": "What areas do you serve?",
            "keywords": ["area", "serve", "city", "coverage"],
            "answer": "We serve the synthetic demo metro only (fictitious).",
        },
        {
            "id": "faq_price",
            "question": "How much does an inspection consult cost?",
            "keywords": ["price", "cost", "fee"],
            "answer": "Inspection consults start at a quoted rate provided by a human; the AI does not invent discounts.",
        },
    ],
    "contact_email": "owner@cedar-ridge.example",
    "handoff_phone": "+15555550100",
    "escalation_settings": {"handoff_on_unknown": True, "handoff_on_legal": True},
    "branding": {"primary_color": "#1f4b3a", "accent": "#c4a35a"},
    "quiet_hours": {"enabled": True, "start": "21:00", "end": "08:00"},
    "plan_code": "growth",
    "is_synthetic_demo": True,
}


def run_synthetic_demo(db: Session, *, organization_id: str, owner_user_id: str) -> dict[str, Any]:
    svc = GrowthAgentService(db)
    profile = svc.upsert_profile(
        organization_id,
        owner_user_id,
        SYNTHETIC_BUSINESS,
        activate=True,
    )
    widget = svc.create_widget_installation(
        organization_id,
        domain="demo.cedar-ridge.example",
        branding=SYNTHETIC_BUSINESS["branding"],
        actor_user_id=owner_user_id,
    )

    # Consented inquiry via widget
    chat1 = svc.widget_chat(
        token=widget["token"],
        origin="https://demo.cedar-ridge.example",
        message="What are your hours?",
        visitor_name="Alex Demo",
        visitor_email="alex.demo@example.com",
        consent_transactional=True,
        consent_marketing=True,
    )

    # Duplicate submission should dedupe
    chat_dup = svc.widget_chat(
        token=widget["token"],
        origin="https://demo.cedar-ridge.example",
        message="Do you serve my city?",
        visitor_name="Alex Demo",
        visitor_email="alex.demo@example.com",
        consent_transactional=True,
        consent_marketing=True,
    )

    leads = svc.list_leads(organization_id)
    alex_leads = [l for l in leads if l["id"] == chat1.get("contact_id")]
    assert chat1["contact_id"] == chat_dup["contact_id"]

    # Owner CRM edit
    crm_edit = svc.update_lead(
        organization_id,
        chat1["contact_id"],
        lead_state="qualified",
        notes="Synthetic demo — qualified after FAQ chat",
        actor_user_id=owner_user_id,
    )

    # Booking
    day = (datetime.now(timezone.utc) + timedelta(days=2)).astimezone().strftime("%Y-%m-%d")
    for offset in range(2, 10):
        candidate = datetime.now(timezone.utc) + timedelta(days=offset)
        if candidate.weekday() < 5:
            day = candidate.strftime("%Y-%m-%d")
            break
    availability = svc.list_availability(organization_id, service_code="inspect", day=day)
    if not availability["slots"] or len(availability["slots"]) < 2:
        raise RuntimeError("Synthetic demo expected at least two availability slots")
    slot = availability["slots"][0]
    slot_b = availability["slots"][1]
    booking = svc.book_appointment(
        organization_id,
        contact_id=chat1["contact_id"],
        service_code="inspect",
        starts_at_utc=slot["starts_at_utc"],
        idempotency_key=f"demo-book-{chat1['contact_id']}-{slot['starts_at_utc']}",
        conversation_id=chat1["conversation_id"],
        actor_user_id=owner_user_id,
        is_synthetic_demo=True,
    )
    # Idempotent rebook
    booking2 = svc.book_appointment(
        organization_id,
        contact_id=chat1["contact_id"],
        service_code="inspect",
        starts_at_utc=slot["starts_at_utc"],
        idempotency_key=f"demo-book-{chat1['contact_id']}-{slot['starts_at_utc']}",
        conversation_id=chat1["conversation_id"],
        actor_user_id=owner_user_id,
        is_synthetic_demo=True,
    )

    # Cancel → rebook same slot, then reschedule
    cancelled = svc.cancel_appointment(
        organization_id,
        booking["id"],
        actor_user_id=owner_user_id,
    )
    rebooked = svc.book_appointment(
        organization_id,
        contact_id=chat1["contact_id"],
        service_code="inspect",
        starts_at_utc=slot["starts_at_utc"],
        idempotency_key=f"demo-rebook-{chat1['contact_id']}-{slot['starts_at_utc']}",
        conversation_id=chat1["conversation_id"],
        actor_user_id=owner_user_id,
        is_synthetic_demo=True,
    )
    rescheduled = svc.reschedule_appointment(
        organization_id,
        rebooked["id"],
        starts_at_utc=slot_b["starts_at_utc"],
        idempotency_key=f"demo-resched-{rebooked['id']}",
        actor_user_id=owner_user_id,
    )

    # Consented reminder dry-run
    preview = svc.preview_workflow(
        organization_id,
        workflow_code="appointment_reminder",
        contact_id=chat1["contact_id"],
        conversation_id=chat1["conversation_id"],
    )
    executed = svc.approve_and_execute_workflow(
        organization_id,
        run_id=preview["run_id"],
        dry_run=True,
        actor_user_id=owner_user_id,
        idempotency_key=f"demo-reminder-{preview['run_id']}",
    )

    # Restart recovery: leave a queued attempt, reclaim it
    recovery_preview = svc.preview_workflow(
        organization_id,
        workflow_code="inquiry_ack",
        contact_id=chat1["contact_id"],
        conversation_id=chat1["conversation_id"],
    )
    queued = GaDeliveryAttempt(
        id=f"demo-queued-{recovery_preview['run_id'][:16]}",
        organization_id=organization_id,
        workflow_run_id=recovery_preview["run_id"],
        channel="email",
        provider="mock",
        status="queued",
        idempotency_key=f"{recovery_preview['run_id']}:ack:email",
        cost_estimate_usd=0.0,
        payload_redacted_json={"note": "synthetic restart fixture"},
        attempt_number=1,
    )
    db.add(queued)
    db.commit()
    recovered = svc.recover_pending_deliveries(
        organization_id,
        actor_user_id=owner_user_id,
    )

    # Human handoff
    handoff = svc.handoff_conversation(
        organization_id,
        chat1["conversation_id"],
        actor_user_id=owner_user_id,
    )

    # Channel-correct marketing opt-out (email) — must not rely on blanket DNC
    opt = svc.record_consent(
        organization_id,
        contact_id=chat1["contact_id"],
        channel="email",
        purpose="marketing",
        status="opted_out",
        collection_source="owner_opt_out",
        actor_user_id=owner_user_id,
    )
    marketing_preview = svc.preview_workflow(
        organization_id,
        workflow_code="post_service_followup",
        contact_id=chat1["contact_id"],
    )
    suppressed = svc.approve_and_execute_workflow(
        organization_id,
        run_id=marketing_preview["run_id"],
        dry_run=True,
        actor_user_id=owner_user_id,
        idempotency_key=f"demo-mkt-{marketing_preview['run_id']}",
    )

    # Duplicate slot attempt with different idempotency should fail
    double_book_error = None
    try:
        svc.book_appointment(
            organization_id,
            contact_id=chat1["contact_id"],
            service_code="inspect",
            starts_at_utc=slot_b["starts_at_utc"],
            idempotency_key=f"demo-double-{slot_b['starts_at_utc']}",
            actor_user_id=owner_user_id,
            is_synthetic_demo=True,
        )
    except Exception as exc:  # noqa: BLE001 — capture for demo report
        double_book_error = getattr(exc, "code", type(exc).__name__)

    analytics = svc.analytics(organization_id)
    export = svc.export_org(organization_id)

    return {
        "label": "SYNTHETIC DEMO — not live customers",
        "profile": profile,
        "widget_installation_id": widget["installation_id"],
        "chat": {
            "first": chat1,
            "duplicate_contact_reused": chat_dup["contact_id"] == chat1["contact_id"],
        },
        "crm_edit": {
            "lead_state": crm_edit["lead_state"],
            "notes": crm_edit["notes"],
        },
        "leads_matching_alex": len(alex_leads),
        "booking": booking,
        "booking_idempotent_replay": booking2["id"] == booking["id"],
        "cancel_rebook": {
            "cancelled_status": cancelled["status"],
            "rebooked_id": rebooked["id"],
            "reused_same_row": rebooked["id"] == booking["id"],
        },
        "reschedule": {
            "status": rescheduled["status"],
            "starts_at_utc": rescheduled["starts_at_utc"],
        },
        "reminder_workflow": executed,
        "restart_recovery": recovered,
        "handoff": {"status": handoff["status"], "handler": handoff["handler"]},
        "opt_out": opt,
        "marketing_suppressed": suppressed,
        "double_book_blocked": double_book_error,
        "analytics": analytics,
        "export_includes": {
            "appointments": len(export.get("appointments") or []),
            "consent_records": len(export.get("consent_records") or []),
            "conversation_messages": len(export.get("conversation_messages") or []),
        },
        "audit_tail": svc.audit_history(organization_id, limit=20),
        "health": svc.health(organization_id),
    }
