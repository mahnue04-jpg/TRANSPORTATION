"""Default-OFF Growth campaign preview contract for Studio handoff.

This is an owner-only, read-only *preview*, not asset ingestion. The service does
not create campaigns, contact leads, publish advertising or trust an approval
reference supplied by a client. The future server-to-server bridge must resolve
Studio projects and grants from persisted stores before any real handoff.
"""
from __future__ import annotations

import os
import re
from typing import Mapping

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class CampaignPreviewDenied(PermissionError):
    pass


def campaign_preview_enabled() -> bool:
    return os.getenv("NOVA_GROWTH_CAMPAIGN_PREVIEW_ENABLED") == "true" and (
        os.getenv("NOVA_GROWTH_CAMPAIGN_LIVE_ENABLED") != "true"
    )


def build_campaign_preview(
    *, organization_id: str, owner_user_id: str, owner_role: str,
    session_organization_id: str, campaign_id: str, asset_id: str,
    studio_project_id: str, profile: Mapping[str, object],
    enabled: bool | None = None,
) -> dict[str, object]:
    """Metadata-only preview from an owner-authenticated, same-tenant session.

    Tenant and role fields MUST be derived from server auth context. The input
    identifiers are *untrusted references*, not proof of Studio ownership or
    approval. Never claim ingest/authorization succeeds based on this output.
    """
    if enabled is None:
        enabled = campaign_preview_enabled()
    if enabled is not True or os.getenv("NOVA_GROWTH_CAMPAIGN_LIVE_ENABLED") == "true":
        raise CampaignPreviewDenied("campaign preview disabled")
    if (owner_role != "admin" or not all(
        isinstance(x, str) and _ID.fullmatch(x)
        for x in (organization_id, owner_user_id, session_organization_id,
                  campaign_id, asset_id, studio_project_id)
    ) or session_organization_id != organization_id):
        raise CampaignPreviewDenied("exact owner tenant authorization required")
    if not isinstance(profile, Mapping) or (
        profile.get("configured") is not True
        or profile.get("organization_id") != organization_id
        or profile.get("is_synthetic_demo") is not True
        or profile.get("activated") is not False
        or profile.get("agent_disabled") is not True
    ):
        raise CampaignPreviewDenied("inactive, disabled synthetic Growth profile required")
    return {
        "status": "preview_only",
        "organization_id": organization_id,
        "campaign_id": campaign_id,
        "studio_project_id": studio_project_id,
        "asset_id": asset_id,
        "owner_id": owner_user_id,
        "studio_ownership_verified": False,
        "studio_approval_verified": False,
        "campaign_ingested": False,
        "lead_created": False,
        "published": False,
        "outbound_messages_sent": False,
        "billing_triggered": False,
    }
