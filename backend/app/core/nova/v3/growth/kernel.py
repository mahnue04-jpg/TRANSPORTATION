"""Nova V3 Growth + Shield kernel. Synthetic, owner-scoped, mock-only."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags
from app.core.nova.v3.growth import calendar as cal
from app.core.nova.v3.growth import inbound as inbound_agent
from app.core.nova.v3.growth import outreach as outreach_engine
from app.core.nova.v3.growth import quotes as quote_engine
from app.core.nova.v3.growth.catalog import TARGET_PROFILES
from app.core.nova.v3.growth.lifecycle import transition
from app.core.nova.v3.growth.models import (
    Activity,
    Customer,
    DemoRequest,
    GrowthApproval,
    Lead,
    OutreachMessage,
    Quote,
    SEQUENCE_STEPS,
    Sequence,
    ShieldDecision,
)
from app.core.nova.v3.growth.scoring import score_lead
from app.core.nova.v3.growth.shield import evaluate as shield_evaluate
from app.core.nova.v3.persistence import V3Store

_TAG_RE = re.compile(r"<[^>]+>")
GROWTH_TABLES = (
    ("nova_v3_leads", "lead_id"),
    ("nova_v3_outreach_messages", "message_id"),
    ("nova_v3_sequences", "sequence_id"),
    ("nova_v3_demos", "demo_id"),
    ("nova_v3_quotes", "quote_id"),
    ("nova_v3_customers", "customer_id"),
    ("nova_v3_shield_decisions", "decision_id"),
    ("nova_v3_growth_approvals", "approval_id"),
)


def _utc(value: datetime | None = None) -> datetime:
    stamp = value or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def fingerprint(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _plain(value: str | None) -> str:
    return _TAG_RE.sub("", str(value or "")).strip()


class GrowthKernel:
    def __init__(self) -> None:
        self.now = _utc()
        self._seq = 0
        self.leads: dict[str, Lead] = {}
        self.activities: list[Activity] = []
        self.messages: dict[str, OutreachMessage] = {}
        self.sequences: dict[str, Sequence] = {}
        self.demos: dict[str, DemoRequest] = {}
        self.quotes: dict[str, Quote] = {}
        self.customers: dict[str, Customer] = {}
        self.shield_log: dict[str, ShieldDecision] = {}
        self.approvals: dict[str, GrowthApproval] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.idempotency: dict[tuple[str, str, str, str], str] = {}
        self.store: V3Store | None = None

    def _id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq:05d}"

    def _note(self, lead_id: str, kind: str, **detail: Any) -> None:
        lead = self.leads[lead_id]
        row = Activity(
            activity_id=self._id("V3ACT"),
            organization_id=lead.organization_id,
            owner_user_id=lead.owner_user_id,
            lead_id=lead_id,
            kind=kind,
            detail=detail,
            at=self.now,
        )
        self.activities.append(row)

    def assert_owner(self, row_owner: str, owner_user_id: str) -> None:
        if row_owner != owner_user_id:
            raise V3Error("FORBIDDEN", "owner isolation", http_status=403)

    def assert_tenant(self, row_org: str, organization_id: str) -> None:
        if row_org != organization_id:
            raise V3Error("NOT_FOUND", "resource not found", http_status=404)

    def get_customer(self, customer_id: str, *, organization_id: str, owner_user_id: str) -> Customer:
        row = self.customers.get(customer_id)
        if row is None or not row.organization_id or not row.owner_user_id:
            raise V3Error("NOT_FOUND", "customer not found", http_status=404)
        self.assert_tenant(row.organization_id, organization_id)
        self.assert_owner(row.owner_user_id, owner_user_id)
        return row

    def list_customers(self, *, organization_id: str, owner_user_id: str) -> list[Customer]:
        return [
            item
            for item in self.customers.values()
            if item.organization_id == organization_id and item.owner_user_id == owner_user_id
        ]

    def customer_out(self, row: Customer) -> dict[str, Any]:
        return {
            "customer_id": row.customer_id,
            "organization_id": row.organization_id,
            "owner_user_id": row.owner_user_id,
            "lead_id": row.lead_id,
            "name": row.name,
            "product": row.product,
            "status": row.status,
            "external_account_created": False,
            "live": False,
        }

    def get_lead(self, lead_id: str, *, organization_id: str, owner_user_id: str) -> Lead:
        row = self.leads.get(lead_id)
        if row is None or row.organization_id != organization_id:
            raise V3Error("NOT_FOUND", "lead not found", http_status=404)
        self.assert_owner(row.owner_user_id, owner_user_id)
        return row

    def discover(self, payload: dict[str, Any], *, organization_id: str, owner_user_id: str) -> Lead:
        if live_flags().get("LIVE_LEAD_DISCOVERY") or live_flags().get("LIVE_DISCOVERY_ENABLED"):
            raise V3Error("LIVE_DISABLED", "live lead discovery is off")
        company = _plain(payload.get("organization_name"))
        email = _plain(payload.get("email_placeholder")) or None
        website = _plain(payload.get("website")) or None
        fp = fingerprint(organization_id, owner_user_id, company.lower(), (website or "").lower(), (email or "").lower())
        existing = next(
            (
                item
                for item in self.leads.values()
                if item.organization_id == organization_id
                and item.owner_user_id == owner_user_id
                and item.fingerprint == fp
            ),
            None,
        )
        explained = score_lead(payload)
        if existing:
            existing.duplicate_of = existing.duplicate_of or existing.lead_id
            existing.provenance = {
                **existing.provenance,
                "also_seen": payload.get("source"),
                "synthetic": True,
            }
            self._note(existing.lead_id, "DEDUPED", source=payload.get("source"), fingerprint=fp)
            return existing
        invalid = bool(email) and ("@" not in email or "." not in email.split("@")[-1])
        status = "DISCOVERED"
        if explained["qualification_status"] == "DO_NOT_CONTACT":
            status = "DO_NOT_CONTACT"
        lead = Lead(
            lead_id=self._id("V3LED"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            organization_name=company,
            contact_name=_plain(payload.get("contact_name")),
            role_title=_plain(payload.get("role_title")),
            industry=_plain(payload.get("industry")).lower(),
            geography=_plain(payload.get("geography")),
            website=website,
            email_placeholder=email,
            phone_placeholder=_plain(payload.get("phone_placeholder")) or None,
            source=str(payload.get("source") or "manual"),
            provenance={"synthetic": True, "live": False, "source": payload.get("source") or "manual"},
            source_url=payload.get("source_url"),
            discovered_at=self.now,
            business_need=_plain(payload.get("business_need")),
            product_fit=explained["product_fit"],
            estimated_value=None if payload.get("estimated_value") is None else float(payload["estimated_value"]),
            urgency=str(payload.get("urgency") or "unspecified"),
            score=explained["score"],
            score_explanation=explained,
            qualification_status=explained["qualification_status"],
            consent_restrictions=list(payload.get("consent_restrictions") or []),
            next_action=explained["recommended_next_action"],
            follow_up_at=self.now + timedelta(days=3),
            status=status,
            fingerprint=fp,
            do_not_contact=status == "DO_NOT_CONTACT",
            opted_out="opt-out" in [str(item).lower() for item in (payload.get("consent_restrictions") or [])],
            invalid_contact=invalid,
            high_value=explained["high_value"],
            regulated=explained["regulated"],
            nova_notes=explained["why"],
        )
        if invalid:
            lead.qualification_status = "DISQUALIFIED"
            lead.next_action = "repair_or_discard_invalid_contact"
        self.leads[lead.lead_id] = lead
        self._note(lead.lead_id, "DISCOVERED", source=lead.source, score=lead.score)
        return lead

    def qualify(self, lead_id: str, *, organization_id: str, owner_user_id: str) -> Lead:
        lead = self.get_lead(lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        wanted = lead.qualification_status
        if wanted == "DO_NOT_CONTACT":
            lead.status = transition(lead.status, "DO_NOT_CONTACT")
        elif wanted == "DISQUALIFIED":
            lead.status = transition(lead.status, "DISQUALIFIED")
        elif wanted == "OWNER_REVIEW":
            lead.status = transition(lead.status, "OWNER_REVIEW")
        elif wanted == "QUALIFIED":
            lead.status = transition(lead.status, "QUALIFIED")
            lead.status = transition(lead.status, "OUTREACH_READY")
        else:
            lead.status = transition(lead.status, "QUALIFYING")
        lead.next_action = lead.score_explanation["recommended_next_action"]
        self._note(lead.lead_id, "QUALIFIED", status=lead.status, score=lead.score)
        return lead

    def set_do_not_contact(self, lead_id: str, *, organization_id: str, owner_user_id: str, reason: str) -> Lead:
        lead = self.get_lead(lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        lead.do_not_contact = True
        lead.opted_out = True
        lead.status = transition(lead.status, "DO_NOT_CONTACT")
        lead.loss_reason = reason
        self._cancel_sequences(lead)
        self._note(lead.lead_id, "DO_NOT_CONTACT", reason=reason)
        return lead

    def _cancel_sequences(self, lead: Lead) -> None:
        for seq in self.sequences.values():
            if seq.lead_id == lead.lead_id and seq.status == "ACTIVE":
                seq.status = "CANCELLED"
                seq.pause_reason = lead.status

    def shield(self, *, action: str, lead: Lead | None, content: str = "", extra: dict[str, Any] | None = None) -> dict[str, Any]:
        result = shield_evaluate(action=action, lead=lead, content=content, extra=extra)
        row = ShieldDecision(
            decision_id=self._id("V3SHD"),
            organization_id=lead.organization_id if lead else "unknown",
            owner_user_id=lead.owner_user_id if lead else "unknown",
            lead_id=None if lead is None else lead.lead_id,
            action=action,
            state=result["state"],
            reasons=list(result["reasons"]),
            explain=result["explain"],
            at=self.now,
            content_fingerprint=fingerprint(content) if content else None,
        )
        self.shield_log[row.decision_id] = row
        if lead:
            self._note(lead.lead_id, "SHIELD", state=result["state"], explain=result["explain"])
        return {**result, "decision_id": row.decision_id}

    def prepare_outreach(self, lead_id: str, kind: str, *, organization_id: str, owner_user_id: str, extra: dict[str, Any] | None = None) -> OutreachMessage:
        lead = self.get_lead(lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        if lead.status in {"DO_NOT_CONTACT", "ARCHIVED", "LOST"}:
            raise V3Error("CONTACT_FORBIDDEN", "lead is not eligible for outreach")
        drafted = outreach_engine.draft(lead, kind, extra=extra)
        extra = extra or {}
        gate = self.shield(action="prepare_outreach", lead=lead, content=drafted["body"], extra=extra)
        if gate["state"] not in {"ALLOW_SYNTHETIC", "OWNER_APPROVAL_REQUIRED"}:
            raise V3Error(gate["state"], gate["explain"])
        if not drafted["quality"]["passed"]:
            raise V3Error("MESSAGE_QUALITY_FAILED", "outreach failed quality gate")
        row = OutreachMessage(
            message_id=self._id("V3GMSG"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            lead_id=lead_id,
            kind=kind,
            body=drafted["body"],
            status="DRAFTED",
            quality=drafted["quality"],
            shield_state=gate["state"],
        )
        self.messages[row.message_id] = row
        if lead.status in {"QUALIFIED", "OWNER_REVIEW", "DISCOVERED", "QUALIFYING"}:
            if lead.status == "QUALIFIED":
                lead.status = transition(lead.status, "OUTREACH_READY")
        self._note(lead_id, "OUTREACH_DRAFTED", outreach_kind=kind, shield=gate["state"])
        return row

    def request_approval(
        self,
        *,
        organization_id: str,
        owner_user_id: str,
        lead_id: str,
        action: str,
        target_id: str,
        payload: dict[str, Any],
        expires_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> GrowthApproval:
        if idempotency_key:
            prior = self.idempotency.get((organization_id, owner_user_id, "gappr", idempotency_key))
            if prior:
                return self.approvals[prior]
        self.get_lead(lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        row = GrowthApproval(
            approval_id=self._id("V3GAP"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            lead_id=lead_id,
            action=action,
            target_id=target_id,
            payload_fingerprint=fingerprint(payload),
            status="PENDING",
            created_at=self.now,
            expires_at=expires_at,
        )
        self.approvals[row.approval_id] = row
        if idempotency_key:
            self.idempotency[(organization_id, owner_user_id, "gappr", idempotency_key)] = row.approval_id
        return row

    def decide_approval(self, approval_id: str, *, organization_id: str, owner_user_id: str, decision: str) -> GrowthApproval:
        row = self.approvals.get(approval_id)
        if row is None or row.organization_id != organization_id:
            raise V3Error("NOT_FOUND", "approval not found", http_status=404)
        self.assert_owner(row.owner_user_id, owner_user_id)
        if row.expires_at is not None and row.expires_at < self.now:
            row.status = "EXPIRED"
            raise V3Error("EXPIRED_APPROVAL", "expired approval cannot be decided")
        if row.status != "PENDING":
            raise V3Error("INVALID_STATE", f"cannot decide from {row.status}")
        wanted = decision.upper()
        if wanted not in {"APPROVED", "REJECTED"}:
            raise V3Error("INVALID_DECISION", "decision must be APPROVED or REJECTED", http_status=400)
        row.status = wanted
        return row

    def consume_approval(self, approval_id: str, *, organization_id: str, owner_user_id: str, action: str, target_id: str, payload: dict[str, Any]) -> GrowthApproval:
        row = self.approvals.get(approval_id)
        if row is None or row.organization_id != organization_id:
            raise V3Error("NOT_FOUND", "approval not found", http_status=404)
        self.assert_owner(row.owner_user_id, owner_user_id)
        if row.expires_at is not None and row.expires_at < self.now:
            row.status = "EXPIRED"
        if row.status == "CONSUMED":
            raise V3Error("DUPLICATE_CONSUME", "consumed approval cannot execute twice")
        if row.status != "APPROVED":
            raise V3Error(row.status + "_APPROVAL" if row.status in {"EXPIRED", "REVOKED", "REJECTED"} else "MISSING_APPROVAL", "approval cannot execute")
        if row.action != action or row.target_id != target_id or row.payload_fingerprint != fingerprint(payload):
            raise V3Error("STALE_APPROVAL", "approval binding mismatch")
        self.get_lead(row.lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        row.status = "CONSUMED"
        row.consumed_at = self.now
        return row

    def mock_send(self, message_id: str, *, organization_id: str, owner_user_id: str, approval_id: str | None = None) -> OutreachMessage:
        if live_flags().get("REAL_OUTREACH_SEND") or live_flags().get("REAL_EMAIL_SEND") or live_flags().get("CLIENT_CONTACT_ENABLED"):
            raise V3Error("LIVE_DISABLED", "real outreach is off")
        row = self.messages.get(message_id)
        if row is None:
            raise V3Error("NOT_FOUND", "message not found", http_status=404)
        lead = self.get_lead(row.lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        extra = {"duplicate_outreach": any(item.lead_id == lead.lead_id and item.mock_sent and item.kind == row.kind for item in self.messages.values() if item.message_id != row.message_id)}
        gate = self.shield(action="mock_send", lead=lead, content=row.body, extra=extra)
        if extra["duplicate_outreach"] and gate["state"] == "RATE_LIMIT":
            raise V3Error("RATE_LIMIT", gate["explain"])
        if gate["state"] == "OWNER_APPROVAL_REQUIRED":
            if not approval_id:
                raise V3Error("MISSING_APPROVAL", "owner approval required")
            self.consume_approval(
                approval_id,
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                action="MOCK_OUTREACH_SEND",
                target_id=message_id,
                payload={"message_id": message_id, "lead_id": lead.lead_id},
            )
        elif gate["blocked"]:
            raise V3Error(gate["state"], gate["explain"])
        outreach_engine.require_quality(row.quality)
        row.status = "MOCK_SENT"
        row.mock_sent = True
        row.sent_externally = False
        lead.outreach_count += 1
        lead.last_contact_at = self.now
        if lead.status in {"OUTREACH_READY", "QUALIFIED", "OWNER_REVIEW"}:
            lead.status = transition(lead.status, "CONTACTED_MOCK") if lead.status == "OUTREACH_READY" else lead.status
            if lead.status == "OWNER_REVIEW":
                lead.status = transition(lead.status, "OUTREACH_READY")
                lead.status = transition(lead.status, "CONTACTED_MOCK")
            elif lead.status == "QUALIFIED":
                lead.status = transition(lead.status, "OUTREACH_READY")
                lead.status = transition(lead.status, "CONTACTED_MOCK")
        elif lead.status == "CONTACTED_MOCK":
            pass
        self._note(lead.lead_id, "MOCK_SENT", message_id=message_id, live=False)
        return row

    def ingest_reply(self, lead_id: str, text: str, *, organization_id: str, owner_user_id: str) -> Lead:
        lead = self.get_lead(lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        lower = text.lower()
        lead.last_contact_at = self.now
        if any(token in lower for token in ("stop", "do not contact", "unsubscribe", "opt out")):
            return self.set_do_not_contact(lead_id, organization_id=organization_id, owner_user_id=owner_user_id, reason="prospect_opt_out")
        if any(token in lower for token in ("not interested", "no thanks", "go away")):
            lead.status = transition(lead.status, "LOST")
            lead.loss_reason = "negative_reply"
            self._cancel_sequences(lead)
            self._note(lead_id, "NEGATIVE_REPLY", text=text)
            return lead
        if "demo" in lower:
            lead.status = transition(lead.status, "ENGAGED") if lead.status == "CONTACTED_MOCK" else lead.status
            if lead.status == "ENGAGED":
                lead.status = transition(lead.status, "DEMO_REQUESTED")
            elif lead.status == "CONTACTED_MOCK":
                lead.status = transition(lead.status, "DEMO_REQUESTED")
            self._cancel_sequences(lead)
            seq = next((item for item in self.sequences.values() if item.lead_id == lead_id), None)
            if seq:
                seq.status = "DEMO_BOOKED"
            self._note(lead_id, "DEMO_INTEREST", text=text)
            return lead
        if lead.status == "CONTACTED_MOCK":
            lead.status = transition(lead.status, "ENGAGED")
        self._note(lead_id, "REPLY", text=text)
        for seq in self.sequences.values():
            if seq.lead_id == lead_id and seq.status == "ACTIVE":
                seq.status = "PROSPECT_REPLIED"
        return lead

    def start_sequence(self, lead_id: str, *, organization_id: str, owner_user_id: str) -> Sequence:
        lead = self.get_lead(lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        if lead.do_not_contact:
            raise V3Error("DO_NOT_CONTACT", "cannot start sequence")
        row = Sequence(
            sequence_id=self._id("V3SEQ"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            lead_id=lead_id,
        )
        self.sequences[row.sequence_id] = row
        self._note(lead_id, "SEQUENCE_STARTED")
        return row

    def pause_sequence(self, sequence_id: str, *, organization_id: str, owner_user_id: str, reason: str) -> Sequence:
        row = self.sequences[sequence_id]
        self.assert_owner(row.owner_user_id, owner_user_id)
        row.status = "PAUSED"
        row.pause_reason = reason
        return row

    def resume_sequence(self, sequence_id: str, *, organization_id: str, owner_user_id: str) -> Sequence:
        row = self.sequences[sequence_id]
        self.assert_owner(row.owner_user_id, owner_user_id)
        if row.status == "CANCELLED":
            raise V3Error("SEQUENCE_CANCELLED", "cannot resume")
        row.status = "ACTIVE"
        return row

    def cancel_sequence(self, sequence_id: str, *, organization_id: str, owner_user_id: str, reason: str) -> Sequence:
        row = self.sequences[sequence_id]
        self.assert_owner(row.owner_user_id, owner_user_id)
        row.status = "CANCELLED"
        row.pause_reason = reason
        return row

    def tick_sequence(self, sequence_id: str, *, organization_id: str, owner_user_id: str, day: int) -> OutreachMessage | None:
        row = self.sequences[sequence_id]
        self.assert_owner(row.owner_user_id, owner_user_id)
        lead = self.get_lead(row.lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        if row.status != "ACTIVE" or lead.do_not_contact or lead.status in {"WON", "LOST", "DO_NOT_CONTACT", "ARCHIVED"}:
            return None
        if row.step_index >= len(SEQUENCE_STEPS):
            row.status = "COMPLETED"
            return None
        key, offset, kind = SEQUENCE_STEPS[row.step_index]
        if day < offset:
            return None
        message = self.prepare_outreach(lead.lead_id, kind, organization_id=organization_id, owner_user_id=owner_user_id)
        row.step_index += 1
        self._note(lead.lead_id, "SEQUENCE_STEP", step=key, outreach_kind=kind)
        return message

    def inbound(self, session_id: str, message: str, *, organization_id: str, owner_user_id: str) -> dict[str, Any]:
        session = self.sessions.setdefault(session_id, {"organization_id": organization_id, "owner_user_id": owner_user_id, "state": "GREETING"})
        result = inbound_agent.turn(session, message)
        self.sessions[session_id] = result["session"]
        return result

    def request_demo(self, lead_id: str, *, organization_id: str, owner_user_id: str, timezone_name: str, demo_type: str = "intro") -> DemoRequest:
        lead = self.get_lead(lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        cal.assert_synthetic()
        tz = cal.require_timezone(timezone_name)
        if lead.status == "CONTACTED_MOCK":
            lead.status = transition(lead.status, "ENGAGED")
        if lead.status == "ENGAGED":
            lead.status = transition(lead.status, "DEMO_REQUESTED")
        elif lead.status == "QUALIFIED":
            lead.status = transition(lead.status, "OUTREACH_READY")
            lead.status = transition(lead.status, "CONTACTED_MOCK")
            lead.status = transition(lead.status, "ENGAGED")
            lead.status = transition(lead.status, "DEMO_REQUESTED")
        elif lead.status == "OUTREACH_READY":
            lead.status = transition(lead.status, "CONTACTED_MOCK")
            lead.status = transition(lead.status, "ENGAGED")
            lead.status = transition(lead.status, "DEMO_REQUESTED")
        elif lead.status not in {"DEMO_REQUESTED", "DEMO_SCHEDULED"}:
            raise V3Error("INVALID_STATE", "demo requires an engaged or requested lead")
        row = DemoRequest(
            demo_id=self._id("V3DEM"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            lead_id=lead_id,
            requested_at=self.now,
            timezone_name=tz,
            product=lead.product_fit,
            demo_type=demo_type,
            contact_name=lead.contact_name,
            company=lead.organization_name,
        )
        self.demos[row.demo_id] = row
        self._note(lead_id, "DEMO_REQUESTED", timezone=tz)
        return row

    def schedule_demo(self, demo_id: str, *, organization_id: str, owner_user_id: str, when: datetime | None = None) -> DemoRequest:
        cal.assert_synthetic()
        row = self.demos[demo_id]
        lead = self.get_lead(row.lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        slots = cal.availability_placeholder(row.timezone_name, self.now)
        row.scheduled_at = when or datetime.fromisoformat(slots[0])
        row.status = "SCHEDULED"
        if lead.status == "DEMO_REQUESTED":
            lead.status = transition(lead.status, "DEMO_SCHEDULED")
        self._note(lead.lead_id, "DEMO_SCHEDULED", at=row.scheduled_at.isoformat(), live_calendar=False)
        return row

    def reschedule_demo(self, demo_id: str, *, organization_id: str, owner_user_id: str) -> DemoRequest:
        row = self.schedule_demo(demo_id, organization_id=organization_id, owner_user_id=owner_user_id)
        row.status = "RESCHEDULED"
        return row

    def cancel_demo(self, demo_id: str, *, organization_id: str, owner_user_id: str) -> DemoRequest:
        row = self.demos[demo_id]
        self.get_lead(row.lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        row.status = "CANCELLED"
        return row

    def reminder_draft(self, demo_id: str, *, organization_id: str, owner_user_id: str) -> dict[str, Any]:
        row = self.demos[demo_id]
        lead = self.get_lead(row.lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        return {
            "body": f"INTERNAL reminder draft for {lead.organization_name} demo. Not sent. Timezone {row.timezone_name}.",
            "live": False,
        }

    def prepare_quote(self, lead_id: str, service_id: str, *, organization_id: str, owner_user_id: str, kind: str = "standard", discount_pct: float = 0, custom_amount: float | None = None) -> Quote:
        lead = self.get_lead(lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        extra = {"custom_pricing": custom_amount is not None, "unauthorized_discount": False}
        drafted = quote_engine.prepare_quote(lead, service_id=service_id, kind=kind, discount_pct=discount_pct, custom_amount=custom_amount)
        gate = self.shield(action="prepare_quote" if custom_amount is None else "custom_quote", lead=lead, content=drafted["body"], extra=extra)
        if gate["blocked"]:
            raise V3Error(gate["state"], gate["explain"])
        row = Quote(
            quote_id=self._id("V3QTE"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            lead_id=lead_id,
            service_id=service_id,
            kind=kind,
            amount=drafted["amount"],
            status="OWNER_ACTION_REQUIRED" if drafted["owner_action_required"] else "DRAFT",
            body=drafted["body"],
            owner_action_required=drafted["owner_action_required"],
        )
        self.quotes[row.quote_id] = row
        if not row.owner_action_required and lead.status in {"DEMO_SCHEDULED", "ENGAGED", "NEGOTIATION"}:
            if lead.status == "DEMO_SCHEDULED":
                lead.status = transition(lead.status, "PROPOSAL_READY")
            elif lead.status == "ENGAGED":
                lead.status = transition(lead.status, "PROPOSAL_READY")
        self._note(lead_id, "QUOTE_DRAFTED", quote_id=row.quote_id, owner_action=row.owner_action_required)
        return row

    def mark_negotiation(self, lead_id: str, *, organization_id: str, owner_user_id: str) -> Lead:
        lead = self.get_lead(lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        lead.status = transition(lead.status, "NEGOTIATION")
        return lead

    def convert(self, lead_id: str, *, organization_id: str, owner_user_id: str, approval_id: str | None = None, reason: str = "owner_accepted_synthetic") -> Customer:
        if live_flags().get("REAL_CONTRACT_ACCEPTANCE") or live_flags().get("REAL_PAYMENT_EXECUTION"):
            raise V3Error("LIVE_DISABLED", "real conversion is off")
        if not organization_id or not owner_user_id:
            raise V3Error("FORBIDDEN", "owner and tenant are required to convert", http_status=403)
        lead = self.get_lead(lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        if lead.high_value and not approval_id:
            raise V3Error("MISSING_APPROVAL", "high-value conversion requires owner approval")
        if approval_id:
            self.consume_approval(
                approval_id,
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                action="CONVERT",
                target_id=lead_id,
                payload={"lead_id": lead_id},
            )
        if lead.status == "PROPOSAL_READY":
            lead.status = transition(lead.status, "NEGOTIATION")
        lead.status = transition(lead.status, "WON")
        lead.conversion_reason = reason
        self._cancel_sequences(lead)
        customer = Customer(
            customer_id=self._id("V3CUS"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            lead_id=lead_id,
            name=lead.organization_name,
            product=lead.product_fit,
            onboarding=["confirm owner contacts", "prepare synthetic workspace", "no external account"],
        )
        self.customers[customer.customer_id] = customer
        self._note(lead_id, "CONVERTED", customer_id=customer.customer_id, external=False)
        return customer

    def convert_synthetic_fixture(
        self,
        *,
        organization_id: str,
        owner_user_id: str,
        organization_name: str = "Convert Co",
        email_placeholder: str | None = None,
    ) -> Customer:
        from app.core.nova.v3.growth.fixtures import fixture

        payload = fixture("C")
        payload["organization_name"] = organization_name
        payload["email_placeholder"] = email_placeholder or f"{organization_name.lower().replace(' ', '')}@example-smb.test"
        lead = self.discover(payload, organization_id=organization_id, owner_user_id=owner_user_id)
        self.qualify(lead.lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        message = self.prepare_outreach(
            lead.lead_id, "introduction_email", organization_id=organization_id, owner_user_id=owner_user_id
        )
        self.mock_send(message.message_id, organization_id=organization_id, owner_user_id=owner_user_id)
        self.ingest_reply(lead.lead_id, "We want a demo", organization_id=organization_id, owner_user_id=owner_user_id)
        demo = self.request_demo(
            lead.lead_id, organization_id=organization_id, owner_user_id=owner_user_id, timezone_name="America/Chicago"
        )
        self.schedule_demo(demo.demo_id, organization_id=organization_id, owner_user_id=owner_user_id)
        self.prepare_quote(lead.lead_id, "nova_ops_assist", organization_id=organization_id, owner_user_id=owner_user_id, kind="trial")
        self.mark_negotiation(lead.lead_id, organization_id=organization_id, owner_user_id=owner_user_id)
        return self.convert(lead.lead_id, organization_id=organization_id, owner_user_id=owner_user_id)

    def crm_views(self, *, organization_id: str, owner_user_id: str) -> dict[str, list[dict[str, Any]]]:
        mapping = {
            "NEW LEADS": {"DISCOVERED", "QUALIFYING"},
            "QUALIFIED": {"QUALIFIED", "OUTREACH_READY"},
            "NEEDS OWNER REVIEW": {"OWNER_REVIEW"},
            "OUTREACH READY": {"OUTREACH_READY"},
            "ENGAGED": {"ENGAGED", "CONTACTED_MOCK"},
            "DEMO REQUESTED": {"DEMO_REQUESTED"},
            "DEMO SCHEDULED": {"DEMO_SCHEDULED"},
            "PROPOSAL READY": {"PROPOSAL_READY"},
            "NEGOTIATION": {"NEGOTIATION"},
            "WON": {"WON"},
            "LOST": {"LOST"},
            "FOLLOW-UP": set(),
            "DO NOT CONTACT": {"DO_NOT_CONTACT"},
        }
        owned = [lead for lead in self.leads.values() if lead.organization_id == organization_id and lead.owner_user_id == owner_user_id]
        views: dict[str, list[dict[str, Any]]] = {}
        for name, statuses in mapping.items():
            if name == "FOLLOW-UP":
                views[name] = [self.lead_out(item) for item in owned if item.follow_up_at and item.follow_up_at <= self.now and item.status not in {"WON", "LOST", "DO_NOT_CONTACT", "ARCHIVED"}]
            else:
                views[name] = [self.lead_out(item) for item in owned if item.status in statuses]
        views["CUSTOMERS CONVERTED"] = [
            self.customer_out(item) for item in self.list_customers(organization_id=organization_id, owner_user_id=owner_user_id)
        ]
        return views

    def lead_out(self, lead: Lead) -> dict[str, Any]:
        timeline = [item.__dict__ | {"at": item.at.isoformat()} for item in self.activities if item.lead_id == lead.lead_id]
        return {
            "lead_id": lead.lead_id,
            "organization_name": lead.organization_name,
            "contact_name": lead.contact_name,
            "role_title": lead.role_title,
            "industry": lead.industry,
            "geography": lead.geography,
            "website": lead.website,
            "email_placeholder": lead.email_placeholder,
            "phone_placeholder": lead.phone_placeholder,
            "source": lead.source,
            "provenance": lead.provenance,
            "source_url": lead.source_url,
            "discovered_at": lead.discovered_at.isoformat(),
            "business_need": lead.business_need,
            "product_fit": lead.product_fit,
            "estimated_value": lead.estimated_value,
            "urgency": lead.urgency,
            "score": lead.score,
            "score_explanation": lead.score_explanation,
            "qualification_status": lead.qualification_status,
            "consent_restrictions": lead.consent_restrictions,
            "next_action": lead.next_action,
            "follow_up_date": None if lead.follow_up_at is None else lead.follow_up_at.isoformat(),
            "status": lead.status,
            "duplicate_of": lead.duplicate_of,
            "do_not_contact": lead.do_not_contact,
            "last_contact": None if lead.last_contact_at is None else lead.last_contact_at.isoformat(),
            "next_contact": None if lead.follow_up_at is None else lead.follow_up_at.isoformat(),
            "owner_notes": lead.owner_notes,
            "nova_notes": lead.nova_notes,
            "activity_timeline": timeline[-20:],
            "conversion_reason": lead.conversion_reason,
            "loss_reason": lead.loss_reason,
            "live": False,
        }

    def filter_leads(self, *, organization_id: str, owner_user_id: str, product: str | None = None, industry: str | None = None, location: str | None = None, status: str | None = None, min_score: float | None = None, source: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for lead in self.leads.values():
            if lead.organization_id != organization_id or lead.owner_user_id != owner_user_id:
                continue
            if product and lead.product_fit != product:
                continue
            if industry and industry.lower() not in lead.industry:
                continue
            if location and location.lower() not in lead.geography.lower():
                continue
            if status and lead.status != status:
                continue
            if min_score is not None and lead.score < min_score:
                continue
            if source and lead.source != source:
                continue
            rows.append(self.lead_out(lead))
        return rows

    def growth_dashboard(self, *, organization_id: str, owner_user_id: str) -> dict[str, Any]:
        owned = [lead for lead in self.leads.values() if lead.organization_id == organization_id and lead.owner_user_id == owner_user_id]
        msgs = [item for item in self.messages.values() if item.organization_id == organization_id and item.owner_user_id == owner_user_id]
        shield_rows = [item for item in self.shield_log.values() if item.organization_id == organization_id and item.owner_user_id == owner_user_id]
        waiting = [item for item in self.approvals.values() if item.organization_id == organization_id and item.owner_user_id == owner_user_id and item.status == "PENDING"]
        converted = [self.customer_out(item) for item in self.list_customers(organization_id=organization_id, owner_user_id=owner_user_id)]
        return {
            "LEADS FOUND": len(owned),
            "QUALIFIED": len([item for item in owned if item.status in {"QUALIFIED", "OUTREACH_READY"}]),
            "OUTREACH READY": len([item for item in owned if item.status == "OUTREACH_READY"]),
            "FOLLOW-UPS DUE": len([item for item in owned if item.follow_up_at and item.follow_up_at <= self.now]),
            "REPLIES": len([item for item in self.activities if item.kind == "REPLY" and item.organization_id == organization_id and item.owner_user_id == owner_user_id]),
            "INTERESTED": len([item for item in owned if item.status in {"ENGAGED", "DEMO_REQUESTED", "DEMO_SCHEDULED"}]),
            "DEMOS REQUESTED": len([item for item in owned if item.status == "DEMO_REQUESTED"]),
            "DEMOS SCHEDULED": len([item for item in owned if item.status == "DEMO_SCHEDULED"]),
            "PROPOSALS": len([item for item in self.quotes.values() if item.organization_id == organization_id and item.owner_user_id == owner_user_id]),
            "WON": len([item for item in owned if item.status == "WON"]),
            "LOST": len([item for item in owned if item.status == "LOST"]),
            "CUSTOMERS_CONVERTED": converted,
            "BLOCKED BY SHIELD": len([item for item in shield_rows if item.state in {"BLOCK", "DO_NOT_CONTACT", "RATE_LIMIT"}]),
            "WAITING OWNER APPROVAL": len(waiting) + len([item for item in shield_rows if item.state == "OWNER_APPROVAL_REQUIRED"]),
            "filters": {"product": None, "industry": None, "location": None, "status": None, "score": None, "source": None, "date": None},
            "profiles": list(TARGET_PROFILES),
            "mock_sends": len([item for item in msgs if item.mock_sent]),
            "live": False,
        }

    def shield_dashboard(self, *, organization_id: str, owner_user_id: str) -> dict[str, Any]:
        rows = [item for item in self.shield_log.values() if item.organization_id == organization_id and item.owner_user_id == owner_user_id]
        return {
            "actions_allowed": len([item for item in rows if item.state == "ALLOW_SYNTHETIC"]),
            "actions_blocked": len([item for item in rows if item.state in {"BLOCK", "DO_NOT_CONTACT", "RATE_LIMIT"}]),
            "owner_approvals_required": len([item for item in rows if item.state == "OWNER_APPROVAL_REQUIRED"]),
            "privacy_warnings": len([item for item in rows if item.state == "PRIVACY_REVIEW_REQUIRED"]),
            "contact_frequency_warnings": len([item for item in rows if item.state == "RATE_LIMIT"]),
            "do_not_contact_entries": [self.lead_out(item) for item in self.leads.values() if item.organization_id == organization_id and item.owner_user_id == owner_user_id and item.do_not_contact],
            "rejected_messages": [item.__dict__ for item in self.messages.values() if item.organization_id == organization_id and item.owner_user_id == owner_user_id and item.status not in {"DRAFTED", "MOCK_SENT"}],
            "policy_reasons": [{"decision_id": item.decision_id, "state": item.state, "explain": item.explain, "action": item.action} for item in rows[-50:]],
            "audit_trail": [{"at": item.at.isoformat(), "state": item.state, "explain": item.explain, "lead_id": item.lead_id} for item in rows[-50:]],
            "live": False,
        }

    def persist(self, store: V3Store | None = None) -> int:
        target = store or self.store or V3Store()
        self.store = target
        written = 0
        mapping = [
            ("nova_v3_leads", "lead_id", self.leads),
            ("nova_v3_outreach_messages", "message_id", self.messages),
            ("nova_v3_sequences", "sequence_id", self.sequences),
            ("nova_v3_demos", "demo_id", self.demos),
            ("nova_v3_quotes", "quote_id", self.quotes),
            ("nova_v3_customers", "customer_id", self.customers),
            ("nova_v3_shield_decisions", "decision_id", self.shield_log),
            ("nova_v3_growth_approvals", "approval_id", self.approvals),
        ]
        for table, key_name, rows in mapping:
            for row in rows.values():
                extra = {key_name: getattr(row, key_name), "organization_id": row.organization_id, "owner_user_id": row.owner_user_id}
                if table == "nova_v3_leads":
                    extra["fingerprint"] = row.fingerprint
                target.upsert(table, extra, row)
                written += 1
        return written


_GROWTH: GrowthKernel | None = None


def get_growth_kernel() -> GrowthKernel:
    global _GROWTH
    if _GROWTH is None:
        _GROWTH = GrowthKernel()
    return _GROWTH


def reset_growth_kernel() -> GrowthKernel:
    global _GROWTH
    _GROWTH = GrowthKernel()
    return _GROWTH
