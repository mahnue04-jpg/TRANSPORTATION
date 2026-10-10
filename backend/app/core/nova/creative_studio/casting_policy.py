"""Authorization policy for planned Nova Casting APIs.

Pure policy functions only: no endpoint registration, uploads, database calls, or
external submissions. Caller must obtain role and organization membership from
the server-verified Nova session, never from client-supplied request fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CastingRole(str, Enum):
    APPLICANT = "applicant"
    REVIEWER = "reviewer"
    ORGANIZER = "organizer"


@dataclass(frozen=True)
class CastingActor:
    user_id: str
    organization_id: str | None
    role: CastingRole
    verified_organization: bool = False


def may_view_application(actor: CastingActor, *, applicant_id: str, organization_id: str) -> bool:
    if not actor.user_id:
        return False
    if actor.role is CastingRole.APPLICANT:
        return actor.user_id == applicant_id
    return (
        actor.role in (CastingRole.REVIEWER, CastingRole.ORGANIZER)
        and actor.verified_organization
        and bool(actor.organization_id)
        and actor.organization_id == organization_id
    )


def may_review_application(actor: CastingActor, *, organization_id: str) -> bool:
    return (
        bool(actor.user_id)
        and actor.role in (CastingRole.REVIEWER, CastingRole.ORGANIZER)
        and actor.verified_organization
        and bool(actor.organization_id)
        and actor.organization_id == organization_id
    )


def may_manage_campaign(actor: CastingActor, *, organization_id: str) -> bool:
    return (
        bool(actor.user_id)
        and actor.role is CastingRole.ORGANIZER
        and actor.verified_organization
        and bool(actor.organization_id)
        and actor.organization_id == organization_id
    )
