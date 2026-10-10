"""Inactive application-access boundary for future Nova Casting endpoints.

Callers must supply an actor derived from a validated Nova session and trusted
server-side campaign/application lookups. No routes or database writes here.
"""
from __future__ import annotations

from .casting_policy import CastingActor, may_view_application, may_review_application
from .casting_workflow_policy import ApplicationState, may_transition_application
from .casting_responses import applicant_application_view, organizer_application_view


class CastingAccessDenied(PermissionError):
    pass


def read_application(*, actor: CastingActor | None, application: dict, campaign: dict) -> dict:
    if (actor is None or not application.get("id") or not application.get("applicant_id")
            or not application.get("campaign_id") or not application.get("status")
            or not application.get("created_at") or not campaign.get("id")
            or not campaign.get("owner_id")):
        raise CastingAccessDenied("Application unavailable")
    if application["campaign_id"] != campaign["id"]:
        raise CastingAccessDenied("Application unavailable")
    if application.get("owner_id") != campaign.get("owner_id"):
        raise CastingAccessDenied("Application unavailable")
    if not may_view_application(actor, applicant_id=application["applicant_id"], organization_id=campaign["owner_id"]):
        raise CastingAccessDenied("Application unavailable")
    if actor.user_id == application["applicant_id"]:
        return applicant_application_view(application)
    return organizer_application_view(application)


def submit_application(*, actor: CastingActor | None, application: dict, campaign: dict, consent_recorded: bool) -> bool:
    if (actor is None or not application.get("id") or not application.get("applicant_id")
            or not application.get("campaign_id") or not campaign.get("id")
            or not campaign.get("owner_id")):
        return False
    if application["campaign_id"] != campaign["id"]:
        return False
    if application.get("owner_id") != campaign.get("owner_id"):
        return False
    try:
        state = ApplicationState(application["status"])
    except (KeyError, ValueError):
        return False
    return may_transition_application(
        actor,
        applicant_id=application["applicant_id"],
        organization_id=campaign["owner_id"],
        current=state,
        target=ApplicationState.SUBMITTED,
        consent_recorded=consent_recorded,
        campaign_open=False,  # Fail closed: campaign activation is not yet supported.
    )
