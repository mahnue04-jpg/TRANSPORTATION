"""Inactive read-only casting application service boundary.

This module defines a server-only composition seam for future authenticated routes.
It registers no endpoint, performs no writes, and never accepts client-supplied
membership evidence. All lookups must query trusted storage using the verified
Nova session identity.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .casting_access import CastingAccessDenied, read_application
from .casting_membership import verified_casting_member


def read_organizer_application(
    *,
    session_user_id: str,
    session_tenant_id: str,
    casting_organization_id: str,
    application_id: str,
    membership_lookup: Callable[[str, str], Mapping[str, object] | None],
    campaign_lookup: Callable[[str], Mapping[str, Any] | None],
    application_lookup: Callable[[str], Mapping[str, Any] | None],
) -> dict[str, Any]:
    """Fail closed until verified identity, membership and owned records agree."""
    if not all((session_user_id, session_tenant_id, casting_organization_id, application_id)):
        raise CastingAccessDenied("Application unavailable")
    actor = verified_casting_member(
        session_user_id=session_user_id,
        session_tenant_id=session_tenant_id,
        organization_id=casting_organization_id,
        lookup=membership_lookup,
    )
    if actor is None:
        raise CastingAccessDenied("Application unavailable")
    application = application_lookup(application_id)
    if not application or application.get("owner_id") != casting_organization_id:
        raise CastingAccessDenied("Application unavailable")
    campaign_id = application.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise CastingAccessDenied("Application unavailable")
    campaign = campaign_lookup(campaign_id)
    if not campaign or campaign.get("owner_id") != casting_organization_id:
        raise CastingAccessDenied("Application unavailable")
    return read_application(actor=actor, application=dict(application), campaign=dict(campaign))
