"""Inactive, human-controlled audition application transition policy.

No database writes, public routes, notifications, or external deliveries.
Caller must authenticate and fetch ownership and organization data server-side.
"""
from __future__ import annotations

from enum import Enum

from .casting_policy import CastingActor, CastingRole, may_review_application


class ApplicationState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"


def may_transition_application(
    actor: CastingActor,
    *,
    applicant_id: str,
    organization_id: str,
    current: ApplicationState,
    target: ApplicationState,
    consent_recorded: bool = False,
    campaign_open: bool = False,
) -> bool:
    """Fail closed: applicants submit/withdraw; reviewers cannot alter submission state."""
    if not actor.user_id or current == target:
        return False
    if actor.role is not CastingRole.APPLICANT or actor.user_id != applicant_id:
        return False
    if current is ApplicationState.DRAFT and target is ApplicationState.SUBMITTED:
        return consent_recorded and campaign_open
    if current is ApplicationState.SUBMITTED and target is ApplicationState.WITHDRAWN:
        return True
    return False


def may_schedule_callback(actor: CastingActor, *, organization_id: str, application_state: ApplicationState) -> bool:
    """Only verified scoped organizers/reviewers may prepare a callback proposal."""
    return application_state is ApplicationState.SUBMITTED and may_review_application(
        actor, organization_id=organization_id
    )
