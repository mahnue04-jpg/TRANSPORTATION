"""V3 revenue workflow state machine. Illegal transitions fail closed."""
from __future__ import annotations

from app.core.nova.v3.errors import V3Error

FORWARD = {
    "DISCOVERED": {"QUALIFIED", "OWNER_REVIEW", "PROPOSAL_READY", "REJECTED", "EXPIRED", "CANCELLED", "ON_HOLD"},
    "QUALIFIED": {"OWNER_REVIEW", "PROPOSAL_READY", "REJECTED", "ON_HOLD", "CANCELLED"},
    "OWNER_REVIEW": {"PROPOSAL_READY", "REJECTED", "EXPIRED", "ON_HOLD"},
    "PROPOSAL_READY": {"APPROVED_FOR_SUBMISSION", "MOCK_SUBMITTED", "REJECTED", "EXPIRED", "ON_HOLD"},
    "APPROVED_FOR_SUBMISSION": {"MOCK_SUBMITTED", "REVOKED", "EXPIRED", "REJECTED", "CANCELLED"},
    "MOCK_SUBMITTED": {"WON", "REJECTED", "EXPIRED", "CANCELLED"},
    "WON": {"ACTIVE", "CANCELLED", "ON_HOLD"},
    "ACTIVE": {"WORK_READY", "DELIVERABLE_READY", "INVOICE_DRAFT", "MOCK_INVOICE_SENT", "PARTIALLY_PAID", "PAID", "ON_HOLD", "CANCELLED", "FAILED", "ARCHIVED"},
    "WORK_READY": {"DELIVERABLE_READY", "FAILED", "ON_HOLD", "CANCELLED"},
    "DELIVERABLE_READY": {"APPROVED_FOR_DELIVERY", "FAILED", "ON_HOLD"},
    "APPROVED_FOR_DELIVERY": {"MOCK_DELIVERED", "INVOICE_DRAFT", "REVOKED", "ON_HOLD"},
    "MOCK_DELIVERED": {"INVOICE_DRAFT", "MOCK_INVOICE_SENT", "PARTIALLY_PAID", "PAID", "ON_HOLD", "CANCELLED"},
    "INVOICE_DRAFT": {"INVOICE_APPROVED", "CANCELLED", "ON_HOLD"},
    "INVOICE_APPROVED": {"MOCK_INVOICE_SENT", "REVOKED"},
    "MOCK_INVOICE_SENT": {"PARTIALLY_PAID", "PAID", "DISPUTED", "CANCELLED"},
    "PARTIALLY_PAID": {"PAID", "DISPUTED", "CANCELLED"},
    "PAID": {"CLOSED", "DISPUTED", "ARCHIVED"},
    "CLOSED": {"ARCHIVED"},
    "REJECTED": {"ARCHIVED"},
    "EXPIRED": {"ARCHIVED"},
    "CANCELLED": {"ARCHIVED"},
    "FAILED": {"ON_HOLD", "CANCELLED", "ARCHIVED"},
    "ON_HOLD": {"ACTIVE", "QUALIFIED", "OWNER_REVIEW", "CANCELLED", "ARCHIVED"},
    "DISPUTED": {"PARTIALLY_PAID", "PAID", "CANCELLED", "ARCHIVED"},
    "ARCHIVED": set(),
    "REVOKED": {"OWNER_REVIEW", "CANCELLED", "ARCHIVED"},
}

ALIASES = {
    "LEAD": "DISCOVERED",
    "APPLICATION_PREPARED": "PROPOSAL_READY",
    "SUBMITTED": "MOCK_SUBMITTED",
    "DELIVERED": "MOCK_DELIVERED",
    "INVOICED": "MOCK_INVOICE_SENT",
    "OWNER_APPROVAL": "APPROVED_FOR_DELIVERY",
}


def normalize(state: str) -> str:
    token = str(state or "").upper()
    return ALIASES.get(token, token)


def can_transition(current: str, target: str) -> bool:
    cur = normalize(current)
    nxt = normalize(target)
    if cur == nxt:
        return True
    return nxt in FORWARD.get(cur, set())


def transition(current: str, target: str) -> str:
    nxt = normalize(target)
    if not can_transition(current, nxt):
        raise V3Error(
            "ILLEGAL_TRANSITION",
            f"cannot transition {normalize(current)} → {nxt}",
            http_status=409,
        )
    return nxt
