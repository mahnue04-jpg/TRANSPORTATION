"""Offline evidence gates shared by Nova Work & Revenue and Operations Agent.

Pure validation only: no network, persistence, provider calls or external sends.
A caller must separately persist the returned event in a tenant-scoped transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Mapping


class EvidenceError(ValueError):
    """Missing evidence, invalid transition or unsafe cross-tenant event."""


class Stage(str, Enum):
    DISCOVERED = "discovered"
    QUALIFIED = "qualified"
    DRAFTED = "drafted"
    OWNER_APPROVED = "owner_approved"
    SENT_VERIFIED = "sent_verified"
    REPLIED = "replied"
    CONTRACTED = "contracted"
    JOB_COMPLETED = "job_completed"
    DELIVERED_VERIFIED = "delivered_verified"
    RECEIVED_VERIFIED = "received_verified"


_ALLOWED = {
    Stage.DISCOVERED: {Stage.QUALIFIED},
    Stage.QUALIFIED: {Stage.DRAFTED},
    Stage.DRAFTED: {Stage.OWNER_APPROVED},
    Stage.OWNER_APPROVED: {Stage.SENT_VERIFIED},
    Stage.SENT_VERIFIED: {Stage.REPLIED},
    Stage.REPLIED: {Stage.CONTRACTED},
    Stage.CONTRACTED: {Stage.JOB_COMPLETED},
    Stage.JOB_COMPLETED: {Stage.DELIVERED_VERIFIED},
    Stage.DELIVERED_VERIFIED: {Stage.RECEIVED_VERIFIED},
}

_REQUIRED_EVIDENCE = {
    Stage.QUALIFIED: "source_url",
    Stage.OWNER_APPROVED: "owner_approval_id",
    Stage.SENT_VERIFIED: "transport_receipt_id",
    Stage.REPLIED: "reply_message_id",
    Stage.CONTRACTED: "contract_reference",
    Stage.JOB_COMPLETED: "artifact_sha256",
    Stage.DELIVERED_VERIFIED: "delivery_receipt_id",
    Stage.RECEIVED_VERIFIED: "payment_confirmation_id",
}


@dataclass(frozen=True)
class EvidenceEvent:
    tenant_id: str
    opportunity_id: str
    previous: Stage
    current: Stage
    actor_id: str
    evidence_type: str
    evidence_reference: str
    idempotency_key: str


def make_event(
    *,
    tenant_id: str,
    opportunity_id: str,
    actor_id: str,
    previous: Stage,
    current: Stage,
    evidence: Mapping[str, str],
    record_tenant_id: str,
) -> EvidenceEvent:
    """Validate one requested transition; does not apply or store it."""
    if not all((tenant_id, opportunity_id, actor_id, record_tenant_id)):
        raise EvidenceError("Tenant, opportunity and actor identities are required")
    if tenant_id != record_tenant_id:
        raise EvidenceError("Cross-tenant transition denied")
    if current not in _ALLOWED.get(previous, set()):
        raise EvidenceError("Unsupported stage transition")
    required = _REQUIRED_EVIDENCE.get(current)
    if current == Stage.DRAFTED:
        required = "draft_id"
    if required is None:
        raise EvidenceError("No evidence contract for requested stage")
    reference = evidence.get(required, "").strip()
    if not reference or len(reference) > 1024:
        raise EvidenceError(f"Missing or invalid {required}")
    if current == Stage.SENT_VERIFIED and evidence.get("receipt_kind") != "external_verified":
        raise EvidenceError("Mock or unverified receipt cannot count as sent")
    if current == Stage.RECEIVED_VERIFIED and evidence.get("payment_kind") != "independently_verified":
        raise EvidenceError("Owner assertion alone is not independent payment verification")
    if current == Stage.JOB_COMPLETED:
        if len(reference) != 64 or any(c not in "0123456789abcdef" for c in reference):
            raise EvidenceError("Artifact checksum must be lowercase SHA-256")
    fingerprint = "\x1f".join((tenant_id, opportunity_id, previous.value, current.value, required, reference))
    return EvidenceEvent(
        tenant_id=tenant_id,
        opportunity_id=opportunity_id,
        previous=previous,
        current=current,
        actor_id=actor_id,
        evidence_type=required,
        evidence_reference=reference,
        idempotency_key=sha256(fingerprint.encode("utf-8")).hexdigest(),
    )
