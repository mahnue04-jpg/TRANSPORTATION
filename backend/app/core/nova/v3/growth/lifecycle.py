"""Lead lifecycle. Illegal transitions fail closed."""
from __future__ import annotations

from app.core.nova.v3.errors import V3Error

FORWARD = {
    "DISCOVERED": {"QUALIFYING", "QUALIFIED", "DISQUALIFIED", "OWNER_REVIEW", "DO_NOT_CONTACT", "ARCHIVED", "ON_HOLD"},
    "QUALIFYING": {"QUALIFIED", "DISQUALIFIED", "OWNER_REVIEW", "DO_NOT_CONTACT", "ON_HOLD"},
    "QUALIFIED": {"OWNER_REVIEW", "OUTREACH_READY", "DISQUALIFIED", "DO_NOT_CONTACT", "ON_HOLD", "DEMO_REQUESTED"},
    "DISQUALIFIED": {"ARCHIVED", "QUALIFYING"},
    "OWNER_REVIEW": {"OUTREACH_READY", "DISQUALIFIED", "DO_NOT_CONTACT", "ON_HOLD"},
    "OUTREACH_READY": {"CONTACTED_MOCK", "ON_HOLD", "DO_NOT_CONTACT", "OWNER_REVIEW"},
    "CONTACTED_MOCK": {"ENGAGED", "DEMO_REQUESTED", "LOST", "ON_HOLD", "DO_NOT_CONTACT", "OUTREACH_READY"},
    "ENGAGED": {"DEMO_REQUESTED", "PROPOSAL_READY", "LOST", "ON_HOLD", "DO_NOT_CONTACT"},
    "DEMO_REQUESTED": {"DEMO_SCHEDULED", "LOST", "ON_HOLD", "ENGAGED"},
    "DEMO_SCHEDULED": {"PROPOSAL_READY", "ENGAGED", "LOST", "ON_HOLD"},
    "PROPOSAL_READY": {"NEGOTIATION", "WON", "LOST", "ON_HOLD"},
    "NEGOTIATION": {"WON", "LOST", "PROPOSAL_READY", "ON_HOLD"},
    "WON": {"ARCHIVED"},
    "LOST": {"ARCHIVED", "QUALIFYING"},
    "ON_HOLD": {"QUALIFIED", "OUTREACH_READY", "ENGAGED", "DO_NOT_CONTACT", "ARCHIVED"},
    "DO_NOT_CONTACT": {"ARCHIVED"},
    "ARCHIVED": set(),
}


def can_transition(current: str, target: str) -> bool:
    cur = str(current or "").upper()
    nxt = str(target or "").upper()
    if cur == nxt:
        return True
    return nxt in FORWARD.get(cur, set())


def transition(current: str, target: str) -> str:
    nxt = str(target or "").upper()
    if not can_transition(current, nxt):
        raise V3Error("ILLEGAL_TRANSITION", f"cannot transition {current} → {nxt}", http_status=409)
    return nxt
