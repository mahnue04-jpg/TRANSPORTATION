"""Owner-reviewed first-customer campaign. No outreach, billing or providers.

Reviews reuse existing tenant-scoped lead events; no new schema or migration.
Order stages are owner assertions, never verified payments or ad attribution.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import func
from sqlalchemy.orm import Session

from .errors import GrowthAgentError
from .models import GaContact, GaLeadEvent

CAMPAIGN = "amicor-follow-up-pilot"
EVENT = "acquisition.followup_pilot.review"
STAGES = ("new", "qualified", "quoted", "ordered", "delivered", "declined")
TRANSITIONS = {
    "new": {"new", "qualified", "declined"},
    "qualified": {"qualified", "quoted", "declined"},
    "quoted": {"quoted", "ordered", "declined"},
    "ordered": {"ordered", "delivered", "declined"},
    "delivered": {"delivered"},
    "declined": {"declined", "new"},
}
PLAN = {
    "code": CAMPAIGN,
    "name": "AMICOR first customer campaign",
    "status": "DRAFT_OWNER_REVIEW",
    "audience": "Small cleaning and home-service businesses with open inquiries or unfinished quotes",
    "offer": "Organize a customer-owned inquiry list, prepare a next-action tracker and draft follow-ups for review.",
    "entry_offer": "Free Scope Check, then a $49 Starter Task only after its scope is agreed",
    "scope": "Remote list organization and drafts. Sending, sensitive records and custom integrations require separate review.",
    "hook": "Quotes waiting for a follow-up? See how an organized next-action list helps you decide what to do next.",
    "call_to_action": "Request a Free Scope Check for your inquiry list.",
    "qualification_questions": [
        "Do you have open inquiries or unfinished quotes?",
        "Can you authorize AMICOR to use the list for this task?",
        "Do you need messages sent, or only prepared for your review?",
        "Does the task require sensitive customer information?",
    ],
    "channels": [
        {"name": "Demonstration content", "action": "Show a synthetic before-and-after list and the deliverable; submit the post for owner approval."},
        {"name": "Existing relationships", "action": "Prepare an introduction request for owner review; send only when authorized."},
        {"name": "Relevant prospects", "action": "Research individual businesses and prepare specific outreach drafts; no automatic sending."},
    ],
    "success_targets": {"paid_pilot_customers": 3, "repeat_or_recurring_customers": 1},
    "targets_are_forecasts": False,
    "automatic_outreach": False,
    "automatic_publishing": False,
    "payment_verification_connected": False,
    "attribution": "Owner assigned CRM contacts; website visits and campaign clicks are not connected",
}


class AcquisitionReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: str | None = None
    stage: Literal["new", "qualified", "quoted", "ordered", "delivered", "declined"]
    has_open_inquiries: StrictBool
    authorized_list_use: StrictBool
    requires_external_sending: StrictBool
    requires_sensitive_data: StrictBool


def campaign_plan() -> dict:
    return deepcopy(PLAN)


def _latest_reviews(db: Session, org: str):
    ranked = db.query(
        GaLeadEvent.id.label("id"),
        func.row_number().over(
            partition_by=GaLeadEvent.contact_id,
            order_by=(GaLeadEvent.created_at.desc(), GaLeadEvent.id.desc()),
        ).label("position"),
    ).filter(GaLeadEvent.organization_id == org, GaLeadEvent.event_type == EVENT).subquery()
    return db.query(GaContact, GaLeadEvent).join(
        GaLeadEvent, (GaLeadEvent.contact_id == GaContact.id)
        & (GaLeadEvent.organization_id == GaContact.organization_id),
    ).join(ranked, ranked.c.id == GaLeadEvent.id).filter(
        ranked.c.position == 1, GaContact.organization_id == org,
        GaContact.is_synthetic_demo.is_(False),
    )


def campaign_board(db: Session, org: str) -> dict:
    latest = _latest_reviews(db, org)
    counts = {stage: 0 for stage in STAGES}
    # Count the entire campaign; the list below is explicitly paginated.
    stage_column = GaLeadEvent.payload_json["stage"].as_string()
    for stage, count in db.query(stage_column, func.count()).filter(
        GaLeadEvent.id.in_(latest.with_entities(GaLeadEvent.id))
    ).group_by(stage_column).all():
        if stage in counts:
            counts[stage] += count
    rows = latest.order_by(GaLeadEvent.created_at.desc(), GaLeadEvent.id.desc()).limit(100).all()
    return {
        "plan": campaign_plan(), "counts": counts,
        "contacts": [{"id": c.id, "display_name": c.display_name,
                      "do_not_contact": c.do_not_contact, "review": e.payload_json} for c, e in rows],
        "contact_limit": 100, "total_reviewed": sum(counts.values()),
        "unassigned_contacts": db.query(GaContact).filter(
            GaContact.organization_id == org, GaContact.is_synthetic_demo.is_(False),
            ~GaContact.id.in_(latest.with_entities(GaContact.id)),
        ).count(),
        "order_evidence": "Owner recorded; payments are not verified",
        "verified_revenue_cents": None,
        "external_actions_performed": False,
    }


def save_campaign_review(db: Session, org: str, contact_id: str, review: AcquisitionReviewIn, *, actor_user_id: str) -> dict:
    contact = db.query(GaContact).filter_by(
        id=contact_id, organization_id=org, is_synthetic_demo=False,
    ).with_for_update().one_or_none()
    if not contact:
        raise GrowthAgentError("CONTACT_NOT_FOUND", "A non-synthetic contact in this organization is required.", http_status=404)
    blockers = []
    if contact.do_not_contact:
        blockers.append("Contact has opted out; do not contact")
    if not review.has_open_inquiries:
        blockers.append("No open inquiries confirmed")
    if not review.authorized_list_use:
        blockers.append("List authorization is not confirmed")
    if review.requires_external_sending:
        blockers.append("External sending needs separate scope review")
    if review.requires_sensitive_data:
        blockers.append("Sensitive-data handling needs separate scope review")
    if review.stage in {"qualified", "quoted", "ordered", "delivered"} and blockers:
        raise GrowthAgentError("SCOPE_REVIEW_REQUIRED", "Resolve scope blockers before advancing this contact.", details={"blockers": blockers})
    previous = _latest_reviews(db, org).filter(GaContact.id == contact_id).one_or_none()
    previous_stage = previous[1].payload_json["stage"] if previous else "new"
    if review.stage not in TRANSITIONS[previous_stage]:
        raise GrowthAgentError("INVALID_CAMPAIGN_TRANSITION", f"Cannot move from {previous_stage} to {review.stage}.")
    payload = {**review.model_dump(exclude={"organization_id"}), "campaign_code": CAMPAIGN,
               "scope_blockers": blockers, "evidence": "owner_review", "payment_verified": False,
               "reviewed_by": actor_user_id}
    if previous and previous[1].payload_json == payload:
        return {"review": payload, "changed": False, "external_actions_performed": False}
    db.add(GaLeadEvent(id=str(uuid4()), organization_id=org, contact_id=contact_id,
                       event_type=EVENT, payload_json=payload))
    db.commit()
    return {"review": payload, "changed": True, "external_actions_performed": False}
