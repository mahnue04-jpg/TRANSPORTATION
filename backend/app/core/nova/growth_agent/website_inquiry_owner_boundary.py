"""Explicit owner/tenant boundary for a future website-inquiry source.

Not exposed as an HTTP route. No Cloudflare client or network access. The
FastAPI caller must first validate JWT/session state via require_growth_owner.
This boundary intentionally does not inherit support-role cross-tenant scope.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.auth import ROLE_ADMIN, UserContext
from app.core.nova.growth_agent.flags import growth_agent_enabled
from app.core.nova.growth_agent.website_inquiry_readonly import (
    ReadOnlyKVSource,
    read_website_inquiries,
)


class WebsiteInquiryAccessDenied(Exception):
    """Do not reveal tenant/source details in errors."""


def read_owner_website_inquiries(
    user: UserContext,
    requested_organization_id: str | None,
    source_for_organization: Callable[[str], ReadOnlyKVSource],
    *,
    trusted_synthetic_fixture: bool = False,
) -> dict[str, Any]:
    """Fail closed before opening a source; source selected by validated tenant.

    Deliberately admin-owner only, excluding super-admin support impersonation.
    Call from an authenticated FastAPI route only after require_growth_owner;
    never accept user-supplied source key, KV namespace or Cloudflare token.
    """
    if not growth_agent_enabled():
        raise WebsiteInquiryAccessDenied("website_inquiry_access_denied")
    if not isinstance(user, UserContext):
        raise WebsiteInquiryAccessDenied("website_inquiry_access_denied")
    if user.role != ROLE_ADMIN or not user.user_id or not user.organization_id:
        raise WebsiteInquiryAccessDenied("website_inquiry_access_denied")
    if user.organization_id == "global":
        raise WebsiteInquiryAccessDenied("website_inquiry_access_denied")
    if requested_organization_id is not None and requested_organization_id != user.organization_id:
        raise WebsiteInquiryAccessDenied("website_inquiry_access_denied")
    # The trusted source factory is called only after all access gates.
    source = source_for_organization(user.organization_id)
    records = read_website_inquiries(source, trusted_synthetic_fixture=trusted_synthetic_fixture)
    return {
        "status": "ok",
        "organization_id": user.organization_id,
        "count": len(records),
        "inquiries": records,
        "read_only": True,
    }
