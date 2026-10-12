"""Fail-closed boundary between verified Nova sessions and casting policy.

These are pure adapters, not live endpoints. Organization membership must come
from the server-side membership store, never request JSON or token role alone.
"""
from __future__ import annotations

from .casting_policy import CastingActor, CastingRole


def from_verified_session(
    *, session_user_id: str, membership_user_id: str,
    membership_org_id: str, membership_role: str,
    membership_active: bool, organization_verified: bool,
) -> CastingActor | None:
    if not session_user_id or session_user_id != membership_user_id:
        return None
    if not membership_active or not organization_verified or not membership_org_id:
        return None
    try:
        role = CastingRole(membership_role)
    except ValueError:
        return None
    if role not in (CastingRole.ORGANIZER, CastingRole.REVIEWER):
        return None
    return CastingActor(
        user_id=session_user_id, organization_id=membership_org_id,
        role=role, verified_organization=True,
    )


def applicant_from_verified_session(*, session_user_id: str) -> CastingActor | None:
    if not session_user_id:
        return None
    return CastingActor(session_user_id, None, CastingRole.APPLICANT)
