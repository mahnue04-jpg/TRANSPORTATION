"""Disabled-by-default, read-only Studio -> Growth approval preview bridge.

Not an HTTP route; never registered in app.main. No external network,
publishing, provider calls, schema migration or database writes. A trusted
server route must independently authenticate UserContext and obtain a fresh
membership check before invoking this preview.
"""
from __future__ import annotations

from datetime import datetime
import os
from typing import Mapping

from .studio_growth_adapter import (
    preview_growth_campaign_from_studio, read_studio_asset_for_growth,
)
from .studio_growth_owner_context import (
    authorize_owner_grant_context,
)


def preview_approved_studio_campaign(
    *,
    authenticated_user: object,
    requested_organization_id: str,
    membership_reader: object,
    studio_store: object,
    grant_ledger: object,
    growth_profile: Mapping[str, object],
    project_id: str,
    asset_id: str,
    campaign_id: str,
    studio_service_principal: str,
    now: datetime,
    enabled: bool | None = None,
) -> dict[str, object]:
    """Only preview when all server-derived data matches one approved grant.

    Explicit prerequisites:
      - authenticated_user comes from get_current_user_context;
      - membership_reader comes from a trusted, fresh platform DB query;
      - studio_store uses owner-scoped Studio persistence;
      - grant_ledger points at an isolated, provisioned grant table;
      - growth_profile comes from trusted GrowthAgentService.get_profile(org).
    This function DOES NOT independently prove these prerequisites. No endpoint
    is registered. The staging-adapter and owner-grant switches default off
    independently and cannot authorize real publishing.
    """
    if enabled is None:
        enabled = os.getenv("NOVA_STUDIO_GROWTH_STAGING_ADAPTER_ENABLED") == "true"
    if enabled is not True or os.getenv("NOVA_STUDIO_GROWTH_LIVE_ENABLED") == "true":
        raise PermissionError("Studio-Growth bridge disabled")

    # Do not forward the staging-adapter flag. Owner grants have their own
    # default-off switch and must stay independently disableable.
    owner = authorize_owner_grant_context(
        authenticated_user=authenticated_user,
        requested_organization_id=requested_organization_id,
        membership_reader=membership_reader,
    )

    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone-aware preview time required")
    if not callable(getattr(grant_ledger, "read_approved", None)):
        raise PermissionError("trusted approved grant reader required")
    requested_campaign_id = campaign_id

    def approval_reader(*, organization_id: str, owner_id: str,
                        project_id: str, asset_id: str, campaign_id: str,
                        action: str):
        if (
            organization_id != owner.organization_id
            or owner_id != owner.user_id
            or campaign_id != requested_campaign_id
            or action != "share_campaign_asset_with_growth"
        ):
            raise PermissionError("grant request scope denied")
        approved = grant_ledger.read_approved(
            organization_id=organization_id,
            owner_id=owner_id,
            project_id=project_id,
            asset_id=asset_id,
            campaign_id=campaign_id,
            now=now,
        )
        if approved is None:
            raise PermissionError("active, matching owner approval required")
        return approved

    event = read_studio_asset_for_growth(
        studio_store=studio_store,
        approval_reader=approval_reader,
        project_id=project_id,
        asset_id=asset_id,
        campaign_id=campaign_id,
        organization_id=owner.organization_id,
        authenticated_owner_id=owner.user_id,
        authenticated_studio_principal=studio_service_principal,
        occurred_at=now,
        enabled=True,
    )
    return preview_growth_campaign_from_studio(
        event, growth_profile, enabled=True,
    )
