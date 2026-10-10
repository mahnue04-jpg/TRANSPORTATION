"""Inactive trusted casting membership resolution.

The resolver must be a server-controlled database lookup. Never pass request
JSON or unverified JWT role claims as membership evidence.
"""
from __future__ import annotations
from collections.abc import Callable, Mapping

from .casting_identity import from_verified_session
from .casting_policy import CastingActor


def verified_casting_member(
    *, session_user_id: str,
    organization_id: str,
    session_tenant_id: str,
    lookup: Callable[[str, str], Mapping[str, object] | None],
) -> CastingActor | None:
    """Reject missing, inactive, mismatched, or unverified membership evidence."""
    if not session_user_id or not organization_id or not session_tenant_id:
        return None
    try:
        record = lookup(session_user_id, organization_id)
    except (LookupError, ConnectionError, TimeoutError):
        return None
    if not record:
        return None
    if record.get("user_id") != session_user_id or record.get("organization_id") != organization_id:
        return None
    if record.get("nova_tenant_id") != session_tenant_id:
        return None
    if record.get("active") is not True or record.get("organization_verified") is not True:
        return None
    role = record.get("casting_role")
    if not isinstance(role, str):
        return None
    return from_verified_session(
        session_user_id=session_user_id,
        membership_user_id=session_user_id,
        membership_org_id=organization_id,
        membership_role=role,
        membership_active=True,
        organization_verified=True,
    )
