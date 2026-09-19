"""Nova V3 Phase 1 kernel. Synthetic, fail-closed, in-memory, not production."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.nova.v3.adapters import RawOpportunity, fixture_expires_at, get_adapter, registry
from app.core.nova.v3.connectors import CONNECTOR_KINDS, SimulatedConnector
from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags
from app.core.nova.v3.lifecycle import transition as workflow_transition
from app.core.nova.v3.models import (
    CLASSIFICATIONS,
    FROZEN,
    PHYSICAL_TOKENS,
    PROHIBITED_TOKENS,
    WORK_TYPES,
    Approval,
    Client,
    Correction,
    CredentialMeta,
    Engagement,
    Invoice,
    Message,
    Opportunity,
    PaymentEvent,
    Proposal,
    ScheduledJob,
    WorkItem,
)

from app.core.nova.v3.persistence import V3Store
from app.core.nova.v3.quality import evaluate_deliverable, require_quality
from app.core.nova.v3.scoring import explain_opportunity
from app.core.nova.v3.webhooks import ingest_webhook
from app.core.nova.v3.growth.kernel import get_growth_kernel, reset_growth_kernel
from app.core.nova.v3.worker import (
    JOB_KINDS,
    backoff_seconds,
    ensure_job_fields,
    lease_job,
    next_run,
    recover_stale,
)

APPROVAL_TYPES = {
    "OPPORTUNITY_APPROVE": "opportunity_approval",
    "LIVE_SUBMISSION": "live_submission_approval",
    "MOCK_SUBMISSION": "submission_approval",
    "MOCK_MESSAGE": "communication_approval",
    "DELIVERABLE_APPROVE": "deliverable_approval",
    "INVOICE_MOCK_DELIVER": "invoice_approval",
    "PAYMENT_ADJUST": "payment_adjustment_approval",
    "CONNECTOR_AUTHORIZE": "connector_authorization",
    "CREDENTIAL_AUTHORIZE": "credential_authorization",
    "WORK_EXECUTE": "deliverable_approval",
}
INJECTION_TOKENS = (
    "<script",
    "javascript:",
    "ignore previous instructions",
    "enable live discovery",
    "bypass captcha",
    "sk_" + "live_",
)
_TAG_RE = re.compile(r"<[^>]+>")


def _utc(value: datetime | None = None) -> datetime:
    stamp = value or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def require_timezone(name: str | None) -> str:
    token = str(name or "").strip()
    if not token:
        raise V3Error("TIMEZONE_REQUIRED", "explicit IANA timezone is required", http_status=400)
    try:
        ZoneInfo(token)
    except ZoneInfoNotFoundError as exc:
        raise V3Error("TIMEZONE_INVALID", "timezone must be an explicit IANA name", http_status=400) from exc
    return token


def fingerprint(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _plain(value: str | None) -> str:
    return _TAG_RE.sub("", str(value or "")).strip()


class NovaV3Kernel:
    def __init__(self) -> None:
        self.now = _utc()
        self._lock = threading.RLock()
        self._seq = 0
        self.opportunities: dict[str, Opportunity] = {}
        self.clients: dict[str, Client] = {}
        self.engagements: dict[str, Engagement] = {}
        self.proposals: dict[str, Proposal] = {}
        self.approvals: dict[str, Approval] = {}
        self.work_items: dict[str, WorkItem] = {}
        self.messages: dict[str, Message] = {}
        self.invoices: dict[str, Invoice] = {}
        self.events: dict[str, PaymentEvent] = {}
        self.corrections: dict[str, Correction] = {}
        self.credentials: dict[str, CredentialMeta] = {}
        self.jobs: dict[str, ScheduledJob] = {}
        self.audit: list[dict[str, Any]] = []
        self.idempotency: dict[tuple[str, str, str, str], Any] = {}
        self.adapter_failures: list[dict[str, Any]] = []
        self.connectors: dict[str, SimulatedConnector] = {}
        self.webhooks: dict[str, Any] = {}
        self.store: V3Store | None = None
        self.crash_before_job_commit = False
        self.fail_next_persist = False
        self.worker_shutdown = False
        self.event_watermarks: dict[str, datetime] = {}

    def _id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq:05d}"

    def _audit(self, event: str, organization_id: str, **payload: Any) -> None:
        self.audit.append(
            {"event": event, "organization_id": organization_id, "at": self.now.isoformat(), **payload}
        )

    def live_flags(self) -> dict[str, bool]:
        return live_flags()

    def assert_tenant(self, row_org: str, organization_id: str) -> None:
        if row_org != organization_id:
            raise V3Error("NOT_FOUND", "resource not found", http_status=404)

    def assert_owner(self, row_owner: str, owner_user_id: str) -> None:
        if row_owner != owner_user_id:
            raise V3Error("FORBIDDEN", "owner isolation", http_status=403)

    def reject_injection(self, text: str | None) -> str:
        cleaned = _plain(text)
        lower = cleaned.lower()
        for token in INJECTION_TOKENS:
            if token in lower:
                raise V3Error("INJECTION_REFUSED", "untrusted text cannot enable live action", http_status=400)
        return cleaned

    def human_gate(self, raw: RawOpportunity | Opportunity) -> str | None:
        if raw.captcha_required or raw.human_verification_required:
            return "HUMAN_ACTION_REQUIRED: CAPTCHA or human verification cannot be bypassed"
        if raw.login_required:
            return "HUMAN_ACTION_REQUIRED: login restrictions cannot be bypassed"
        if raw.rate_limited:
            return "HUMAN_ACTION_REQUIRED: rate limits cannot be bypassed"
        return None

    def classify(self, raw: RawOpportunity) -> tuple[str, float]:
        explained = explain_opportunity(raw)
        return explained["classification"], explained["score"]

    def _opportunity_from_raw(
        self,
        raw: RawOpportunity,
        *,
        organization_id: str,
        owner_user_id: str,
    ) -> Opportunity:
        self.reject_injection(raw.title)
        self.reject_injection(raw.description)
        if raw.source_url and (raw.source_url.lower().startswith("javascript:") or "<" in raw.source_url):
            raise V3Error("UNSAFE_URL", "source URL refused", http_status=400)
        explained = explain_opportunity(raw)
        classification, score = explained["classification"], explained["score"]
        fp = fingerprint(organization_id, raw.provider_id, raw.provider_identifier, raw.title.lower(), raw.company_name.lower())
        return Opportunity(
            opportunity_id=self._id("V3OPP"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            source_kind=raw.source_kind,
            provider_id=raw.provider_id,
            provider_identifier=raw.provider_identifier,
            title=_plain(raw.title),
            company_name=_plain(raw.company_name),
            description=_plain(raw.description),
            source_url=raw.source_url,
            source_evidence=raw.evidence,
            fetched_at=self.now,
            expires_at=fixture_expires_at(self.now),
            compensation_amount=raw.compensation_amount,
            compensation_type=raw.compensation_type,
            currency=raw.currency,
            required_qualifications=list(raw.required_qualifications),
            geography=raw.geography,
            remote_status=raw.remote_status,
            terms_restrictions=raw.terms_restrictions,
            login_required=raw.login_required,
            captcha_required=raw.captcha_required,
            human_verification_required=raw.human_verification_required,
            rate_limited=raw.rate_limited,
            fingerprint=fp,
            provenance={
                "adapter": raw.provider_id,
                "fetched_at": self.now.isoformat(),
                "synthetic": not bool(raw.live),
                "live": bool(raw.live),
            },
            classification=classification,
            score=score,
            status="LEAD",
            owner_review_required=True,
            score_explanation=explained,
            workflow_state="DISCOVERED",
        )

    def ingest(self, provider_id: str, *, organization_id: str, owner_user_id: str) -> dict[str, Any]:
        with self._lock:
            adapter = get_adapter(provider_id)
            try:
                raw_items = adapter.fetch()
            except V3Error as exc:
                if exc.code == "ADAPTER_FAILURE":
                    self.adapter_failures.append(
                        {"provider_id": provider_id, "organization_id": organization_id, "at": self.now.isoformat()}
                    )
                    self._audit("ADAPTER_FAILURE", organization_id, provider_id=provider_id)
                raise
            created: list[Opportunity] = []
            duplicates: list[str] = []
            for raw in raw_items:
                row = self._opportunity_from_raw(raw, organization_id=organization_id, owner_user_id=owner_user_id)
                existing = next(
                    (
                        item
                        for item in self.opportunities.values()
                        if item.organization_id == organization_id and item.fingerprint == row.fingerprint
                    ),
                    None,
                )
                if existing:
                    existing.duplicate_of = existing.duplicate_of or existing.opportunity_id
                    duplicates.append(existing.opportunity_id)
                    self._audit("OPPORTUNITY_DEDUPED", organization_id, fingerprint=row.fingerprint)
                    continue
                self.opportunities[row.opportunity_id] = row
                created.append(row)
                self._audit("OPPORTUNITY_INGESTED", organization_id, opportunity_id=row.opportunity_id)
            return {
                "created": [self.opportunity_out(item) for item in created],
                "duplicates": duplicates,
                "human_gates": [self.human_gate(item) for item in created if self.human_gate(item)],
            }

    def ingest_live_jobs(
        self,
        jobs: list[dict[str, Any]],
        *,
        organization_id: str,
        owner_user_id: str,
    ) -> dict[str, Any]:
        if not live_flags()["LIVE_DISCOVERY_ENABLED"]:
            raise V3Error("LIVE_DISABLED", "Live discovery is not enabled", http_status=409)
        created: list[Opportunity] = []
        duplicates: list[str] = []
        with self._lock:
            for job in jobs:
                raw = RawOpportunity(
                    provider_id=str(job.get("provider_id") or "live_job_source"),
                    source_kind="job_board",
                    provider_identifier=str(job.get("provider_identifier") or job.get("source_url") or ""),
                    title=str(job.get("title") or ""),
                    company_name=str(job.get("company_name") or ""),
                    description=str(job.get("description") or ""),
                    source_url=job.get("source_url"),
                    compensation_amount=None,
                    compensation_type="unknown",
                    currency="USD",
                    required_qualifications=[],
                    geography=str(job.get("geography") or "Remote"),
                    remote_status=str(job.get("remote_status") or "remote"),
                    terms_restrictions="Live source listing. Owner review required before any external action.",
                    login_required=False,
                    captcha_required=False,
                    human_verification_required=False,
                    evidence=f"live discovery via {job.get('source_attribution') or job.get('provider_id') or 'source'}",
                    live=True,
                )
                row = self._opportunity_from_raw(
                    raw,
                    organization_id=organization_id,
                    owner_user_id=owner_user_id,
                )
                existing = next(
                    (
                        item
                        for item in self.opportunities.values()
                        if item.organization_id == organization_id and item.fingerprint == row.fingerprint
                    ),
                    None,
                )
                if existing:
                    duplicates.append(existing.opportunity_id)
                    continue
                self.opportunities[row.opportunity_id] = row
                created.append(row)
                self._audit(
                    "LIVE_OPPORTUNITY_INGESTED",
                    organization_id,
                    opportunity_id=row.opportunity_id,
                    provider_id=row.provider_id,
                )
        return {
            "created": [self.opportunity_out(item) for item in created],
            "duplicates": duplicates,
        }

    def enter_manual(self, payload: dict[str, Any], *, organization_id: str, owner_user_id: str) -> Opportunity:
        raw = RawOpportunity(
            provider_id="manual",
            source_kind="manual",
            provider_identifier=str(payload.get("provider_identifier") or f"MAN-{self._seq + 1}"),
            title=str(payload.get("title") or ""),
            company_name=str(payload.get("company_name") or ""),
            description=str(payload.get("description") or ""),
            source_url=payload.get("source_url"),
            compensation_amount=payload.get("compensation_amount"),
            compensation_type=str(payload.get("compensation_type") or "fixed"),
            currency=str(payload.get("currency") or "USD"),
            required_qualifications=list(payload.get("required_qualifications") or []),
            geography=str(payload.get("geography") or "Remote"),
            remote_status=str(payload.get("remote_status") or "remote"),
            terms_restrictions=str(payload.get("terms_restrictions") or "manual entry"),
            login_required=bool(payload.get("login_required")),
            captcha_required=bool(payload.get("captcha_required")),
            human_verification_required=bool(payload.get("human_verification_required")),
            evidence="owner manual entry",
        )
        row = self._opportunity_from_raw(raw, organization_id=organization_id, owner_user_id=owner_user_id)
        self.opportunities[row.opportunity_id] = row
        self._audit("MANUAL_OPPORTUNITY", organization_id, opportunity_id=row.opportunity_id)
        return row

    def get_opportunity(self, opportunity_id: str, *, organization_id: str, owner_user_id: str) -> Opportunity:
        row = self.opportunities.get(opportunity_id)
        if row is None:
            raise V3Error("NOT_FOUND", "opportunity not found", http_status=404)
        self.assert_tenant(row.organization_id, organization_id)
        self.assert_owner(row.owner_user_id, owner_user_id)
        return row

    def list_opportunities(self, *, organization_id: str, owner_user_id: str) -> list[Opportunity]:
        return [
            item
            for item in self.opportunities.values()
            if item.organization_id == organization_id and item.owner_user_id == owner_user_id
        ]

    def opportunity_out(self, row: Opportunity) -> dict[str, Any]:
        gate = self.human_gate(row)
        return {
            "opportunity_id": row.opportunity_id,
            "title": row.title,
            "company_name": row.company_name,
            "description": row.description,
            "source_kind": row.source_kind,
            "provider_id": row.provider_id,
            "provider_identifier": row.provider_identifier,
            "source_url": row.source_url,
            "source_evidence": row.source_evidence,
            "fetched_at": row.fetched_at.isoformat(),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "compensation_amount": row.compensation_amount,
            "compensation_type": row.compensation_type,
            "currency": row.currency,
            "required_qualifications": row.required_qualifications,
            "geography": row.geography,
            "remote_status": row.remote_status,
            "terms_restrictions": row.terms_restrictions,
            "login_required": row.login_required,
            "captcha_required": row.captcha_required,
            "human_verification_required": row.human_verification_required,
            "fingerprint": row.fingerprint,
            "provenance": row.provenance,
            "classification": row.classification,
            "score": row.score,
            "score_explanation": row.score_explanation,
            "workflow_state": row.workflow_state,
            "status": row.status,
            "duplicate_of": row.duplicate_of,
            "human_action": gate,
            "live_discovery": bool(row.provenance.get("live")),
        }

    def prepare_proposal(self, opportunity_id: str, *, organization_id: str, owner_user_id: str) -> Proposal:
        opp = self.get_opportunity(opportunity_id, organization_id=organization_id, owner_user_id=owner_user_id)
        if opp.status in {"REJECTED", "EXPIRED", "CANCELLED", "ARCHIVED"} or opp.workflow_state in {"REJECTED", "EXPIRED", "CANCELLED", "ARCHIVED"}:
            raise V3Error("INVALID_STATE", "rejected or closed opportunity cannot receive a proposal")
        if opp.classification in {"PROHIBITED", "HUMAN_ONLY"}:
            raise V3Error("NOT_APPROPRIATE", "Nova will not prepare a proposal for this classification")
        body = (
            f"INTERNAL DRAFT ONLY. Company: {opp.company_name}. Work: {opp.title}. "
            "Nova did not submit this. Missing facts remain [OWNER INPUT REQUIRED]."
        )
        proposal = Proposal(
            proposal_id=self._id("V3APP"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            opportunity_id=opportunity_id,
            body=body,
            status="APPLICATION_PREPARED",
        )
        self.proposals[proposal.proposal_id] = proposal
        opp.status = "APPLICATION_PREPARED"
        opp.workflow_state = workflow_transition(opp.workflow_state, "PROPOSAL_READY")
        self._audit("PROPOSAL_PREPARED", organization_id, proposal_id=proposal.proposal_id)
        return proposal

    def request_approval(
        self,
        *,
        organization_id: str,
        owner_user_id: str,
        action: str,
        target_id: str,
        payload: dict[str, Any],
        expires_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> Approval:
        if idempotency_key:
            prior = self.idempotency.get((organization_id, owner_user_id, "approval", idempotency_key))
            if prior:
                return self.approvals[prior]
        row = Approval(
            approval_id=self._id("V3APV"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            action=action,
            target_id=target_id,
            payload_fingerprint=fingerprint(payload),
            status="PENDING",
            created_at=self.now,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            approval_type=APPROVAL_TYPES.get(action, "generic"),
        )
        self.approvals[row.approval_id] = row
        if idempotency_key:
            self.idempotency[(organization_id, owner_user_id, "approval", idempotency_key)] = row.approval_id
        self._audit("APPROVAL_REQUESTED", organization_id, approval_id=row.approval_id, action=action)
        return row

    def get_approval(self, approval_id: str, *, organization_id: str, owner_user_id: str) -> Approval:
        row = self.approvals.get(approval_id)
        if row is None:
            raise V3Error("NOT_FOUND", "approval not found", http_status=404)
        self.assert_tenant(row.organization_id, organization_id)
        self.assert_owner(row.owner_user_id, owner_user_id)
        return row

    def decide_approval(
        self, approval_id: str, *, organization_id: str, owner_user_id: str, decision: str
    ) -> Approval:
        row = self.get_approval(approval_id, organization_id=organization_id, owner_user_id=owner_user_id)
        self.expire_due_approvals()
        wanted = decision.upper()
        if wanted not in {"APPROVED", "REJECTED"}:
            raise V3Error("INVALID_DECISION", "decision must be APPROVED or REJECTED", http_status=400)
        if row.status == "EXPIRED":
            raise V3Error("EXPIRED_APPROVAL", "expired approval cannot be decided")
        if row.status not in {"REQUESTED", "PENDING"}:
            raise V3Error("INVALID_STATE", f"cannot decide from {row.status}")
        row.status = wanted
        self._audit("APPROVAL_DECIDED", organization_id, approval_id=approval_id, status=wanted, approval_type=row.approval_type)
        return row

    def revoke_approval(self, approval_id: str, *, organization_id: str, owner_user_id: str) -> Approval:
        row = self.get_approval(approval_id, organization_id=organization_id, owner_user_id=owner_user_id)
        if row.status != "APPROVED":
            raise V3Error("INVALID_STATE", "only APPROVED can be revoked")
        row.status = "REVOKED"
        self._audit("APPROVAL_REVOKED", organization_id, approval_id=approval_id)
        return row

    def expire_due_approvals(self) -> None:
        for row in self.approvals.values():
            if row.status in {"APPROVED", "REQUESTED", "PENDING"} and row.expires_at is not None and row.expires_at < self.now:
                row.status = "EXPIRED"

    def consume_approval(
        self,
        approval_id: str,
        *,
        organization_id: str,
        owner_user_id: str,
        action: str,
        target_id: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> Approval:
        if idempotency_key:
            prior = self.idempotency.get((organization_id, owner_user_id, "consume", idempotency_key))
            if prior:
                return self.approvals[prior]
        row = self.get_approval(approval_id, organization_id=organization_id, owner_user_id=owner_user_id)
        self.expire_due_approvals()
        if row.status == "EXPIRED":
            raise V3Error("EXPIRED_APPROVAL", "expired approval cannot execute")
        if row.status == "REVOKED":
            raise V3Error("REVOKED_APPROVAL", "revoked approval cannot execute")
        if row.status == "REJECTED":
            raise V3Error("REJECTED_APPROVAL", "rejected approval cannot execute")
        if row.status == "CONSUMED":
            raise V3Error("DUPLICATE_CONSUME", "consumed approval cannot execute twice")
        if row.status != "APPROVED":
            raise V3Error("MISSING_APPROVAL", "approval is not approved")
        if row.action != action or row.target_id != target_id:
            raise V3Error("STALE_APPROVAL", "approval target mismatch")
        if row.payload_fingerprint != fingerprint(payload):
            raise V3Error("PAYLOAD_CHANGED", "changed payload requires a new approval")
        row.status = "CONSUMED"
        row.consumed_at = self.now
        if idempotency_key:
            self.idempotency[(organization_id, owner_user_id, "consume", idempotency_key)] = row.approval_id
        self._audit("APPROVAL_CONSUMED", organization_id, approval_id=approval_id, executed=False)
        return row

    def live_submit(
        self,
        proposal_id: str,
        *,
        organization_id: str,
        owner_user_id: str,
        approval_id: str,
    ) -> dict[str, Any]:
        if not live_flags()["EXTERNAL_SUBMISSION_ENABLED"]:
            raise V3Error("LIVE_DISABLED", "Controlled external submission is not enabled", http_status=409)

        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise V3Error("NOT_FOUND", "proposal not found", http_status=404)
        self.assert_tenant(proposal.organization_id, organization_id)
        self.assert_owner(proposal.owner_user_id, owner_user_id)

        opp = self.get_opportunity(
            proposal.opportunity_id,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
        )
        if not bool(opp.provenance.get("live")):
            raise V3Error("NOT_LIVE_OPPORTUNITY", "live submission requires a live opportunity", http_status=400)
        if not opp.source_url:
            raise V3Error("MISSING_APPLICATION_URL", "live opportunity has no application URL", http_status=400)

        approval = self.get_approval(
            approval_id,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
        )
        expected_payload = {"proposal_id": proposal_id, "source_url": opp.source_url}
        if approval.status != "APPROVED":
            raise V3Error("MISSING_APPROVAL", "live submission approval is not approved")
        if approval.action != "LIVE_SUBMISSION" or approval.target_id != proposal_id:
            raise V3Error("STALE_APPROVAL", "live submission approval target mismatch")
        if approval.payload_fingerprint != fingerprint(expected_payload):
            raise V3Error("PAYLOAD_CHANGED", "application target changed; new approval required")

        # Remotive is a discovery source. Listings lead to employer-controlled application
        # pages and Nova has no authorized direct-submit transport for those sites.
        # Preserve the approval and return a truthful handoff instead of pretending to submit.
        result = {
            "status": "HUMAN_ACTION_REQUIRED",
            "submission_mode": "external_url_handoff",
            "provider_id": opp.provider_id,
            "proposal_id": proposal_id,
            "opportunity_id": opp.opportunity_id,
            "application_url": opp.source_url,
            "approval_id": approval_id,
            "approval_status": approval.status,
            "externally_submitted": False,
            "reason": (
                "No authorized direct-submit API is configured for this listing. "
                "Open the employer application page and complete any login, CAPTCHA, "
                "identity verification, or terms acceptance manually."
            ),
        }
        self._audit(
            "LIVE_SUBMISSION_HANDOFF",
            organization_id,
            proposal_id=proposal_id,
            provider_id=opp.provider_id,
            executed=False,
        )
        return result

    def mock_submit(self, proposal_id: str, *, organization_id: str, owner_user_id: str, approval_id: str) -> Proposal:
        if live_flags()["EXTERNAL_SUBMISSION_ENABLED"]:
            raise V3Error("LIVE_DISABLED", "live submission cannot be enabled in Phase 1")
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise V3Error("NOT_FOUND", "proposal not found", http_status=404)
        self.assert_tenant(proposal.organization_id, organization_id)
        self.assert_owner(proposal.owner_user_id, owner_user_id)
        opp = self.get_opportunity(proposal.opportunity_id, organization_id=organization_id, owner_user_id=owner_user_id)
        gate = self.human_gate(opp)
        if gate:
            raise V3Error("HUMAN_ACTION_REQUIRED", gate)
        self.consume_approval(
            approval_id,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            action="MOCK_SUBMISSION",
            target_id=proposal_id,
            payload={"proposal_id": proposal_id},
        )
        proposal.mock_submitted = True
        proposal.externally_submitted = False
        proposal.status = "SUBMITTED"
        opp.status = "SUBMITTED"
        opp.workflow_state = workflow_transition(opp.workflow_state, "MOCK_SUBMITTED")
        self._audit("MOCK_SUBMISSION", organization_id, proposal_id=proposal_id, live=False)
        return proposal

    def accept_synthetic(self, proposal_id: str, *, organization_id: str, owner_user_id: str) -> Engagement:
        proposal = self.proposals.get(proposal_id)
        if proposal is None or not proposal.mock_submitted:
            raise V3Error("INVALID_STATE", "synthetic accept requires mock submission")
        self.assert_tenant(proposal.organization_id, organization_id)
        self.assert_owner(proposal.owner_user_id, owner_user_id)
        opp = self.get_opportunity(proposal.opportunity_id, organization_id=organization_id, owner_user_id=owner_user_id)
        client = Client(
            client_id=self._id("V3CLT"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            name=opp.company_name,
            status="WON",
        )
        self.clients[client.client_id] = client
        expected = float(opp.compensation_amount or 0)
        engagement = Engagement(
            engagement_id=self._id("V3ENG"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            client_id=client.client_id,
            opportunity_id=opp.opportunity_id,
            title=opp.title,
            status="ACTIVE",
            expected_amount=expected,
            remaining_amount=expected,
            workflow_state="ACTIVE",
        )
        self.engagements[engagement.engagement_id] = engagement
        opp.status = "WON"
        opp.workflow_state = workflow_transition(opp.workflow_state, "WON")
        self._audit("ENGAGEMENT_CREATED", organization_id, engagement_id=engagement.engagement_id)
        return engagement

    def get_engagement(self, engagement_id: str, *, organization_id: str, owner_user_id: str) -> Engagement:
        row = self.engagements.get(engagement_id)
        if row is None:
            raise V3Error("NOT_FOUND", "engagement not found", http_status=404)
        self.assert_tenant(row.organization_id, organization_id)
        self.assert_owner(row.owner_user_id, owner_user_id)
        return row

    def set_engagement_status(
        self, engagement_id: str, *, organization_id: str, owner_user_id: str, status: str
    ) -> Engagement:
        row = self.get_engagement(engagement_id, organization_id=organization_id, owner_user_id=owner_user_id)
        wanted = status.upper()
        row.workflow_state = workflow_transition(row.workflow_state, wanted)
        row.status = wanted
        if wanted in FROZEN:
            for job in self.jobs.values():
                if job.organization_id == organization_id and job.owner_user_id == owner_user_id:
                    if job.ref_id in {engagement_id, None} or job.ref_id == engagement_id:
                        if job.ref_id == engagement_id:
                            job.status = "CANCELLED"
        return row

    def create_work_item(
        self,
        *,
        organization_id: str,
        owner_user_id: str,
        engagement_id: str,
        work_type: str,
        source_inputs: dict[str, Any],
        approval_id: str,
    ) -> WorkItem:
        if work_type not in WORK_TYPES:
            raise V3Error("INVALID_WORK_TYPE", "work type is not in the Phase 1 catalog", http_status=400)
        engagement = self.get_engagement(engagement_id, organization_id=organization_id, owner_user_id=owner_user_id)
        if engagement.status in FROZEN:
            raise V3Error("FINANCIAL_FREEZE", "frozen engagement rejects new work")
        if engagement.status == "ON_HOLD" or engagement.workflow_state == "ON_HOLD":
            raise V3Error("PAUSED_WORKFLOW", "paused engagement rejects new work")
        self.consume_approval(
            approval_id,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            action="WORK_EXECUTE",
            target_id=engagement_id,
            payload={"work_type": work_type, "engagement_id": engagement_id},
        )
        plan = [
            "collect owner-supplied inputs",
            f"prepare {work_type.replace('_', ' ')}",
            "quality check",
            "owner review",
        ]
        item = WorkItem(
            work_item_id=self._id("V3WRK"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            engagement_id=engagement.engagement_id,
            work_type=work_type,
            source_inputs=source_inputs,
            task_plan=plan,
            evidence_links=["synthetic://internal-notes"],
        )
        self.work_items[item.work_item_id] = item
        self._audit("WORK_PLANNED", organization_id, work_item_id=item.work_item_id)
        return item

    def execute_work(self, work_item_id: str, *, organization_id: str, owner_user_id: str) -> WorkItem:
        item = self.work_items.get(work_item_id)
        if item is None:
            raise V3Error("NOT_FOUND", "work item not found", http_status=404)
        self.assert_tenant(item.organization_id, organization_id)
        self.assert_owner(item.owner_user_id, owner_user_id)
        item.deliverable = (
            f"INTERNAL {item.work_type} draft for engagement {item.engagement_id}. "
            "Not delivered to any client. Sources: owner-supplied synthetic inputs."
        )
        item.quality_checks = ["no fabricated qualifications", "no external delivery claim", "sources cited"]
        item.execution_record = {"ran_at": self.now.isoformat(), "external": False}
        item.status = "COMPLETE"
        item.owner_review_status = "READY_FOR_REVIEW"
        item.delivery_status = "INTERNAL_ONLY"
        engagement = self.get_engagement(item.engagement_id, organization_id=organization_id, owner_user_id=owner_user_id)
        engagement.status = "DELIVERABLE_READY"
        engagement.workflow_state = workflow_transition(engagement.workflow_state, "DELIVERABLE_READY")
        self._audit("WORK_EXECUTED_INTERNAL", organization_id, work_item_id=work_item_id)
        return item

    def owner_approve_deliverable(
        self, work_item_id: str, *, organization_id: str, owner_user_id: str
    ) -> WorkItem:
        item = self.work_items.get(work_item_id)
        if item is None:
            raise V3Error("NOT_FOUND", "work item not found", http_status=404)
        self.assert_tenant(item.organization_id, organization_id)
        self.assert_owner(item.owner_user_id, owner_user_id)
        report = evaluate_deliverable(
            body=item.deliverable, source_inputs=item.source_inputs, evidence_links=item.evidence_links
        )
        require_quality(report)
        item.quality_report = report
        item.owner_review_status = "APPROVED"
        engagement = self.get_engagement(item.engagement_id, organization_id=organization_id, owner_user_id=owner_user_id)
        engagement.status = "OWNER_APPROVAL"
        engagement.workflow_state = workflow_transition(engagement.workflow_state, "APPROVED_FOR_DELIVERY")
        return item

    def mock_deliver(self, work_item_id: str, *, organization_id: str, owner_user_id: str) -> WorkItem:
        if live_flags()["CLIENT_CONTACT_ENABLED"]:
            raise V3Error("LIVE_DISABLED", "live delivery is off")
        item = self.work_items.get(work_item_id)
        if item is None or item.owner_review_status != "APPROVED":
            raise V3Error("MISSING_APPROVAL", "deliverable requires owner approval")
        self.assert_owner(item.owner_user_id, owner_user_id)
        item.delivery_status = "MOCK_DELIVERED"
        engagement = self.get_engagement(item.engagement_id, organization_id=organization_id, owner_user_id=owner_user_id)
        engagement.status = "DELIVERED"
        engagement.workflow_state = workflow_transition(engagement.workflow_state, "MOCK_DELIVERED")
        engagement.status = "DELIVERED"
        self._audit("MOCK_DELIVERY", organization_id, work_item_id=work_item_id, live=False)
        return item

    def prepare_message(
        self, *, organization_id: str, owner_user_id: str, channel: str, body: str
    ) -> Message:
        text = self.reject_injection(body)
        if channel not in {"email", "messaging", "crm_note", "portal"}:
            raise V3Error("INVALID_CHANNEL", "unknown communication channel", http_status=400)
        row = Message(
            message_id=self._id("V3MSG"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            channel=channel,
            body=text,
            status="PREPARED",
        )
        self.messages[row.message_id] = row
        return row

    def validate_message(self, message_id: str, *, organization_id: str, owner_user_id: str) -> Message:
        row = self.messages.get(message_id)
        if row is None:
            raise V3Error("NOT_FOUND", "message not found", http_status=404)
        self.assert_tenant(row.organization_id, organization_id)
        self.assert_owner(row.owner_user_id, owner_user_id)
        if not row.body.strip():
            raise V3Error("INVALID_MESSAGE", "message body required", http_status=400)
        row.status = "VALIDATED"
        return row

    def send_mock(self, message_id: str, *, organization_id: str, owner_user_id: str, approval_id: str) -> Message:
        if live_flags()["CLIENT_CONTACT_ENABLED"]:
            raise V3Error("LIVE_DISABLED", "real messaging is off")
        row = self.validate_message(message_id, organization_id=organization_id, owner_user_id=owner_user_id)
        self.consume_approval(
            approval_id,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            action="MOCK_MESSAGE",
            target_id=message_id,
            payload={"message_id": message_id, "channel": row.channel},
        )
        row.status = "MOCK_SENT"
        row.sent_externally = False
        self._audit("MOCK_MESSAGE", organization_id, message_id=message_id, channel=row.channel)
        return row

    def schedule_job(
        self,
        *,
        organization_id: str,
        owner_user_id: str,
        kind: str,
        timezone_name: str,
        frequency: str = "daily",
        ref_id: str | None = None,
    ) -> ScheduledJob:
        tz = require_timezone(timezone_name)
        allowed = set(JOB_KINDS) | {"invoice_follow_up"}
        if kind not in allowed:
            raise V3Error("INVALID_JOB_KIND", "unknown scheduler job kind", http_status=400)
        key = self.period_key(frequency, tz)
        existing = next(
            (
                item
                for item in self.jobs.values()
                if item.organization_id == organization_id
                and item.owner_user_id == owner_user_id
                and item.kind == kind
                and item.period_key == key
            ),
            None,
        )
        if existing:
            return existing
        job = ScheduledJob(
            job_id=self._id("V3JOB"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            kind=kind,
            period_key=key,
            timezone_name=tz,
            status="PREPARED",
            frequency=frequency,
            next_run_at=self.now,
            ref_id=ref_id,
        )
        self.jobs[job.job_id] = job
        self._audit("JOB_PREPARED", organization_id, job_id=job.job_id, worker=False)
        return job

    def period_key(self, frequency: str, timezone_name: str, when: datetime | None = None) -> str:
        tz = require_timezone(timezone_name)
        local = (when or self.now).astimezone(ZoneInfo(tz))
        if frequency == "weekly":
            iso = local.isocalendar()
            return f"{frequency}:{tz}:{iso.year}-W{iso.week:02d}"
        if frequency == "monthly":
            return f"{frequency}:{tz}:{local.strftime('%Y-%m')}"
        return f"{frequency}:{tz}:{local.strftime('%Y-%m-%d')}"

    def run_job(self, job_id: str, *, organization_id: str, owner_user_id: str) -> ScheduledJob:
        if live_flags()["BACKGROUND_WORKER_ENABLED"]:
            raise V3Error("LIVE_DISABLED", "production worker cannot start in Phase 1")
        job = self.jobs.get(job_id)
        if job is None:
            raise V3Error("NOT_FOUND", "job not found", http_status=404)
        self.assert_tenant(job.organization_id, organization_id)
        self.assert_owner(job.owner_user_id, owner_user_id)
        if job.status in {"PAUSED", "CANCELLED", "ARCHIVED"}:
            raise V3Error("JOB_NOT_ACTIVE", f"cannot run {job.status}")
        if job.status == "EXECUTED":
            raise V3Error("DUPLICATE_JOB", "period already executed")
        job.status = "EXECUTED"
        job.run_count += 1
        self._audit("JOB_MOCK_RUN", organization_id, job_id=job_id, live=False)
        return job

    def pause_job(self, job_id: str, *, organization_id: str, owner_user_id: str) -> ScheduledJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise V3Error("NOT_FOUND", "job not found", http_status=404)
        self.assert_owner(job.owner_user_id, owner_user_id)
        job.status = "PAUSED"
        return job

    def resume_job(self, job_id: str, *, organization_id: str, owner_user_id: str) -> ScheduledJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise V3Error("NOT_FOUND", "job not found", http_status=404)
        self.assert_owner(job.owner_user_id, owner_user_id)
        if job.status == "CANCELLED":
            raise V3Error("JOB_NOT_ACTIVE", "cancelled job cannot resume")
        job.status = "PREPARED"
        return job

    def cancel_job(self, job_id: str, *, organization_id: str, owner_user_id: str) -> ScheduledJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise V3Error("NOT_FOUND", "job not found", http_status=404)
        self.assert_owner(job.owner_user_id, owner_user_id)
        job.status = "CANCELLED"
        return job

    def create_invoice(
        self,
        *,
        organization_id: str,
        owner_user_id: str,
        engagement_id: str,
        amount: float,
        kind: str,
        due_at: datetime | None = None,
    ) -> Invoice:
        engagement = self.get_engagement(engagement_id, organization_id=organization_id, owner_user_id=owner_user_id)
        if engagement.status not in {"DELIVERED", "OWNER_APPROVAL", "ACTIVE", "INVOICED", "PARTIALLY_PAID"}:
            raise V3Error("INVALID_STATE", "invoice requires completed approved work context")
        if kind not in {"fixed", "hourly", "milestone", "recurring"}:
            raise V3Error("INVALID_INVOICE_KIND", "unsupported invoice kind", http_status=400)
        invoice = Invoice(
            invoice_id=self._id("V3INV"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            engagement_id=engagement_id,
            amount=round(float(amount), 2),
            kind=kind,
            status="DRAFT",
            due_at=due_at,
        )
        self.invoices[invoice.invoice_id] = invoice
        engagement.workflow_state = workflow_transition(engagement.workflow_state, "INVOICE_DRAFT")
        self._audit("INVOICE_DRAFT", organization_id, invoice_id=invoice.invoice_id, stripe=False)
        return invoice

    def approve_invoice(
        self, invoice_id: str, *, organization_id: str, owner_user_id: str, approval_id: str
    ) -> Invoice:
        invoice = self.invoices.get(invoice_id)
        if invoice is None:
            raise V3Error("NOT_FOUND", "invoice not found", http_status=404)
        self.assert_owner(invoice.owner_user_id, owner_user_id)
        self.consume_approval(
            approval_id,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            action="INVOICE_MOCK_DELIVER",
            target_id=invoice_id,
            payload={"invoice_id": invoice_id},
        )
        invoice.status = "OWNER_APPROVED"
        engagement = self.get_engagement(invoice.engagement_id, organization_id=organization_id, owner_user_id=owner_user_id)
        engagement.workflow_state = workflow_transition(engagement.workflow_state, "INVOICE_APPROVED")
        return invoice

    def mock_deliver_invoice(self, invoice_id: str, *, organization_id: str, owner_user_id: str) -> Invoice:
        if live_flags()["INVOICE_SEND_ENABLED"]:
            raise V3Error("LIVE_DISABLED", "real invoice send is off")
        invoice = self.invoices.get(invoice_id)
        if invoice is None or invoice.status != "OWNER_APPROVED":
            raise V3Error("MISSING_APPROVAL", "invoice mock delivery requires owner approval")
        self.assert_owner(invoice.owner_user_id, owner_user_id)
        invoice.status = "MOCK_DELIVERED"
        invoice.delivered_mock = True
        invoice.stripe_invoice_created = False
        engagement = self.get_engagement(invoice.engagement_id, organization_id=organization_id, owner_user_id=owner_user_id)
        engagement.status = "INVOICED"
        engagement.workflow_state = workflow_transition(engagement.workflow_state, "MOCK_INVOICE_SENT")
        self._audit("INVOICE_MOCK_DELIVERED", organization_id, invoice_id=invoice_id, stripe=False)
        return invoice

    def ingest_payment_event(
        self,
        *,
        organization_id: str,
        owner_user_id: str,
        event_id: str,
        invoice_id: str | None,
        amount: float,
        event_type: str,
        occurred_at: datetime,
        processor: str = "synthetic",
    ) -> PaymentEvent:
        if str(processor or "").lower() == "stripe":
            raise V3Error("STRIPE_FORBIDDEN", "Stripe payment events are out of scope")
        key = (organization_id, owner_user_id, "event", event_id)
        prior = self.idempotency.get(key)
        if prior:
            existing = self.events[prior]
            existing.duplicate = True
            return existing
        unknown = False
        mismatch = str(processor or "synthetic").lower() not in {"synthetic", "lab", "mock"}
        if invoice_id:
            invoice = self.invoices.get(invoice_id)
            if invoice is None:
                unknown = True
            else:
                self.assert_owner(invoice.owner_user_id, owner_user_id)
                self.assert_tenant(invoice.organization_id, organization_id)
        late = occurred_at < (self.now - timedelta(days=7))
        stale = occurred_at < (self.now - timedelta(days=90))
        event_type_l = str(event_type or "").lower()
        watermark_key = f"{organization_id}:{owner_user_id}:{invoice_id or 'none'}"
        last = self.event_watermarks.get(watermark_key)
        out_of_order = bool(last and occurred_at < last)
        event = PaymentEvent(
            event_id=event_id,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            invoice_id=invoice_id,
            amount=round(float(amount), 2),
            event_type=event_type,
            occurred_at=_utc(occurred_at),
            applied_to_ledger=False,
            late=late,
            processor=processor or "synthetic",
            stale=stale,
            reversed=event_type_l in {"refund", "chargeback", "reversal"},
            unknown_invoice=unknown,
            out_of_order=out_of_order,
            processor_mismatch=mismatch,
        )
        self.events[event.event_id] = event
        self.idempotency[key] = event.event_id
        if not out_of_order:
            self.event_watermarks[watermark_key] = _utc(occurred_at)
        self._audit("PAYMENT_EVENT", organization_id, event_id=event_id, applied_to_ledger=False, processor=event.processor)
        return event

    def confirm_received(
        self,
        engagement_id: str,
        *,
        organization_id: str,
        owner_user_id: str,
        total_received_so_far: float,
        idempotency_key: str | None = None,
    ) -> Engagement:
        if idempotency_key:
            prior = self.idempotency.get((organization_id, owner_user_id, "confirm", idempotency_key))
            if prior:
                return self.engagements[prior]
        row = self.get_engagement(engagement_id, organization_id=organization_id, owner_user_id=owner_user_id)
        if row.status in FROZEN:
            raise V3Error("FINANCIAL_FREEZE", "frozen engagement rejects ordinary payment mutation")
        if row.status == "ON_HOLD" or row.workflow_state == "ON_HOLD":
            raise V3Error("PAUSED_WORKFLOW", "paused engagement rejects payment mutation")
        amount = round(float(total_received_so_far), 2)
        expected = round(float(row.expected_amount or 0), 2)
        if amount < 0:
            raise V3Error("INVALID_AMOUNT", "received total cannot be negative", http_status=400)
        if amount > expected + 0.009:
            raise V3Error("OVERPAYMENT_REQUIRES_OWNER_REVIEW", "overpayment refused")
        row.received_amount = amount
        row.remaining_amount = round(expected - amount, 2)
        if amount == 0:
            row.status = "INVOICED"
            row.workflow_state = workflow_transition(row.workflow_state, "MOCK_INVOICE_SENT")
        elif amount + 0.009 < expected:
            row.status = "PARTIALLY_PAID"
            row.workflow_state = workflow_transition(row.workflow_state, "PARTIALLY_PAID")
        else:
            row.status = "PAID"
            row.remaining_amount = 0.0
            row.workflow_state = workflow_transition(row.workflow_state, "PAID")
        if idempotency_key:
            self.idempotency[(organization_id, owner_user_id, "confirm", idempotency_key)] = row.engagement_id
        self._audit("OWNER_CONFIRMED_RECEIVED", organization_id, engagement_id=engagement_id, received=amount)
        return row

    def historical_correct(
        self,
        engagement_id: str,
        *,
        organization_id: str,
        owner_user_id: str,
        original_amount: float,
        corrected_amount: float,
        reason: str,
        authorized: bool,
        idempotency_key: str,
    ) -> Correction:
        if not authorized:
            raise V3Error("MISSING_APPROVAL", "historical correction requires owner authorization", http_status=403)
        if not str(reason or "").strip():
            raise V3Error("REASON_REQUIRED", "reason required", http_status=400)
        prior = self.idempotency.get((organization_id, owner_user_id, "correction", idempotency_key))
        if prior:
            return self.corrections[prior]
        row = self.get_engagement(engagement_id, organization_id=organization_id, owner_user_id=owner_user_id)
        if round(float(original_amount), 2) != round(row.received_amount, 2):
            raise V3Error("ORIGINAL_AMOUNT_MISMATCH", "original amount must match current received")
        if corrected_amount < 0:
            raise V3Error("INVALID_AMOUNT", "corrected amount cannot be negative", http_status=400)
        if corrected_amount > row.expected_amount + 0.009:
            raise V3Error("OVERPAYMENT_REQUIRES_OWNER_REVIEW", "correction cannot silently inflate")
        correction = Correction(
            correction_id=self._id("V3COR"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            engagement_id=engagement_id,
            original_amount=round(float(original_amount), 2),
            corrected_amount=round(float(corrected_amount), 2),
            reason=str(reason).strip(),
            idempotency_key=idempotency_key,
        )
        self.corrections[correction.correction_id] = correction
        # Synthetic V3 engagement totals only. Never mutates nova_work_revenue_entries.
        row.received_amount = correction.corrected_amount
        row.remaining_amount = round(row.expected_amount - row.received_amount, 2)
        self.idempotency[(organization_id, owner_user_id, "correction", idempotency_key)] = correction.correction_id
        self._audit("HISTORICAL_CORRECTION", organization_id, correction_id=correction.correction_id, ledger="v3_synthetic")
        return correction

    def register_credential(
        self,
        *,
        organization_id: str,
        owner_user_id: str,
        provider: str,
        credential_type: str,
        authorization_scope: str,
        expires_at: datetime | None,
        refresh_capable: bool,
        owner_approved: bool,
    ) -> CredentialMeta:
        row = CredentialMeta(
            credential_id=self._id("V3CRD"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            provider=provider,
            credential_type=credential_type,
            authorization_scope=authorization_scope,
            expires_at=expires_at,
            refresh_capable=refresh_capable,
            owner_approved=owner_approved,
            connection_status="METADATA_ONLY",
            revoked=False,
            secret_present=False,
            token_stored=False,
        )
        self.credentials[row.credential_id] = row
        self._audit("CREDENTIAL_METADATA", organization_id, credential_id=row.credential_id, secret=False)
        return row

    def revoke_credential(self, credential_id: str, *, organization_id: str, owner_user_id: str) -> CredentialMeta:
        row = self.credentials.get(credential_id)
        if row is None:
            raise V3Error("NOT_FOUND", "credential not found", http_status=404)
        self.assert_owner(row.owner_user_id, owner_user_id)
        row.revoked = True
        row.connection_status = "REVOKED"
        return row

    def diagnostics(self, *, organization_id: str, owner_user_id: str) -> dict[str, Any]:
        opps = self.list_opportunities(organization_id=organization_id, owner_user_id=owner_user_id)
        waiting = [item for item in self.approvals.values() if item.organization_id == organization_id and item.status in {"REQUESTED", "PENDING"}]
        stale = [item for item in opps if item.expires_at and item.expires_at < self.now]
        stalled = [
            item
            for item in self.engagements.values()
            if item.organization_id == organization_id
            and item.owner_user_id == owner_user_id
            and item.status in {"ACTIVE", "DELIVERABLE_READY"}
        ]
        expired_creds = [
            item
            for item in self.credentials.values()
            if item.organization_id == organization_id
            and item.expires_at is not None
            and item.expires_at < self.now
        ]
        failed_deliveries = [item for item in self.messages.values() if item.status not in {"MOCK_SENT", "PREPARED", "VALIDATED"}]
        discrepancies = [
            event
            for event in self.events.values()
            if event.organization_id == organization_id and event.applied_to_ledger
        ]
        return {
            "live_flags": live_flags(),
            "adapter_registry": registry(),
            "worker_run_status": "PREPARE_ONLY",
            "connector_status": "SYNTHETIC",
            "adapter_failures": len([item for item in self.adapter_failures if item["organization_id"] == organization_id]),
            "retry_count": sum(job.retry_count for job in self.jobs.values() if job.organization_id == organization_id),
            "stale_opportunities": len(stale),
            "stalled_engagements": len(stalled),
            "failed_mock_delivery": len(failed_deliveries),
            "reconciliation_discrepancies": len(discrepancies),
            "credential_expirations": len(expired_creds),
            "approvals_waiting": len(waiting),
            "secrets_exposed": False,
            "classifications": list(CLASSIFICATIONS),
        }

    def lab_snapshot(self, *, organization_id: str, owner_user_id: str) -> dict[str, Any]:
        def _owned(mapping):
            return [
                item
                for item in mapping.values()
                if getattr(item, "organization_id", None) == organization_id
                and getattr(item, "owner_user_id", None) == owner_user_id
            ]

        return {
            "opportunities": [self.opportunity_out(item) for item in _owned(self.opportunities)],
            "applications": [item.__dict__ | {"externally_submitted": False} for item in _owned(self.proposals)],
            "clients": [item.__dict__ for item in _owned(self.clients)],
            "active_work": [item.__dict__ for item in _owned(self.work_items)],
            "deliverables": [
                {"work_item_id": item.work_item_id, "deliverable": item.deliverable, "delivery_status": item.delivery_status}
                for item in _owned(self.work_items)
            ],
            "invoices": [item.__dict__ | {"stripe_invoice_created": False} for item in _owned(self.invoices)],
            "payments": [
                {
                    "engagement_id": item.engagement_id,
                    "received": item.received_amount,
                    "remaining": item.remaining_amount,
                    "status": item.status,
                }
                for item in _owned(self.engagements)
            ],
            "workers": [item.__dict__ | {"live_worker": False} for item in _owned(self.jobs)],
            "connectors": [item.__dict__ for item in _owned(self.connectors)] or registry(),
            "engagements": [item.__dict__ for item in _owned(self.engagements)],
            "tasks": [item.__dict__ for item in _owned(self.work_items)],
            "approvals": [item.__dict__ for item in _owned(self.approvals)],
            "communications": [item.__dict__ | {"sent_externally": False} for item in _owned(self.messages)],
            "alerts": self.diagnostics(organization_id=organization_id, owner_user_id=owner_user_id),
            "audit": [item for item in self.audit if item.get("organization_id") == organization_id][-50:],
            "growth": get_growth_kernel().growth_dashboard(organization_id=organization_id, owner_user_id=owner_user_id),
            "growth_crm": get_growth_kernel().crm_views(organization_id=organization_id, owner_user_id=owner_user_id),
            "growth_leads": get_growth_kernel().filter_leads(organization_id=organization_id, owner_user_id=owner_user_id),
            "shield": get_growth_kernel().shield_dashboard(organization_id=organization_id, owner_user_id=owner_user_id),
        }

    def persist(self, store: V3Store | None = None) -> int:
        target = store or self.store or V3Store()
        self.store = target
        if self.fail_next_persist:
            self.fail_next_persist = False
            raise RuntimeError("injected database write failure")
        written = 0
        for row in self.opportunities.values():
            target.upsert(
                "nova_v3_opportunities",
                {
                    "opportunity_id": row.opportunity_id,
                    "organization_id": row.organization_id,
                    "owner_user_id": row.owner_user_id,
                    "fingerprint": row.fingerprint,
                },
                row,
            )
            target.upsert(
                "nova_v3_opportunity_sources",
                {
                    "source_id": f"{row.opportunity_id}:src",
                    "organization_id": row.organization_id,
                    "owner_user_id": row.owner_user_id,
                },
                {"provider_id": row.provider_id, "source_kind": row.source_kind, "provenance": row.provenance},
            )
            target.upsert(
                "nova_v3_classifications",
                {
                    "classification_id": f"{row.opportunity_id}:cls",
                    "organization_id": row.organization_id,
                    "owner_user_id": row.owner_user_id,
                },
                row.score_explanation or {"classification": row.classification, "score": row.score},
            )
            written += 1
        mapping = [
            ("nova_v3_clients", "client_id", self.clients),
            ("nova_v3_engagements", "engagement_id", self.engagements),
            ("nova_v3_proposals", "proposal_id", self.proposals),
            ("nova_v3_approvals", "approval_id", self.approvals),
            ("nova_v3_work_items", "work_item_id", self.work_items),
            ("nova_v3_messages", "message_id", self.messages),
            ("nova_v3_invoices", "invoice_id", self.invoices),
            ("nova_v3_payment_events", "event_id", self.events),
            ("nova_v3_corrections", "correction_id", self.corrections),
            ("nova_v3_scheduler_jobs", "job_id", self.jobs),
            ("nova_v3_credentials", "credential_id", self.credentials),
        ]
        for table, key_name, rows in mapping:
            for row in rows.values():
                extra = {
                    key_name: getattr(row, key_name),
                    "organization_id": row.organization_id,
                    "owner_user_id": row.owner_user_id,
                }
                if table == "nova_v3_scheduler_jobs":
                    extra["kind"] = row.kind
                    extra["period_key"] = row.period_key
                target.upsert(table, extra, row)
                written += 1
        for row in self.connectors.values():
            target.upsert(
                "nova_v3_connectors",
                {
                    "connector_id": row.connector_id,
                    "organization_id": row.organization_id,
                    "owner_user_id": row.owner_user_id,
                },
                row,
            )
            written += 1
        for row in self.webhooks.values():
            target.upsert(
                "nova_v3_webhooks",
                {
                    "event_id": row.event_id,
                    "organization_id": row.organization_id,
                    "owner_user_id": row.owner_user_id,
                    "payload_hash": row.payload_hash,
                },
                row,
            )
            written += 1
        for item in self.audit[-200:]:
            target.upsert(
                "nova_v3_audit",
                {
                    "organization_id": item.get("organization_id") or "",
                    "owner_user_id": item.get("owner_user_id"),
                },
                item,
            )
            written += 1
        written += get_growth_kernel().persist(target)
        return written

    def check_credentials(self, *, organization_id: str, owner_user_id: str) -> list[CredentialMeta]:
        expired: list[CredentialMeta] = []
        for row in self.credentials.values():
            if row.organization_id != organization_id or row.owner_user_id != owner_user_id:
                continue
            if row.revoked:
                continue
            if row.expires_at is not None and row.expires_at <= self.now:
                row.connection_status = "HUMAN_ACTION_REQUIRED"
                expired.append(row)
                for connector in self.connectors.values():
                    if connector.owner_user_id == owner_user_id and connector.organization_id == organization_id:
                        if connector.kind in {"opportunity_source", "email", "crm", "invoice_delivery", "payment_processor"}:
                            connector.state = "HUMAN_ACTION_REQUIRED"
                self._audit("CREDENTIAL_EXPIRED", organization_id, credential_id=row.credential_id)
        return expired

    def pause_engagement(self, engagement_id: str, *, organization_id: str, owner_user_id: str) -> Engagement:
        return self.set_engagement_status(engagement_id, organization_id=organization_id, owner_user_id=owner_user_id, status="ON_HOLD")

    def register_connector(
        self, *, organization_id: str, owner_user_id: str, kind: str, connector_id: str | None = None, state: str = "CONNECTED"
    ) -> SimulatedConnector:
        if kind not in CONNECTOR_KINDS:
            raise V3Error("INVALID_CONNECTOR", "unknown connector kind", http_status=400)
        row = SimulatedConnector(
            connector_id=connector_id or self._id("V3CON"),
            kind=kind,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            state=state,
        )
        self.connectors[row.connector_id] = row
        self._audit("CONNECTOR_REGISTERED", organization_id, connector_id=row.connector_id, live=False)
        return row

    def call_connector(self, connector_id: str, *, organization_id: str, owner_user_id: str) -> dict[str, Any]:
        row = self.connectors.get(connector_id)
        if row is None:
            raise V3Error("NOT_FOUND", "connector not found", http_status=404)
        self.assert_owner(row.owner_user_id, owner_user_id)
        try:
            return row.call()
        except V3Error:
            self._audit("CONNECTOR_FAILURE", organization_id, connector_id=connector_id, state=row.state)
            raise

    def ingest_lab_webhook(self, *, organization_id: str, owner_user_id: str, provider: str, event_id: str, payload: dict[str, Any], signature: str) -> Any:
        event = ingest_webhook(
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            provider=provider,
            event_id=event_id,
            payload=payload,
            signature=signature,
            existing_ids=set(self.webhooks),
        )
        self.webhooks[event.event_id] = event
        self._audit("WEBHOOK_SYNTHETIC", organization_id, event_id=event_id, duplicate=event.duplicate)
        return event

    def tick_worker(self, *, organization_id: str, owner_user_id: str, worker_id: str = "worker-a") -> list[ScheduledJob]:
        if live_flags()["BACKGROUND_WORKER_ENABLED"]:
            raise V3Error("LIVE_DISABLED", "production worker cannot start")
        if self.worker_shutdown:
            return []
        ran: list[ScheduledJob] = []
        lease_mismatches = 0
        crashed = False
        for job in list(self.jobs.values()):
            if job.organization_id != organization_id or job.owner_user_id != owner_user_id:
                continue
            recover_stale(job, now=self.now)
            if job.ref_id:
                engagement = self.engagements.get(job.ref_id)
                if engagement and engagement.status in FROZEN:
                    job.status = "CANCELLED"
                    continue
                if engagement and (engagement.status == "ON_HOLD" or engagement.workflow_state == "ON_HOLD"):
                    continue
            if job.status in {"PAUSED", "CANCELLED", "ARCHIVED", "EXECUTED"} or job.dead_letter:
                continue
            if job.next_run_at and job.next_run_at > self.now and job.run_count > 0:
                continue
            try:
                lease_job(job, worker_id=worker_id, now=self.now, ttl=timedelta(seconds=30))
                if self.crash_before_job_commit:
                    self.crash_before_job_commit = False
                    raise V3Error("WORKER_CRASH", "synthetic crash before commit")
                if job.kind == "credential_expiry_check":
                    self.check_credentials(organization_id=organization_id, owner_user_id=owner_user_id)
                elif job.kind == "connector_health_check":
                    connector = next((item for item in self.connectors.values() if item.owner_user_id == owner_user_id), None)
                    if connector and connector.state == "TEMPORARY_FAILURE":
                        job.attempts += 1
                        job.retry_count += 1
                        job.last_error = "connector temporary failure"
                        job.lease_owner = None
                        job.status = "PREPARED"
                        job.next_run_at = self.now + timedelta(seconds=backoff_seconds(job.attempts))
                        if job.attempts >= job.max_attempts:
                            job.dead_letter = True
                            job.status = "DEAD_LETTER"
                        continue
                    if connector and connector.state in {"AUTH_EXPIRED", "HUMAN_ACTION_REQUIRED"}:
                        job.last_error = connector.state
                        job.lease_owner = None
                        job.status = "PREPARED"
                        continue
                job.status = "EXECUTED"
                job.run_count += 1
                job.lease_owner = None
                job.next_run_at = next_run(job.frequency or "daily", job.timezone_name, self.now)
                job.run_history.append({"at": self.now.isoformat(), "worker_id": worker_id, "live": False, "kind": job.kind})
                ran.append(job)
            except V3Error as exc:
                if exc.code == "LEASE_MISMATCH":
                    lease_mismatches += 1
                    continue
                if exc.code == "WORKER_CRASH":
                    crashed = True
                    job.last_error = str(exc)
                    continue
                job.last_error = str(exc)
        if lease_mismatches and not ran and not crashed:
            raise V3Error("LEASE_MISMATCH", "job is leased by another worker")
        return ran

    def retry_job(self, job_id: str, *, organization_id: str, owner_user_id: str) -> ScheduledJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise V3Error("NOT_FOUND", "job not found", http_status=404)
        self.assert_owner(job.owner_user_id, owner_user_id)
        if job.status == "CANCELLED":
            raise V3Error("JOB_NOT_ACTIVE", "cancelled job cannot retry")
        job.dead_letter = False
        job.status = "PREPARED"
        job.lease_owner = None
        return job

    def decide_opportunity(self, opportunity_id: str, *, organization_id: str, owner_user_id: str, decision: str) -> Opportunity:
        opp = self.get_opportunity(opportunity_id, organization_id=organization_id, owner_user_id=owner_user_id)
        wanted = decision.upper()
        if wanted == "APPROVED":
            opp.workflow_state = workflow_transition(opp.workflow_state, "OWNER_REVIEW")
            opp.status = "OWNER_REVIEW"
        elif wanted == "REJECTED":
            opp.workflow_state = workflow_transition(opp.workflow_state, "REJECTED")
            opp.status = "REJECTED"
        else:
            raise V3Error("INVALID_DECISION", "opportunity decision must be APPROVED or REJECTED", http_status=400)
        self._audit("OPPORTUNITY_DECISION", organization_id, opportunity_id=opportunity_id, decision=wanted)
        return opp

    def lab_action(self, action: str, payload: dict[str, Any], *, organization_id: str, owner_user_id: str) -> Any:
        name = action.strip().lower().replace("-", "_")

        def _auto_approval(action_name: str, target_id: str, body: dict[str, Any]) -> str:
            if payload.get("approval_id"):
                return str(payload["approval_id"])
            row = self.request_approval(
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                action=action_name,
                target_id=target_id,
                payload=body,
                idempotency_key=payload.get("idempotency_key"),
            )
            self.decide_approval(row.approval_id, organization_id=organization_id, owner_user_id=owner_user_id, decision="APPROVED")
            return row.approval_id
        if name == "approve_opportunity":
            return self.decide_opportunity(payload["opportunity_id"], organization_id=organization_id, owner_user_id=owner_user_id, decision="APPROVED")
        if name == "reject_opportunity":
            return self.decide_opportunity(payload["opportunity_id"], organization_id=organization_id, owner_user_id=owner_user_id, decision="REJECTED")
        if name == "prepare_proposal":
            return self.prepare_proposal(payload["opportunity_id"], organization_id=organization_id, owner_user_id=owner_user_id)
        if name == "approve_proposal":
            row = self.request_approval(
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                action="MOCK_SUBMISSION",
                target_id=payload["proposal_id"],
                payload={"proposal_id": payload["proposal_id"]},
                idempotency_key=payload.get("idempotency_key"),
            )
            return self.decide_approval(row.approval_id, organization_id=organization_id, owner_user_id=owner_user_id, decision="APPROVED")
        if name == "mock_submit":
            approval_id = payload.get("approval_id") or _auto_approval(
                "MOCK_SUBMISSION", payload["proposal_id"], {"proposal_id": payload["proposal_id"]}
            )
            return self.mock_submit(payload["proposal_id"], organization_id=organization_id, owner_user_id=owner_user_id, approval_id=approval_id)
        if name == "create_engagement":
            return self.accept_synthetic(payload["proposal_id"], organization_id=organization_id, owner_user_id=owner_user_id)
        if name == "create_task":
            work_type = payload.get("work_type") or "administrative_reporting"
            approval_id = _auto_approval(
                "WORK_EXECUTE",
                payload["engagement_id"],
                {"work_type": work_type, "engagement_id": payload["engagement_id"]},
            )
            return self.create_work_item(
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                engagement_id=payload["engagement_id"],
                work_type=work_type,
                source_inputs=payload.get("source_inputs") or {"notes": "lab"},
                approval_id=approval_id,
            )
        if name == "complete_synthetic_task":
            return self.execute_work(payload["work_item_id"], organization_id=organization_id, owner_user_id=owner_user_id)
        if name == "prepare_deliverable":
            return self.execute_work(payload["work_item_id"], organization_id=organization_id, owner_user_id=owner_user_id)
        if name == "approve_deliverable":
            return self.owner_approve_deliverable(payload["work_item_id"], organization_id=organization_id, owner_user_id=owner_user_id)
        if name == "mock_deliver":
            return self.mock_deliver(payload["work_item_id"], organization_id=organization_id, owner_user_id=owner_user_id)
        if name == "generate_invoice":
            return self.create_invoice(
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                engagement_id=payload["engagement_id"],
                amount=float(payload.get("amount") or 0),
                kind=payload.get("kind") or "fixed",
            )
        if name == "approve_invoice":
            approval_id = payload.get("approval_id") or _auto_approval(
                "INVOICE_MOCK_DELIVER", payload["invoice_id"], {"invoice_id": payload["invoice_id"]}
            )
            return self.approve_invoice(
                payload["invoice_id"], organization_id=organization_id, owner_user_id=owner_user_id, approval_id=approval_id
            )
        if name == "mock_send_invoice":
            return self.mock_deliver_invoice(payload["invoice_id"], organization_id=organization_id, owner_user_id=owner_user_id)
        if name == "record_synthetic_partial_payment":
            return self.confirm_received(
                payload["engagement_id"],
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                total_received_so_far=float(payload["amount"]),
                idempotency_key=payload.get("idempotency_key"),
            )
        if name == "record_synthetic_final_payment":
            return self.confirm_received(
                payload["engagement_id"],
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                total_received_so_far=float(payload["amount"]),
                idempotency_key=payload.get("idempotency_key"),
            )
        if name == "pause_worker":
            return self.pause_job(payload["job_id"], organization_id=organization_id, owner_user_id=owner_user_id)
        if name == "resume_worker":
            return self.resume_job(payload["job_id"], organization_id=organization_id, owner_user_id=owner_user_id)
        if name == "retry_failed_worker":
            return self.retry_job(payload["job_id"], organization_id=organization_id, owner_user_id=owner_user_id)
        if name == "revoke_approval":
            return self.revoke_approval(payload["approval_id"], organization_id=organization_id, owner_user_id=owner_user_id)
        if name == "archive_engagement":
            return self.set_engagement_status(
                payload["engagement_id"], organization_id=organization_id, owner_user_id=owner_user_id, status="ARCHIVED"
            )
        if name == "growth_synthetic_convert":
            return get_growth_kernel().convert_synthetic_fixture(
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                organization_name=str(payload.get("organization_name") or "Convert Co"),
            )
        raise V3Error("UNKNOWN_LAB_ACTION", f"unsupported lab action {action}", http_status=400)


_KERNEL: NovaV3Kernel | None = None


def get_kernel() -> NovaV3Kernel:
    global _KERNEL
    if _KERNEL is None:
        _KERNEL = NovaV3Kernel()
    return _KERNEL


def reset_kernel() -> NovaV3Kernel:
    global _KERNEL
    reset_growth_kernel()
    _KERNEL = NovaV3Kernel()
    return _KERNEL
