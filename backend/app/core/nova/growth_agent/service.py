"""Growth Agent orchestration: CRM, chat, consent workflows, booking, audit."""

from __future__ import annotations

import hashlib
import html
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

# threading retained for in-process booking mutex (DB unique constraint is source of truth).

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.nova.growth_agent import appointments as appt_mod
from app.core.nova.growth_agent import workflows as wf_mod
from app.core.nova.growth_agent.commercial import UNIT_COST_MODEL, plan_catalog, quota_for
from app.core.nova.growth_agent.consent import consent_evidence, is_stop_message
from app.core.nova.growth_agent.errors import (
    ConsentRequiredError,
    DoubleBookError,
    GrowthAgentError,
    IdempotencyConflictError,
)
from app.core.nova.growth_agent.models import (
    LEAD_STATES,
    GaAppointment,
    GaAppointmentService,
    GaAuditEvent,
    GaAvailabilityRule,
    GaBusinessProfile,
    GaConsentRecord,
    GaContact,
    GaContactIdentity,
    GaConversation,
    GaConversationMessage,
    GaDeliveryAttempt,
    GaIdempotencyKey,
    GaIntegrationConnection,
    GaLeadEvent,
    GaUsageEvent,
    GaWidgetInstallation,
    GaWorkflowDefinition,
    GaWorkflowRun,
)
from app.core.nova.growth_agent.providers.mock_ai import MockAIAdapter
from app.core.nova.growth_agent.providers.mock_calendar import MockCalendarAdapter
from app.core.nova.growth_agent.providers.mock_email import MockEmailAdapter
from app.core.nova.growth_agent.providers.mock_sms import MockSmsAdapter
from app.core.nova.growth_agent.redact import redact_mapping, redact_text
from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema
from app.core.nova.growth_agent.widget_crypto import (
    domain_allowed,
    hash_token,
    mint_installation_token,
    verify_installation_token,
)

_BOOK_LOCK = threading.Lock()


def _id() -> str:
    return uuid4().hex


def _now() -> datetime:
    return datetime.utcnow()


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    return html.escape(text, quote=False)


def _fingerprint(*parts: str) -> str:
    raw = "|".join(p.strip().lower() for p in parts if p)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _hash_identity(channel: str, external_id: str) -> str:
    """Store contact identities as digests — never plaintext email/phone in identity rows."""
    normalized = (external_id or "").strip().lower()
    return hashlib.sha256(f"{channel}:{normalized}".encode("utf-8")).hexdigest()


_ACTIVE_BOOKING_STATUSES = ("confirmed", "rescheduled")


class GrowthAgentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.ai = MockAIAdapter()
        self.email = MockEmailAdapter()
        self.sms = MockSmsAdapter()
        self.calendar = MockCalendarAdapter()
        ensure_growth_agent_schema(bind=db.get_bind())

    # ── audit / usage / idempotency ──────────────────────────────────────────

    def audit(
        self,
        org_id: str,
        *,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        actor_user_id: str | None = None,
        summary: str = "",
        payload: dict | None = None,
    ) -> None:
        self.db.add(
            GaAuditEvent(
                id=_id(),
                organization_id=org_id,
                actor_user_id=actor_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                summary=redact_text(summary)[:500],
                payload_redacted_json=redact_mapping(payload or {}),
            )
        )
        self.db.flush()

    def record_usage(
        self,
        org_id: str,
        *,
        meter: str,
        quantity: float,
        unit_cost_usd: float = 0.0,
        provider: str = "mock",
        meta: dict | None = None,
    ) -> None:
        self.db.add(
            GaUsageEvent(
                id=_id(),
                organization_id=org_id,
                meter=meter,
                quantity=quantity,
                unit_cost_usd=unit_cost_usd,
                provider=provider,
                billed=False,
                meta_json=redact_mapping(meta or {}),
            )
        )

    def _idempotent_get(self, org_id: str, scope: str, key: str) -> dict | None:
        row = (
            self.db.query(GaIdempotencyKey)
            .filter_by(organization_id=org_id, scope=scope, key=key)
            .one_or_none()
        )
        return dict(row.response_json) if row else None

    def _idempotent_put(self, org_id: str, scope: str, key: str, response: dict) -> None:
        existing = (
            self.db.query(GaIdempotencyKey)
            .filter_by(organization_id=org_id, scope=scope, key=key)
            .one_or_none()
        )
        if existing:
            if existing.response_json != response:
                raise IdempotencyConflictError()
            return
        self.db.add(
            GaIdempotencyKey(
                id=_id(),
                organization_id=org_id,
                scope=scope,
                key=key,
                response_json=response,
            )
        )

    def _profile(self, org_id: str) -> GaBusinessProfile | None:
        return self.db.query(GaBusinessProfile).filter_by(organization_id=org_id).one_or_none()

    def _require_profile(self, org_id: str) -> GaBusinessProfile:
        profile = self._profile(org_id)
        if not profile:
            raise GrowthAgentError("PROFILE_REQUIRED", "Complete setup wizard first", http_status=400)
        return profile

    def _org_query(self, model, org_id: str):
        return self.db.query(model).filter(model.organization_id == org_id)

    # ── setup wizard / profile ───────────────────────────────────────────────

    def upsert_profile(
        self,
        org_id: str,
        owner_user_id: str,
        data: dict[str, Any],
        *,
        activate: bool = False,
        preview_only: bool = False,
    ) -> dict[str, Any]:
        name = (data.get("business_name") or "").strip()
        if not name:
            raise GrowthAgentError("VALIDATION", "business_name is required")
        tz = (data.get("timezone") or "America/Chicago").strip()
        faqs = data.get("faqs") or []
        for faq in faqs:
            if not str(faq.get("question") or "").strip() or not str(faq.get("answer") or "").strip():
                raise GrowthAgentError("VALIDATION", "Each FAQ needs question and answer")
        checklist = {
            "business_name": bool(name),
            "website": bool(data.get("website")),
            "timezone": bool(tz),
            "operating_hours": data.get("operating_hours") is not None,
            "services": bool(data.get("services")),
            "faqs": bool(faqs),
            "contact_and_handoff": bool(data.get("contact_email") or data.get("handoff_phone")),
            # Empty dict still counts as provided escalation config.
            "escalation_settings": data.get("escalation_settings") is not None,
        }
        preview = {
            "business_name": name,
            "website": data.get("website"),
            "timezone": tz,
            "faq_count": len(faqs),
            "services_count": len(data.get("services") or []),
            "checklist": checklist,
            "ready_to_activate": all(checklist.values()),
            "activated": False,
            "is_synthetic_demo": bool(data.get("is_synthetic_demo")),
        }
        if preview_only:
            return preview

        profile = self._profile(org_id)
        if profile is None:
            profile = GaBusinessProfile(
                id=_id(),
                organization_id=org_id,
                owner_user_id=owner_user_id,
                business_name=name,
            )
            self.db.add(profile)
        profile.business_name = name
        profile.website = data.get("website")
        profile.timezone = tz
        profile.operating_hours_json = data.get("operating_hours") or {}
        profile.services_json = data.get("services") or []
        profile.faqs_json = faqs
        profile.contact_email = data.get("contact_email")
        profile.handoff_phone = data.get("handoff_phone")
        profile.escalation_settings_json = data.get("escalation_settings") or {}
        profile.branding_json = data.get("branding") or {}
        profile.quiet_hours_json = data.get("quiet_hours") or {"enabled": True, "start": "21:00", "end": "08:00"}
        profile.plan_code = (data.get("plan_code") or profile.plan_code or "starter").lower()
        profile.setup_checklist_json = checklist
        profile.is_synthetic_demo = bool(data.get("is_synthetic_demo"))
        if activate:
            if not all(checklist.values()):
                raise GrowthAgentError("SETUP_INCOMPLETE", "Complete checklist before activation")
            profile.activated = True
            profile.agent_paused = False
            profile.agent_disabled = False
            self._ensure_default_workflows(org_id)
            self._ensure_default_services(org_id, profile)
        self.db.flush()
        self.audit(
            org_id,
            action="profile.upsert",
            entity_type="business_profile",
            entity_id=profile.id,
            actor_user_id=owner_user_id,
            summary="Business profile updated",
            payload={"activated": profile.activated},
        )
        self.db.commit()
        return self.get_profile(org_id)

    def get_profile(self, org_id: str) -> dict[str, Any]:
        profile = self._profile(org_id)
        if not profile:
            return {"configured": False, "organization_id": org_id}
        return {
            "configured": True,
            "id": profile.id,
            "organization_id": profile.organization_id,
            "business_name": profile.business_name,
            "website": profile.website,
            "timezone": profile.timezone,
            "operating_hours": profile.operating_hours_json,
            "services": profile.services_json,
            "faqs": profile.faqs_json,
            "contact_email": profile.contact_email,
            "handoff_phone": profile.handoff_phone,
            "escalation_settings": profile.escalation_settings_json,
            "branding": profile.branding_json,
            "plan_code": profile.plan_code,
            "quotas": quota_for(profile.plan_code),
            "agent_paused": profile.agent_paused,
            "agent_disabled": profile.agent_disabled,
            "activated": profile.activated,
            "setup_checklist": profile.setup_checklist_json,
            "quiet_hours": profile.quiet_hours_json,
            "is_synthetic_demo": profile.is_synthetic_demo,
        }

    def set_agent_state(
        self,
        org_id: str,
        *,
        paused: bool | None = None,
        disabled: bool | None = None,
        actor_user_id: str | None = None,
    ) -> dict[str, Any]:
        profile = self._require_profile(org_id)
        if paused is not None:
            profile.agent_paused = bool(paused)
        if disabled is not None:
            profile.agent_disabled = bool(disabled)
        self.audit(
            org_id,
            action="agent.state",
            entity_type="business_profile",
            entity_id=profile.id,
            actor_user_id=actor_user_id,
            summary=f"paused={profile.agent_paused} disabled={profile.agent_disabled}",
        )
        self.db.commit()
        return self.get_profile(org_id)

    def _ensure_default_workflows(self, org_id: str) -> None:
        for spec in wf_mod.DEFAULT_WORKFLOWS:
            exists = (
                self.db.query(GaWorkflowDefinition)
                .filter_by(organization_id=org_id, code=spec["code"])
                .one_or_none()
            )
            if exists:
                continue
            self.db.add(
                GaWorkflowDefinition(
                    id=_id(),
                    organization_id=org_id,
                    code=spec["code"],
                    name=spec["name"],
                    purpose=spec["purpose"],
                    steps_json=list(spec["steps"]),
                    requires_approval=True,
                    active=True,
                )
            )
        # Default-off integrations
        for provider in ("mock_email", "mock_sms", "google", "microsoft"):
            exists = (
                self.db.query(GaIntegrationConnection)
                .filter_by(organization_id=org_id, provider=provider)
                .one_or_none()
            )
            if exists:
                continue
            status = "mock_ready" if provider.startswith("mock_") else "disabled"
            self.db.add(
                GaIntegrationConnection(
                    id=_id(),
                    organization_id=org_id,
                    provider=provider,
                    status=status,
                    secret_ref=None,
                    config_json={"live": False},
                )
            )

    def _ensure_default_services(self, org_id: str, profile: GaBusinessProfile) -> None:
        services = profile.services_json or [{"code": "consult", "name": "Consultation", "duration_minutes": 30}]
        for svc in services:
            code = str(svc.get("code") or svc.get("name") or "service").lower().replace(" ", "_")[:80]
            exists = (
                self.db.query(GaAppointmentService)
                .filter_by(organization_id=org_id, code=code)
                .one_or_none()
            )
            if exists:
                continue
            self.db.add(
                GaAppointmentService(
                    id=_id(),
                    organization_id=org_id,
                    code=code,
                    name=str(svc.get("name") or code),
                    duration_minutes=int(svc.get("duration_minutes") or 30),
                    buffer_minutes=int(svc.get("buffer_minutes") or 10),
                )
            )
        # Weekday 9–17 availability if none
        if self._org_query(GaAvailabilityRule, org_id).count() == 0:
            for dow in range(0, 5):
                self.db.add(
                    GaAvailabilityRule(
                        id=_id(),
                        organization_id=org_id,
                        day_of_week=dow,
                        start_minute=9 * 60,
                        end_minute=17 * 60,
                    )
                )

    # ── widget ───────────────────────────────────────────────────────────────

    def create_widget_installation(
        self,
        org_id: str,
        *,
        domain: str,
        branding: dict | None = None,
        actor_user_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_profile(org_id)
        domain_n = domain.lower().strip()
        if not domain_n:
            raise GrowthAgentError("VALIDATION", "domain is required")
        existing = (
            self.db.query(GaWidgetInstallation)
            .filter_by(organization_id=org_id, domain=domain_n)
            .one_or_none()
        )
        installation_id = existing.id if existing else _id()
        token = mint_installation_token(
            organization_id=org_id,
            domain=domain_n,
            installation_id=installation_id,
        )
        if existing:
            existing.token_hash = hash_token(token)
            existing.branding_json = branding or existing.branding_json or {}
            existing.active = True
            row = existing
        else:
            row = GaWidgetInstallation(
                id=installation_id,
                organization_id=org_id,
                domain=domain_n,
                token_hash=hash_token(token),
                branding_json=branding or {},
                active=True,
            )
            self.db.add(row)
        self.audit(
            org_id,
            action="widget.create",
            entity_type="widget_installation",
            entity_id=installation_id,
            actor_user_id=actor_user_id,
            summary=f"Widget for domain={domain_n}",
        )
        self.db.commit()
        return {
            "installation_id": installation_id,
            "domain": domain_n,
            "token": token,
            "embed_snippet": (
                f'<script src="/static/nova-growth/widget.js" '
                f'data-amicor-growth-token="{token}" async></script>'
            ),
            "note": "Store token securely. Token is shown once in API responses for owner setup.",
            "rotated": bool(existing),
        }

    def _check_rate(self, *, org_id: str, installation_id: str, limit: int) -> None:
        """Atomic shared rate limit suitable for multiple workers (survives restart).

        Uses a short-lived session + commit so concurrent workers observe increments
        immediately without committing the caller's broader unit of work.
        """
        from sqlalchemy.orm import sessionmaker

        from app.core.nova.growth_agent.rate_limit import check_and_increment

        Session = sessionmaker(bind=self.db.get_bind())
        rl_db = Session()
        try:
            check_and_increment(
                rl_db,
                organization_id=org_id,
                bucket_key=f"widget:{installation_id}",
                limit=limit,
                window_seconds=60,
                commit=True,
            )
        finally:
            rl_db.close()

    def widget_chat(
        self,
        *,
        token: str,
        origin: str | None,
        message: str,
        conversation_id: str | None = None,
        visitor_name: str | None = None,
        visitor_email: str | None = None,
        consent_marketing: bool = False,
        consent_transactional: bool = False,
    ) -> dict[str, Any]:
        claims = verify_installation_token(token)
        org_id = claims["organization_id"]
        installation = (
            self.db.query(GaWidgetInstallation)
            .filter_by(id=claims["installation_id"], organization_id=org_id)
            .one_or_none()
        )
        if not installation or not installation.active:
            raise GrowthAgentError("INVALID_WIDGET_TOKEN", "Installation inactive", http_status=401)
        if hash_token(token) != installation.token_hash:
            raise GrowthAgentError("INVALID_WIDGET_TOKEN", "Token mismatch", http_status=401)
        # Fail closed: Origin/Referer (or explicit embed origin) is required.
        if not (origin or "").strip():
            raise GrowthAgentError(
                "ORIGIN_REQUIRED",
                "Origin or Referer required for widget chat",
                http_status=403,
            )
        if not domain_allowed(installation.domain, origin):
            raise GrowthAgentError("ORIGIN_DENIED", "Origin not allowed for this installation", http_status=403)
        self._check_rate(
            org_id=org_id,
            installation_id=installation.id,
            limit=installation.rate_limit_per_minute,
        )

        profile = self._require_profile(org_id)
        if not profile.activated:
            raise GrowthAgentError(
                "NOT_ACTIVATED",
                "Business profile must be activated before public chat",
                http_status=403,
            )
        if profile.agent_disabled:
            raise GrowthAgentError("AGENT_DISABLED", "Agent disabled", http_status=403)

        safe_message = _strip_html(message).strip()
        if not safe_message:
            raise GrowthAgentError("VALIDATION", "message is required")

        contact = None
        if visitor_email or visitor_name:
            if not (consent_transactional or consent_marketing):
                raise ConsentRequiredError(
                    "Consent required before storing contact details"
                )
            contact = self._upsert_contact(
                org_id,
                name=visitor_name,
                email=visitor_email,
                channel="web",
                source="widget",
                consent_marketing=consent_marketing,
                consent_transactional=consent_transactional,
                is_synthetic_demo=bool(profile.is_synthetic_demo),
            )

        conv = None
        if conversation_id:
            conv = (
                self._org_query(GaConversation, org_id)
                .filter_by(id=conversation_id)
                .one_or_none()
            )
        if conv is None:
            conv = GaConversation(
                id=_id(),
                organization_id=org_id,
                contact_id=contact.id if contact else None,
                widget_installation_id=installation.id,
                status="open",
                handler="human" if profile.agent_paused else "ai",
                is_synthetic_demo=bool(profile.is_synthetic_demo),
                subject=safe_message[:120],
            )
            self.db.add(conv)
            self.db.flush()

        self.db.add(
            GaConversationMessage(
                id=_id(),
                organization_id=org_id,
                conversation_id=conv.id,
                role="visitor",
                content=safe_message,
            )
        )

        if is_stop_message(safe_message) and contact:
            self.record_consent(
                org_id,
                contact_id=contact.id,
                channel="sms",
                purpose="marketing",
                status="opted_out",
                collection_source="widget_stop",
                actor_user_id=None,
            )
            self.record_consent(
                org_id,
                contact_id=contact.id,
                channel="email",
                purpose="marketing",
                status="opted_out",
                collection_source="widget_stop",
                actor_user_id=None,
            )
            reply = {
                "answer": "You are opted out of marketing messages. A human can still help with your account.",
                "grounded": False,
                "disclosure": f"I am an AI assistant for {profile.business_name}.",
            }
        elif profile.agent_paused or conv.handler == "human":
            reply = {
                "answer": "An owner has paused the AI assistant. A human will follow up.",
                "grounded": False,
                "escalate": True,
                "disclosure": f"I am an AI assistant for {profile.business_name}.",
            }
            conv.handler = "human"
            conv.status = "handed_off"
        else:
            usage_tokens = (
                self._org_query(GaUsageEvent, org_id)
                .filter_by(meter="tokens")
                .count()
            )  # coarse stand-in for monthly usage in MVP
            caps = quota_for(profile.plan_code)
            reply = self.ai.complete(
                question=safe_message,
                faqs=list(profile.faqs_json or []),
                business_name=profile.business_name,
                usage_tokens=usage_tokens * 50,
                token_cap=int(caps.get("ai_tokens_per_month") or 100_000),
            )
            self.record_usage(
                org_id,
                meter="tokens",
                quantity=float(reply.get("tokens_used") or 0),
                unit_cost_usd=float(reply.get("unit_cost_usd") or 0),
                provider="mock_ai",
            )
            if reply.get("escalate"):
                conv.handler = "human"
                conv.status = "handed_off"

        assistant_text = f"{reply.get('disclosure')} {reply.get('answer')}".strip()
        self.db.add(
            GaConversationMessage(
                id=_id(),
                organization_id=org_id,
                conversation_id=conv.id,
                role="assistant",
                content=assistant_text,
                grounded=bool(reply.get("grounded")),
                faq_id=reply.get("faq_id"),
            )
        )
        self.audit(
            org_id,
            action="widget.chat",
            entity_type="conversation",
            entity_id=conv.id,
            summary="Widget chat turn",
            payload={"grounded": reply.get("grounded"), "handler": conv.handler},
        )
        self.db.commit()
        return {
            "conversation_id": conv.id,
            "handler": conv.handler,
            "status": conv.status,
            "reply": assistant_text,
            "grounded": bool(reply.get("grounded")),
            "contact_id": contact.id if contact else None,
            "ai_disclosed": True,
        }

    # ── contacts / CRM ───────────────────────────────────────────────────────

    def _upsert_contact(
        self,
        org_id: str,
        *,
        name: str | None,
        email: str | None = None,
        phone: str | None = None,
        channel: str = "web",
        source: str = "api",
        consent_marketing: bool = False,
        consent_transactional: bool = False,
        is_synthetic_demo: bool = False,
    ) -> GaContact:
        email_n = (email or "").strip().lower()
        phone_n = re.sub(r"\D", "", phone or "")
        fp = _fingerprint(email_n, phone_n, name or "")
        existing = None
        if email_n:
            email_hash = _hash_identity("email", email_n)
            ident = (
                self.db.query(GaContactIdentity)
                .filter_by(organization_id=org_id, channel="email", external_id=email_hash)
                .one_or_none()
            )
            if ident:
                existing = self._org_query(GaContact, org_id).filter_by(id=ident.contact_id).one_or_none()
        if existing is None and phone_n:
            phone_hash = _hash_identity("phone", phone_n)
            ident = (
                self.db.query(GaContactIdentity)
                .filter_by(organization_id=org_id, channel="phone", external_id=phone_hash)
                .one_or_none()
            )
            if ident:
                existing = self._org_query(GaContact, org_id).filter_by(id=ident.contact_id).one_or_none()
        if existing is None and fp:
            existing = (
                self._org_query(GaContact, org_id)
                .filter_by(dedupe_fingerprint=fp)
                .one_or_none()
            )
        safe_name = _strip_html(name).strip() if name else None
        if existing:
            contact = existing
            if safe_name and not contact.display_name:
                contact.display_name = safe_name
        else:
            contact = GaContact(
                id=_id(),
                organization_id=org_id,
                display_name=safe_name,
                lead_state="new",
                dedupe_fingerprint=fp,
                is_synthetic_demo=is_synthetic_demo,
            )
            self.db.add(contact)
            self.db.flush()
            self.db.add(
                GaLeadEvent(
                    id=_id(),
                    organization_id=org_id,
                    contact_id=contact.id,
                    event_type="lead_created",
                    payload_json={"source": source},
                )
            )
        if email_n:
            self._ensure_identity(org_id, contact.id, "email", email_n)
        if phone_n:
            self._ensure_identity(org_id, contact.id, "phone", phone_n)
        if consent_transactional:
            self._write_consent(
                org_id,
                contact.id,
                channel=channel if channel in {"email", "sms", "web"} else "web",
                purpose="transactional",
                status="opted_in",
                collection_source=source,
            )
        if consent_marketing:
            self._write_consent(
                org_id,
                contact.id,
                channel="email" if email_n else channel,
                purpose="marketing",
                status="opted_in",
                collection_source=source,
            )
        self.db.flush()
        return contact

    def _ensure_identity(self, org_id: str, contact_id: str, channel: str, external_id: str) -> None:
        digest = _hash_identity(channel, external_id)
        exists = (
            self.db.query(GaContactIdentity)
            .filter_by(organization_id=org_id, channel=channel, external_id=digest)
            .one_or_none()
        )
        if exists:
            return
        self.db.add(
            GaContactIdentity(
                id=_id(),
                organization_id=org_id,
                contact_id=contact_id,
                channel=channel,
                external_id=digest,
                verified=False,
            )
        )

    def list_leads(self, org_id: str, *, q: str | None = None, state: str | None = None) -> list[dict]:
        query = self._org_query(GaContact, org_id)
        if state:
            query = query.filter(GaContact.lead_state == state)
        rows = query.order_by(GaContact.updated_at.desc()).limit(200).all()
        out = []
        for row in rows:
            if q:
                hay = f"{row.display_name or ''} {row.notes or ''}".lower()
                if q.lower() not in hay:
                    continue
            out.append(self._contact_dict(row))
        return out

    def _contact_dict(self, row: GaContact) -> dict[str, Any]:
        idents = (
            self.db.query(GaContactIdentity)
            .filter_by(organization_id=row.organization_id, contact_id=row.id)
            .all()
        )
        return {
            "id": row.id,
            "display_name": row.display_name,
            "lead_state": row.lead_state,
            "notes": row.notes,
            "do_not_contact": row.do_not_contact,
            "is_synthetic_demo": row.is_synthetic_demo,
            "identities": [
                {
                    "channel": i.channel,
                    "external_id_redacted": "[REDACTED]",
                    "external_id_hashed": True,
                    "external_id_hint": "",
                }
                for i in idents
            ],
            "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None,
        }

    def update_lead(
        self,
        org_id: str,
        contact_id: str,
        *,
        lead_state: str | None = None,
        notes: str | None = None,
        actor_user_id: str | None = None,
    ) -> dict[str, Any]:
        contact = self._org_query(GaContact, org_id).filter_by(id=contact_id).one_or_none()
        if not contact:
            raise GrowthAgentError("NOT_FOUND", "Contact not found", http_status=404)
        if lead_state:
            if lead_state not in LEAD_STATES:
                raise GrowthAgentError("VALIDATION", f"lead_state must be one of {LEAD_STATES}")
            contact.lead_state = lead_state
            self.db.add(
                GaLeadEvent(
                    id=_id(),
                    organization_id=org_id,
                    contact_id=contact.id,
                    event_type="state_changed",
                    payload_json={"lead_state": lead_state},
                )
            )
        if notes is not None:
            contact.notes = _strip_html(notes)[:4000]
        self.audit(
            org_id,
            action="lead.update",
            entity_type="contact",
            entity_id=contact.id,
            actor_user_id=actor_user_id,
            summary="Lead updated",
        )
        self.db.commit()
        return self._contact_dict(contact)

    # ── consent ──────────────────────────────────────────────────────────────

    def _write_consent(
        self,
        org_id: str,
        contact_id: str,
        *,
        channel: str,
        purpose: str,
        status: str,
        collection_source: str,
    ) -> GaConsentRecord:
        row = GaConsentRecord(
            id=_id(),
            organization_id=org_id,
            contact_id=contact_id,
            channel=channel,
            purpose=purpose,
            status=status,
            collection_source=collection_source,
            evidence_json=consent_evidence(
                source=collection_source,
                method="explicit_checkbox" if status == "opted_in" else "stop_keyword",
                text_shown="Consent captured via Growth Agent controls",
            ),
        )
        self.db.add(row)
        if status == "opted_out":
            contact = self._org_query(GaContact, org_id).filter_by(id=contact_id).one_or_none()
            if contact and purpose == "marketing":
                # Channel-specific marketing opt-out must not blanket DNC transactional paths.
                # Only explicit STOP keyword sources mark the contact do-not-contact.
                if collection_source in {
                    "widget_stop",
                    "sms_stop",
                    "email_stop",
                    "owner_global_stop",
                }:
                    contact.do_not_contact = True
        return row

    def record_consent(
        self,
        org_id: str,
        *,
        contact_id: str,
        channel: str,
        purpose: str,
        status: str,
        collection_source: str,
        actor_user_id: str | None,
    ) -> dict[str, Any]:
        contact = self._org_query(GaContact, org_id).filter_by(id=contact_id).one_or_none()
        if not contact:
            raise GrowthAgentError("NOT_FOUND", "Contact not found", http_status=404)
        if status not in {"opted_in", "opted_out"}:
            raise GrowthAgentError("VALIDATION", "status must be opted_in or opted_out")
        row = self._write_consent(
            org_id,
            contact_id,
            channel=channel,
            purpose=purpose,
            status=status,
            collection_source=collection_source,
        )
        self.audit(
            org_id,
            action="consent.record",
            entity_type="consent",
            entity_id=row.id,
            actor_user_id=actor_user_id,
            summary=f"{channel}/{purpose}={status}",
        )
        self.db.commit()
        return {
            "id": row.id,
            "contact_id": contact_id,
            "channel": channel,
            "purpose": purpose,
            "status": status,
            "collection_source": collection_source,
        }

    def consent_records_for(self, org_id: str, contact_id: str) -> list[dict[str, Any]]:
        rows = (
            self._org_query(GaConsentRecord, org_id)
            .filter_by(contact_id=contact_id)
            .order_by(GaConsentRecord.recorded_at.asc())
            .all()
        )
        return [
            {
                "id": r.id,
                "channel": r.channel,
                "purpose": r.purpose,
                "status": r.status,
                "collection_source": r.collection_source,
                "recorded_at": r.recorded_at.isoformat() + "Z" if r.recorded_at else None,
            }
            for r in rows
        ]

    # ── inbox / conversations ────────────────────────────────────────────────

    def list_conversations(self, org_id: str) -> list[dict[str, Any]]:
        rows = self._org_query(GaConversation, org_id).order_by(GaConversation.updated_at.desc()).limit(100).all()
        return [
            {
                "id": c.id,
                "contact_id": c.contact_id,
                "status": c.status,
                "handler": c.handler,
                "subject": c.subject,
                "is_synthetic_demo": c.is_synthetic_demo,
                "updated_at": c.updated_at.isoformat() + "Z" if c.updated_at else None,
            }
            for c in rows
        ]

    def get_conversation(self, org_id: str, conversation_id: str) -> dict[str, Any]:
        conv = self._org_query(GaConversation, org_id).filter_by(id=conversation_id).one_or_none()
        if not conv:
            raise GrowthAgentError("NOT_FOUND", "Conversation not found", http_status=404)
        messages = (
            self._org_query(GaConversationMessage, org_id)
            .filter_by(conversation_id=conversation_id)
            .order_by(GaConversationMessage.created_at.asc())
            .all()
        )
        return {
            "id": conv.id,
            "status": conv.status,
            "handler": conv.handler,
            "contact_id": conv.contact_id,
            "is_synthetic_demo": conv.is_synthetic_demo,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "grounded": m.grounded,
                    "faq_id": m.faq_id,
                    "created_at": m.created_at.isoformat() + "Z" if m.created_at else None,
                }
                for m in messages
            ],
        }

    def handoff_conversation(
        self,
        org_id: str,
        conversation_id: str,
        *,
        actor_user_id: str | None = None,
    ) -> dict[str, Any]:
        conv = self._org_query(GaConversation, org_id).filter_by(id=conversation_id).one_or_none()
        if not conv:
            raise GrowthAgentError("NOT_FOUND", "Conversation not found", http_status=404)
        conv.handler = "human"
        conv.status = "handed_off"
        self.db.add(
            GaConversationMessage(
                id=_id(),
                organization_id=org_id,
                conversation_id=conv.id,
                role="system",
                content="Conversation handed off to human.",
            )
        )
        self.audit(
            org_id,
            action="conversation.handoff",
            entity_type="conversation",
            entity_id=conv.id,
            actor_user_id=actor_user_id,
            summary="Handed off to human",
        )
        self.db.commit()
        return self.get_conversation(org_id, conversation_id)

    # ── workflows ────────────────────────────────────────────────────────────

    def preview_workflow(
        self,
        org_id: str,
        *,
        workflow_code: str,
        contact_id: str,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        profile = self._require_profile(org_id)
        wf = (
            self.db.query(GaWorkflowDefinition)
            .filter_by(organization_id=org_id, code=workflow_code, active=True)
            .one_or_none()
        )
        if not wf:
            raise GrowthAgentError("NOT_FOUND", "Workflow not found", http_status=404)
        contact = self._org_query(GaContact, org_id).filter_by(id=contact_id).one_or_none()
        if not contact:
            raise GrowthAgentError("NOT_FOUND", "Contact not found", http_status=404)
        preview = wf_mod.build_preview(
            workflow={"code": wf.code, "purpose": wf.purpose, "steps": wf.steps_json},
            business_name=profile.business_name,
            contact_id=contact_id,
            quiet_hours=profile.quiet_hours_json,
            tz_name=profile.timezone,
        )
        run = GaWorkflowRun(
            id=_id(),
            organization_id=org_id,
            workflow_id=wf.id,
            contact_id=contact_id,
            conversation_id=conversation_id,
            status="preview",
            dry_run=True,
            preview_json=preview,
        )
        self.db.add(run)
        self.audit(
            org_id,
            action="workflow.preview",
            entity_type="workflow_run",
            entity_id=run.id,
            summary=f"Preview {workflow_code}",
        )
        self.db.commit()
        return {"run_id": run.id, "preview": preview, "status": run.status}

    def approve_and_execute_workflow(
        self,
        org_id: str,
        *,
        run_id: str,
        dry_run: bool = True,
        actor_user_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        key = idempotency_key or f"wf-exec-{run_id}-{dry_run}"
        cached = self._idempotent_get(org_id, "workflow_execute", key)
        if cached:
            return cached

        run = self._org_query(GaWorkflowRun, org_id).filter_by(id=run_id).one_or_none()
        if not run:
            raise GrowthAgentError("NOT_FOUND", "Workflow run not found", http_status=404)
        profile = self._require_profile(org_id)
        wf = self.db.query(GaWorkflowDefinition).filter_by(id=run.workflow_id, organization_id=org_id).one()
        contact = self._org_query(GaContact, org_id).filter_by(id=run.contact_id).one()
        consents = self.consent_records_for(org_id, contact.id)
        attempts = []
        for msg in (run.preview_json or {}).get("messages") or []:
            channel = msg["channel"]
            delivery_key = f"{run.id}:{msg.get('step_id')}:{channel}"
            existing_attempt = (
                self.db.query(GaDeliveryAttempt)
                .filter_by(organization_id=org_id, idempotency_key=delivery_key)
                .one_or_none()
            )
            try:
                wf_mod.validate_send_allowed(
                    purpose=wf.purpose,
                    channel=channel if channel != "web" else "email",
                    consent_records=consents,
                    do_not_contact=contact.do_not_contact,
                    agent_paused=profile.agent_paused,
                    agent_disabled=profile.agent_disabled,
                )
            except (ConsentRequiredError, GrowthAgentError) as exc:
                if existing_attempt and existing_attempt.status == "suppressed":
                    attempts.append(
                        {
                            "status": "suppressed",
                            "id": existing_attempt.id,
                            "error": getattr(exc, "code", "SUPPRESSED"),
                            "deduped": True,
                        }
                    )
                else:
                    attempt = existing_attempt or GaDeliveryAttempt(
                        id=_id(),
                        organization_id=org_id,
                        workflow_run_id=run.id,
                        channel=channel,
                        provider="mock",
                        status="suppressed",
                        idempotency_key=delivery_key,
                        cost_estimate_usd=0.0,
                        error_code=getattr(exc, "code", "SUPPRESSED"),
                        payload_redacted_json={"reason": redact_text(str(exc))},
                    )
                    if existing_attempt:
                        attempt.status = "suppressed"
                        attempt.error_code = getattr(exc, "code", "SUPPRESSED")
                    else:
                        self.db.add(attempt)
                    attempts.append(
                        {"status": "suppressed", "id": attempt.id, "error": getattr(exc, "code", "SUPPRESSED")}
                    )
                run.status = "suppressed"
                run.stop_reason = getattr(exc, "code", "SUPPRESSED")
                continue

            if existing_attempt and existing_attempt.status in {"sent_mock", "suppressed"}:
                attempts.append(
                    {"status": existing_attempt.status, "id": existing_attempt.id, "deduped": True}
                )
                continue

            # Persist queued row first so a crash mid-send can be recovered on restart.
            if existing_attempt and existing_attempt.status in {"queued", "retrying", "running"}:
                attempt = existing_attempt
            else:
                attempt = GaDeliveryAttempt(
                    id=_id(),
                    organization_id=org_id,
                    workflow_run_id=run.id,
                    channel=channel,
                    provider="mock",
                    status="queued",
                    idempotency_key=delivery_key,
                    cost_estimate_usd=float(msg.get("cost_estimate_usd") or 0),
                    payload_redacted_json={"body_preview": "[REDACTED]"},
                    available_at=_now(),
                    max_attempts=5,
                )
                self.db.add(attempt)
                self.db.flush()

            from app.core.nova.growth_agent.flags import background_worker_enabled

            if background_worker_enabled() and attempt.status in {"queued", "retrying"}:
                # Defer to durable mock worker — do not send inline.
                attempts.append(
                    {
                        "status": attempt.status,
                        "id": attempt.id,
                        "provider": "mock",
                        "queued_for_worker": True,
                        "live_send": False,
                    }
                )
                continue

            processed = self._process_delivery_attempt(
                org_id,
                attempt,
                profile=profile,
                channel=channel,
                body=msg.get("body_preview"),
                dry_run=dry_run,
            )
            attempts.append(processed)

        if run.status != "suppressed":
            if any(a.get("queued_for_worker") for a in attempts):
                run.status = "approved"
            else:
                run.status = "completed" if attempts else "failed"
        run.dry_run = dry_run
        response = {
            "run_id": run.id,
            "status": run.status,
            "dry_run": dry_run,
            "attempts": attempts,
            "stop_reason": run.stop_reason,
            "live_send": False,
            "mock_worker_deferred": any(a.get("queued_for_worker") for a in attempts),
        }
        self._idempotent_put(org_id, "workflow_execute", key, response)
        self.audit(
            org_id,
            action="workflow.execute",
            entity_type="workflow_run",
            entity_id=run.id,
            actor_user_id=actor_user_id,
            summary=f"Execute dry_run={dry_run} status={run.status}",
        )
        self.db.commit()
        return response

    def _process_delivery_attempt(
        self,
        org_id: str,
        attempt: GaDeliveryAttempt,
        *,
        profile: GaBusinessProfile,
        channel: str,
        body: str | None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        adapter = self.sms if channel == "sms" else self.email
        result = adapter.send(
            channel=channel,
            payload={
                "body": body,
                "subject": f"{profile.business_name} update",
                "live": False,
            },
        )
        # Live flags are hard-off; dry-run and "live" execute both stay mock.
        status = "sent_mock"
        attempt.status = status
        attempt.provider = result.provider
        attempt.cost_estimate_usd = float(result.cost_estimate_usd or attempt.cost_estimate_usd or 0)
        attempt.payload_redacted_json = redact_mapping(result.meta)
        attempt.attempt_number = int(attempt.attempt_number or 1)
        attempt.error_code = None
        self.record_usage(
            org_id,
            meter=channel,
            quantity=1,
            unit_cost_usd=attempt.cost_estimate_usd,
            provider=result.provider,
        )
        return {
            "status": status,
            "id": attempt.id,
            "provider": result.provider,
            "recovered": attempt.attempt_number > 1,
            "dry_run": dry_run,
        }

    def recover_pending_deliveries(
        self,
        org_id: str,
        *,
        actor_user_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Reclaim queued/retrying delivery attempts after process restart (mock transport only)."""
        profile = self._require_profile(org_id)
        pending = (
            self._org_query(GaDeliveryAttempt, org_id)
            .filter(GaDeliveryAttempt.status.in_(["queued", "retrying"]))
            .order_by(GaDeliveryAttempt.created_at.asc())
            .limit(max(1, min(limit, 200)))
            .all()
        )
        recovered = []
        for attempt in pending:
            run = self._org_query(GaWorkflowRun, org_id).filter_by(id=attempt.workflow_run_id).one_or_none()
            body = None
            if run and isinstance(run.preview_json, dict):
                for msg in run.preview_json.get("messages") or []:
                    key = f"{run.id}:{msg.get('step_id')}:{msg.get('channel')}"
                    if key == attempt.idempotency_key:
                        body = msg.get("body_preview")
                        break
            attempt.attempt_number = int(attempt.attempt_number or 1) + 1
            processed = self._process_delivery_attempt(
                org_id,
                attempt,
                profile=profile,
                channel=attempt.channel,
                body=body,
                dry_run=True,
            )
            if run and run.status in {"preview", "awaiting_approval", "approved", "running", "failed"}:
                run.status = "completed"
            recovered.append(processed)

        self.audit(
            org_id,
            action="workflow.recover",
            entity_type="delivery_attempt",
            actor_user_id=actor_user_id,
            summary=f"Recovered {len(recovered)} pending mock deliveries after restart",
            payload={"recovered_count": len(recovered)},
        )
        self.db.commit()
        from app.core.nova.growth_agent.flags import background_worker_enabled

        return {
            "recovered_count": len(recovered),
            "attempts": recovered,
            "live_send": False,
            "background_worker_mock": background_worker_enabled(),
            "note": "Manual reclaim path for mock deliveries. Live transports remain hard-off.",
        }

    def diagnostics(self, org_id: str) -> dict[str, Any]:
        """Owner diagnostics: worker status, pending/failed jobs, retention preview."""
        from app.core.nova.growth_agent.flags import (
            background_worker_enabled,
            retention_delete_enabled,
            retention_schedule_enabled,
        )
        from app.core.nova.growth_agent.models import GaRetentionScheduleRun, GaWorkerHeartbeat
        from app.core.nova.growth_agent.retention import preview_retention
        from app.core.nova.growth_agent.retention_schedule import (
            current_window_key,
            effective_mode,
            get_runtime_scheduler,
            recent_runs_for_org,
        )
        from app.core.nova.growth_agent.worker import get_runtime_worker

        pending = (
            self._org_query(GaDeliveryAttempt, org_id)
            .filter(GaDeliveryAttempt.status.in_(["queued", "retrying", "running"]))
            .count()
        )
        failed = (
            self._org_query(GaDeliveryAttempt, org_id)
            .filter(GaDeliveryAttempt.status == "failed")
            .count()
        )
        sent_mock = (
            self._org_query(GaDeliveryAttempt, org_id)
            .filter(GaDeliveryAttempt.status == "sent_mock")
            .count()
        )
        suppressed = (
            self._org_query(GaDeliveryAttempt, org_id)
            .filter(GaDeliveryAttempt.status == "suppressed")
            .count()
        )
        heartbeats = (
            self.db.query(GaWorkerHeartbeat)
            .order_by(GaWorkerHeartbeat.last_beat_at.desc())
            .limit(10)
            .all()
        )
        runtime = get_runtime_worker()
        scheduler = get_runtime_scheduler()
        retention_preview = preview_retention(self.db, org_id, batch_limit=100)
        schedule_pending = (
            self.db.query(GaRetentionScheduleRun)
            .filter(
                GaRetentionScheduleRun.organization_id == org_id,
                GaRetentionScheduleRun.status.in_(["pending", "running", "failed"]),
            )
            .count()
        )
        return {
            "organization_id": org_id,
            "mock_processing_only": True,
            "live_delivery": False,
            "worker": {
                "mock_worker_flag": background_worker_enabled(),
                "live_worker": False,
                "runtime_worker_id": runtime.worker_id if runtime else None,
                "runtime_stats": dict(runtime.stats) if runtime else None,
                "heartbeats": [
                    {
                        "worker_id": h.worker_id,
                        "status": h.status,
                        "jobs_claimed": h.jobs_claimed,
                        "jobs_completed": h.jobs_completed,
                        "jobs_failed": h.jobs_failed,
                        "last_beat_at": h.last_beat_at.isoformat() + "Z" if h.last_beat_at else None,
                        "meta": h.meta_json,
                    }
                    for h in heartbeats
                ],
            },
            "jobs": {
                "pending_queued_retrying_running": pending,
                "failed": failed,
                "sent_mock": sent_mock,
                "suppressed": suppressed,
            },
            "retention_preview": retention_preview,
            "retention_schedule": {
                "schedule_enabled": retention_schedule_enabled(),
                "delete_enabled": retention_delete_enabled(),
                "mode": effective_mode(),
                "dry_run_default": True,
                "current_window_key": current_window_key(),
                "pending_or_retryable_runs": schedule_pending,
                "runtime_scheduler_id": scheduler.scheduler_id if scheduler else None,
                "runtime_stats": dict(scheduler.stats) if scheduler else None,
                "recent_runs": recent_runs_for_org(self.db, org_id, limit=5),
                "note": (
                    "Scheduled retention is default-off. When enabled it dry-runs unless "
                    "NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED is separately set."
                ),
            },
            "retention_delete_enabled": retention_delete_enabled(),
            "distinction": {
                "mock": "Worker/recover paths only mark sent_mock via mock adapters.",
                "real": "REAL_EMAIL_SEND/REAL_SMS_SEND remain hard-coded False.",
            },
        }

    def retention_preview(self, org_id: str, *, batch_limit: int = 500) -> dict[str, Any]:
        from app.core.nova.growth_agent.retention import preview_retention

        return preview_retention(self.db, org_id, batch_limit=batch_limit)

    def retention_execute(
        self,
        org_id: str,
        *,
        batch_limit: int = 500,
        actor_user_id: str | None = None,
    ) -> dict[str, Any]:
        from app.core.nova.growth_agent.retention import execute_retention

        return execute_retention(
            self.db,
            org_id,
            batch_limit=batch_limit,
            actor_user_id=actor_user_id,
        )

    # ── appointments ─────────────────────────────────────────────────────────

    def list_availability(
        self,
        org_id: str,
        *,
        service_code: str,
        day: str,
    ) -> dict[str, Any]:
        profile = self._require_profile(org_id)
        service = (
            self.db.query(GaAppointmentService)
            .filter_by(organization_id=org_id, code=service_code, active=True)
            .one_or_none()
        )
        if not service:
            raise GrowthAgentError("NOT_FOUND", "Service not found", http_status=404)
        day_local = datetime.strptime(day, "%Y-%m-%d")
        rules = [
            {
                "day_of_week": r.day_of_week,
                "start_minute": r.start_minute,
                "end_minute": r.end_minute,
                "exception_date": r.exception_date,
                "is_closed": r.is_closed,
            }
            for r in self._org_query(GaAvailabilityRule, org_id).all()
        ]
        existing_rows = (
            self._org_query(GaAppointment, org_id)
            .filter(GaAppointment.status.in_(_ACTIVE_BOOKING_STATUSES))
            .all()
        )
        existing = [
            {"starts_at_utc": a.starts_at_utc, "ends_at_utc": a.ends_at_utc, "status": a.status}
            for a in existing_rows
        ]
        slots = appt_mod.slots_for_day(
            day_local=day_local,
            rules=rules,
            duration_minutes=service.duration_minutes,
            buffer_minutes=service.buffer_minutes,
            existing=existing,
            tz_name=profile.timezone,
        )
        return {"service_code": service_code, "day": day, "timezone": profile.timezone, "slots": slots}

    def book_appointment(
        self,
        org_id: str,
        *,
        contact_id: str,
        service_code: str,
        starts_at_utc: str,
        idempotency_key: str,
        conversation_id: str | None = None,
        actor_user_id: str | None = None,
        is_synthetic_demo: bool = False,
    ) -> dict[str, Any]:
        cached = self._idempotent_get(org_id, "appointment_book", idempotency_key)
        if cached:
            return cached
        profile = self._require_profile(org_id)
        contact = self._org_query(GaContact, org_id).filter_by(id=contact_id).one_or_none()
        if not contact:
            raise GrowthAgentError("NOT_FOUND", "Contact not found", http_status=404)
        # Never downgrade a synthetic profile or synthetic lead to a real booking.
        is_synthetic_demo = bool(is_synthetic_demo or profile.is_synthetic_demo or contact.is_synthetic_demo)
        service = (
            self.db.query(GaAppointmentService)
            .filter_by(organization_id=org_id, code=service_code, active=True)
            .one_or_none()
        )
        if not service:
            raise GrowthAgentError("NOT_FOUND", "Service not found", http_status=404)
        start = appt_mod.parse_iso_utc(starts_at_utc)
        end = start + timedelta(minutes=service.duration_minutes)

        with _BOOK_LOCK:
            existing_rows = (
                self._org_query(GaAppointment, org_id)
                .filter(GaAppointment.status.in_(_ACTIVE_BOOKING_STATUSES))
                .all()
            )
            existing = [
                {"starts_at_utc": a.starts_at_utc, "ends_at_utc": a.ends_at_utc, "status": a.status}
                for a in existing_rows
            ]
            appt_mod.assert_no_overlap(
                starts_at_utc=start,
                ends_at_utc=end,
                existing=existing,
                buffer_minutes=service.buffer_minutes,
            )
            # Reuse a cancelled row at the same unique slot so cancel→rebook works
            # without relaxing the DB unique constraint.
            start_naive = start.replace(tzinfo=None)
            end_naive = end.replace(tzinfo=None)
            cancelled = (
                self._org_query(GaAppointment, org_id)
                .filter_by(
                    service_id=service.id,
                    starts_at_utc=start_naive,
                    status="cancelled",
                )
                .one_or_none()
            )
            if cancelled:
                cancelled.contact_id = contact_id
                cancelled.conversation_id = conversation_id
                cancelled.ends_at_utc = end_naive
                cancelled.status = "confirmed"
                cancelled.idempotency_key = idempotency_key
                cancelled.timezone = profile.timezone
                cancelled.is_synthetic_demo = is_synthetic_demo
                appt = cancelled
                event_type = "appointment_rebooked"
                audit_action = "appointment.rebook"
                summary = "Cancelled appointment slot rebooked"
            else:
                appt = GaAppointment(
                    id=_id(),
                    organization_id=org_id,
                    contact_id=contact_id,
                    service_id=service.id,
                    conversation_id=conversation_id,
                    starts_at_utc=start_naive,
                    ends_at_utc=end_naive,
                    status="confirmed",
                    idempotency_key=idempotency_key,
                    timezone=profile.timezone,
                    is_synthetic_demo=is_synthetic_demo,
                )
                self.db.add(appt)
                event_type = "appointment_booked"
                audit_action = "appointment.book"
                summary = "Appointment confirmed"
            try:
                # Nested savepoint avoids wiping sibling uncommitted work on conflict.
                with self.db.begin_nested():
                    self.db.flush()
            except IntegrityError as exc:
                raise DoubleBookError() from exc

            contact.lead_state = "booked"
            self.db.add(
                GaLeadEvent(
                    id=_id(),
                    organization_id=org_id,
                    contact_id=contact.id,
                    event_type=event_type,
                    payload_json={"appointment_id": appt.id, "service_code": service_code},
                )
            )
            cal = self.calendar.write_event(
                {"action": "create", "appointment_id": appt.id, "live": False}
            )
            response = {
                "id": appt.id,
                "status": appt.status,
                "starts_at_utc": start.isoformat().replace("+00:00", "Z"),
                "ends_at_utc": end.isoformat().replace("+00:00", "Z"),
                "service_code": service_code,
                "contact_id": contact_id,
                "calendar_sync": {"provider": cal.provider, "status": cal.status, "live": False},
                "is_synthetic_demo": is_synthetic_demo,
            }
            self._idempotent_put(org_id, "appointment_book", idempotency_key, response)
            self.audit(
                org_id,
                action=audit_action,
                entity_type="appointment",
                entity_id=appt.id,
                actor_user_id=actor_user_id,
                summary=summary,
            )
            self.db.commit()
            return response

    def cancel_appointment(
        self,
        org_id: str,
        appointment_id: str,
        *,
        actor_user_id: str | None = None,
    ) -> dict[str, Any]:
        appt = self._org_query(GaAppointment, org_id).filter_by(id=appointment_id).one_or_none()
        if not appt:
            raise GrowthAgentError("NOT_FOUND", "Appointment not found", http_status=404)
        if appt.status == "cancelled":
            return {"id": appt.id, "status": appt.status}
        appt.status = "cancelled"
        self.audit(
            org_id,
            action="appointment.cancel",
            entity_type="appointment",
            entity_id=appt.id,
            actor_user_id=actor_user_id,
            summary="Appointment cancelled",
        )
        self.db.commit()
        return {"id": appt.id, "status": appt.status}

    def reschedule_appointment(
        self,
        org_id: str,
        appointment_id: str,
        *,
        starts_at_utc: str,
        idempotency_key: str,
        actor_user_id: str | None = None,
    ) -> dict[str, Any]:
        cached = self._idempotent_get(org_id, "appointment_reschedule", idempotency_key)
        if cached:
            return cached
        appt = self._org_query(GaAppointment, org_id).filter_by(id=appointment_id).one_or_none()
        if not appt:
            raise GrowthAgentError("NOT_FOUND", "Appointment not found", http_status=404)
        if appt.status == "cancelled":
            raise GrowthAgentError(
                "INVALID_STATE",
                "Cancelled appointments cannot be rescheduled; book a new slot instead",
                http_status=409,
            )
        profile = self._require_profile(org_id)
        service = (
            self.db.query(GaAppointmentService)
            .filter_by(id=appt.service_id, organization_id=org_id, active=True)
            .one_or_none()
        )
        if not service:
            raise GrowthAgentError("NOT_FOUND", "Service not found", http_status=404)
        start = appt_mod.parse_iso_utc(starts_at_utc)
        end = start + timedelta(minutes=service.duration_minutes)
        start_naive = start.replace(tzinfo=None)
        end_naive = end.replace(tzinfo=None)

        with _BOOK_LOCK:
            existing_rows = (
                self._org_query(GaAppointment, org_id)
                .filter(
                    GaAppointment.status.in_(_ACTIVE_BOOKING_STATUSES),
                    GaAppointment.id != appt.id,
                )
                .all()
            )
            existing = [
                {"starts_at_utc": a.starts_at_utc, "ends_at_utc": a.ends_at_utc, "status": a.status}
                for a in existing_rows
            ]
            appt_mod.assert_no_overlap(
                starts_at_utc=start,
                ends_at_utc=end,
                existing=existing,
                buffer_minutes=service.buffer_minutes,
            )
            # Free the unique slot if a cancelled appointment already occupies the target.
            blocker = (
                self._org_query(GaAppointment, org_id)
                .filter(
                    GaAppointment.service_id == service.id,
                    GaAppointment.starts_at_utc == start_naive,
                    GaAppointment.status == "cancelled",
                    GaAppointment.id != appt.id,
                )
                .one_or_none()
            )
            if blocker:
                # Nudge cancelled row off the unique key while preserving history.
                blocker.starts_at_utc = blocker.starts_at_utc + timedelta(microseconds=1)
                self.db.flush()

            appt.starts_at_utc = start_naive
            appt.ends_at_utc = end_naive
            appt.status = "rescheduled"
            appt.idempotency_key = idempotency_key
            appt.timezone = profile.timezone
            try:
                with self.db.begin_nested():
                    self.db.flush()
            except IntegrityError as exc:
                raise DoubleBookError() from exc

            self.db.add(
                GaLeadEvent(
                    id=_id(),
                    organization_id=org_id,
                    contact_id=appt.contact_id,
                    event_type="appointment_rescheduled",
                    payload_json={
                        "appointment_id": appt.id,
                        "starts_at_utc": start.isoformat().replace("+00:00", "Z"),
                    },
                )
            )
            cal = self.calendar.write_event(
                {"action": "reschedule", "appointment_id": appt.id, "live": False}
            )
            response = {
                "id": appt.id,
                "status": appt.status,
                "starts_at_utc": start.isoformat().replace("+00:00", "Z"),
                "ends_at_utc": end.isoformat().replace("+00:00", "Z"),
                "service_code": service.code,
                "contact_id": appt.contact_id,
                "calendar_sync": {"provider": cal.provider, "status": cal.status, "live": False},
                "is_synthetic_demo": bool(appt.is_synthetic_demo),
            }
            self._idempotent_put(org_id, "appointment_reschedule", idempotency_key, response)
            self.audit(
                org_id,
                action="appointment.reschedule",
                entity_type="appointment",
                entity_id=appt.id,
                actor_user_id=actor_user_id,
                summary="Appointment rescheduled",
            )
            self.db.commit()
            return response

    # ── analytics / health / commercial ──────────────────────────────────────

    def analytics(self, org_id: str, *, days: int = 30) -> dict[str, Any]:
        since = _now() - timedelta(days=max(1, min(days, 90)))
        contacts = self._org_query(GaContact, org_id).filter(GaContact.created_at >= since).count()
        consented = (
            self._org_query(GaConsentRecord, org_id)
            .filter(GaConsentRecord.recorded_at >= since, GaConsentRecord.status == "opted_in")
            .count()
        )
        opt_outs = (
            self._org_query(GaConsentRecord, org_id)
            .filter(GaConsentRecord.recorded_at >= since, GaConsentRecord.status == "opted_out")
            .count()
        )
        booked = (
            self._org_query(GaAppointment, org_id)
            .filter(
                GaAppointment.created_at >= since,
                GaAppointment.status.in_(_ACTIVE_BOOKING_STATUSES),
            )
            .count()
        )
        deliveries = self._org_query(GaDeliveryAttempt, org_id).filter(GaDeliveryAttempt.created_at >= since).all()
        success = sum(1 for d in deliveries if d.status == "sent_mock")
        failed = sum(1 for d in deliveries if d.status in {"failed", "suppressed"})
        usage = self._org_query(GaUsageEvent, org_id).filter(GaUsageEvent.created_at >= since).all()
        cost = sum(float(u.unit_cost_usd) * float(u.quantity) for u in usage)
        return {
            "window_days": days,
            "denominator_note": "Counts are org-scoped events created in the window; not attribution claims.",
            "inquiries": contacts,
            "consented_leads": consented,
            "booked_appointments": booked,
            "delivery_success": success,
            "delivery_failure_or_suppressed": failed,
            "opt_outs": opt_outs,
            "usage_cost_estimate_usd": round(cost, 6),
            "billed": False,
            "is_attribution": False,
        }

    def health(self, org_id: str) -> dict[str, Any]:
        profile = self._profile(org_id)
        failed = (
            self._org_query(GaDeliveryAttempt, org_id)
            .filter(GaDeliveryAttempt.status.in_(["failed", "retrying"]))
            .count()
        )
        queued = (
            self._org_query(GaDeliveryAttempt, org_id)
            .filter(GaDeliveryAttempt.status.in_(["queued", "retrying"]))
            .count()
        )
        return {
            "status": "ok" if profile and not profile.agent_disabled else "disabled_or_unconfigured",
            "agent_paused": bool(profile.agent_paused) if profile else None,
            "agent_disabled": bool(profile.agent_disabled) if profile else None,
            "delivery_failure_queue": failed,
            "pending_delivery_reclaim": queued,
            "restart_recovery": "POST /api/nova/growth-agent/workflows/recover",
            "live_flags": {
                "email": False,
                "sms": False,
                "calendar": False,
                "stripe": False,
                "voice": False,
            },
            "kill_switch": "POST /api/nova/growth-agent/agent {disabled:true}",
            "unit_cost_model": UNIT_COST_MODEL,
            "plans": plan_catalog(),
        }

    def audit_history(self, org_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = (
            self._org_query(GaAuditEvent, org_id)
            .order_by(GaAuditEvent.created_at.desc())
            .limit(min(limit, 500))
            .all()
        )
        return [
            {
                "id": r.id,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "summary": r.summary,
                "payload_redacted": r.payload_redacted_json,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ]

    @staticmethod
    def retention_policy() -> dict[str, Any]:
        return {
            "minimal_collection": [
                "business profile configuration",
                "contact identities needed for messaging after consent",
                "conversation transcripts for owner visibility",
                "consent records with collection source",
                "appointment times",
                "delivery attempt metadata (redacted)",
                "audit/usage instrumentation",
            ],
            "not_collected": [
                "payment card data",
                "government IDs",
                "scraped cold-contact lists",
                "provider API keys in plaintext",
            ],
            "retention_default_days": {
                "conversation_messages": 365,
                "audit_events": 730,
                "usage_events": 365,
                "delivery_attempts": 365,
                "lead_events": 365,
                "rate_limit_counters": 7,
                "consent_records": "retain while account active + legal minimum",
            },
            "retain_always": [
                "consent_records",
                "business_profiles",
                "contacts",
                "contact_identities",
                "appointments",
            ],
            "deletion": (
                "Dry-run preview via POST /retention/preview. "
                "Scheduled processor (NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED) is default-off "
                "and dry-runs by default. Destructive cleanup requires separate "
                "NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED=true plus POST /retention/execute "
                "or a scheduled delete-mode run (bounded batches)."
            ),
            "export": "GET /api/nova/growth-agent/export returns org-scoped JSON with PII included only for the owning org.",
        }

    def list_appointments(self, org_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = (
            self._org_query(GaAppointment, org_id)
            .order_by(GaAppointment.starts_at_utc.desc())
            .limit(max(1, min(limit, 200)))
            .all()
        )
        services = {
            s.id: s.code
            for s in self._org_query(GaAppointmentService, org_id).all()
        }
        return [
            {
                "id": a.id,
                "contact_id": a.contact_id,
                "service_code": services.get(a.service_id),
                "starts_at_utc": a.starts_at_utc.isoformat() + "Z" if a.starts_at_utc else None,
                "ends_at_utc": a.ends_at_utc.isoformat() + "Z" if a.ends_at_utc else None,
                "status": a.status,
                "is_synthetic_demo": bool(a.is_synthetic_demo),
            }
            for a in rows
        ]

    def list_consent_records(self, org_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        rows = (
            self._org_query(GaConsentRecord, org_id)
            .order_by(GaConsentRecord.recorded_at.desc())
            .limit(max(1, min(limit, 500)))
            .all()
        )
        return [
            {
                "id": r.id,
                "contact_id": r.contact_id,
                "channel": r.channel,
                "purpose": r.purpose,
                "status": r.status,
                "collection_source": r.collection_source,
                "recorded_at": r.recorded_at.isoformat() + "Z" if r.recorded_at else None,
            }
            for r in rows
        ]

    def export_org(self, org_id: str) -> dict[str, Any]:
        conversations = self.list_conversations(org_id)
        transcripts = []
        for conv in conversations[:50]:
            detail = self.get_conversation(org_id, conv["id"])
            transcripts.append(
                {
                    "conversation_id": conv["id"],
                    "messages": [
                        {
                            "role": m.get("role"),
                            "content": m.get("content"),
                            "grounded": m.get("grounded"),
                        }
                        for m in (detail.get("messages") or [])
                    ],
                }
            )
        return {
            "organization_id": org_id,
            "profile": self.get_profile(org_id),
            "leads": self.list_leads(org_id),
            "conversations": conversations,
            "conversation_messages": transcripts,
            "consent_records": self.list_consent_records(org_id),
            "appointments": self.list_appointments(org_id),
            "analytics": self.analytics(org_id),
            "audit": self.audit_history(org_id, limit=500),
            "retention": self.retention_policy(),
            "note": "Owner-only export. Handle as confidential. Identity digests are hashed.",
        }
