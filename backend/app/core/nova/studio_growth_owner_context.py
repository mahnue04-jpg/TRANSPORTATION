"""Proposed authenticated owner context for Studio -> Growth grant actions.

PURE validation only, default-off, with zero imports from app.main/routers.
Callers MUST pass a UserContext returned by server-side
get_current_user_context (never one constructed from request body) and a
trusted membership verifier. This module cannot verify JWTs itself.

No route, database migration, customer access or service connection is enabled.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Callable

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_OWNER_ROLE = "admin"


@dataclass(frozen=True)
class VerifiedStudioGrowthOwner:
    user_id: str
    organization_id: str


def authorize_owner_grant_context(
    *,
    authenticated_user: object,
    requested_organization_id: str,
    membership_reader: Callable[[str, str], bool],
    enabled: bool | None = None,
) -> VerifiedStudioGrowthOwner:
    """Validate only *trusted* auth-context attributes and tenant membership.

    `membership_reader` must perform a fresh server-side tenant membership
    check for the exact user and organization, and fail closed on exceptions.
    A test callback or user-controlled object does not provide real security.
    """
    if enabled is None:
        enabled = os.getenv("NOVA_STUDIO_GROWTH_OWNER_GRANTS_ENABLED") == "true"
    if enabled is not True or os.getenv("NOVA_STUDIO_GROWTH_LIVE_ENABLED") == "true":
        raise PermissionError("Studio-Growth owner grant interface disabled")
    user_id = getattr(authenticated_user, "user_id", None)
    org = getattr(authenticated_user, "organization_id", None)
    role = getattr(authenticated_user, "role", None)
    if not (
        isinstance(user_id, str) and _ID.fullmatch(user_id)
        and isinstance(org, str) and _ID.fullmatch(org)
        and isinstance(requested_organization_id, str)
        and _ID.fullmatch(requested_organization_id)
        and org == requested_organization_id
        and role == _OWNER_ROLE
    ):
        raise PermissionError("signed admin session with exact tenant required")
    if not callable(membership_reader):
        raise PermissionError("server membership verifier required")
    try:
        is_member = membership_reader(user_id, org)
    except Exception as exc:
        raise PermissionError("membership lookup failed closed") from exc
    if is_member is not True:
        raise PermissionError("owner tenant membership not verified")
    return VerifiedStudioGrowthOwner(user_id=user_id, organization_id=org)
