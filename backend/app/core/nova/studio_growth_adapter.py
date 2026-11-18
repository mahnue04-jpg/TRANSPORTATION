"""Default-off Nova Creative Studio -> Growth asset metadata contract, v0.1.

Side-effect-free staging boundary. NOT a service connection or production adapter.
Only fictional asset identifiers; no video bytes, URLs, customer data or transports.
"""
from __future__ import annotations

from datetime import datetime
import os
import re
from typing import Mapping

from .agent_events import Agent, AgentEvent, EventType, SCHEMA_VERSION

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REQUIRED = frozenset({
    "organization_id", "campaign_id", "asset_id", "project_id",
    "status", "asset_kind", "review_state",
})
_DENIED = frozenset({
    "customer_email", "customer_name", "phone", "asset_url", "download_url",
    "media_bytes", "script", "voice", "token", "api_key", "provider_key",
})


def staging_asset_event(
    raw: Mapping[str, object], *,
    organization_id: str,
    source_identity: str,
    occurred_at: datetime,
    enabled: bool | None = None,
) -> AgentEvent:
    """Create a synthetic, review-only event, never send or persist it.

    `source_identity` is a caller-verified identifier supplied by a future
    server-side authenticator; this function does NOT authenticate identities.
    """
    if enabled is None:
        enabled = os.getenv("NOVA_STUDIO_GROWTH_STAGING_ADAPTER_ENABLED") == "true"
    if enabled is not True or os.getenv("NOVA_STUDIO_GROWTH_LIVE_ENABLED") == "true":
        raise PermissionError("Studio-Growth adapter disabled or live route blocked")
    if not isinstance(raw, Mapping):
        raise ValueError("asset metadata mapping required")
    if set(raw) != _REQUIRED:
        raise ValueError("asset metadata must contain exactly approved keys")
    if any(key in raw for key in _DENIED):
        raise ValueError("customer or media data forbidden")
    if not isinstance(source_identity, str) or not _ID.fullmatch(source_identity):
        raise PermissionError("verified Studio source identity required")
    if raw["organization_id"] != organization_id or not _ID.fullmatch(organization_id):
        raise PermissionError("cross-tenant asset denied")
    for key in ("campaign_id", "asset_id", "project_id"):
        if not isinstance(raw[key], str) or not _ID.fullmatch(raw[key]):
            raise ValueError("invalid opaque " + key)
    if raw["status"] != "completed" or raw["review_state"] != "owner_approved":
        raise PermissionError("only owner-approved completed asset metadata allowed")
    if raw["asset_kind"] not in ("video", "image"):
        raise ValueError("unsupported asset type")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("timezone-aware creation time required")
    asset_id = str(raw["asset_id"])
    return AgentEvent(
        schema_version=SCHEMA_VERSION,
        event_id="studio-asset:" + asset_id,
        correlation_id=str(raw["campaign_id"]),
        organization_id=organization_id,
        source_agent=Agent.CREATIVE_STUDIO,
        target_agent=Agent.GROWTH,
        event_type=EventType.ASSET_READY,
        subject_kind="campaign",
        subject_id=str(raw["campaign_id"]),
        synthetic=True,
        occurred_at=occurred_at,
        idempotency_key="studio-asset:" + asset_id,
        payload_reference="synthetic:" + asset_id,
    )


def staged_studio_record_event(
    *,
    project: object,
    asset: object,
    owner_approval: Mapping[str, object],
    campaign_id: str,
    organization_id: str,
    authenticated_owner_id: str,
    authenticated_studio_principal: str,
    occurred_at: datetime,
    enabled: bool | None = None,
) -> AgentEvent:
    """Project trusted Studio model rows to a *synthetic* event; no I/O.

    The caller must independently authenticate the Studio service principal,
    load project/asset from a tenant/owner scoped store and read a persisted
    owner approval. No user-supplied raw JSON is authorization evidence.

    Actual Studio CreativeAsset uses status=GENERATED, not completed. A real
    owner-approval record is NOT currently part of that model, so a future
    staging wrapper must introduce/verify that record before calling here.
    """
    if (not authenticated_owner_id or not _ID.fullmatch(authenticated_owner_id)
            or not authenticated_studio_principal
            or not _ID.fullmatch(authenticated_studio_principal)):
        raise PermissionError("trusted owner and Studio service identities required")
    if (getattr(project, "owner_id", None) != authenticated_owner_id
            or getattr(asset, "owner_id", None) != authenticated_owner_id
            or getattr(asset, "project_id", None) != getattr(project, "id", None)):
        raise PermissionError("Studio asset and project ownership mismatch")
    if getattr(asset, "status", None) != "GENERATED":
        raise PermissionError("Studio asset must be generated")
    if getattr(asset, "kind", None) not in ("video", "image"):
        raise PermissionError("non-campaign Studio asset type")
    required_approval = {"organization_id", "project_id", "asset_id", "owner_id",
                         "approved", "action"}
    if not isinstance(owner_approval, Mapping) or set(owner_approval) != required_approval:
        raise PermissionError("trusted persisted approval evidence required")
    if (owner_approval["organization_id"] != organization_id
            or owner_approval["project_id"] != getattr(project, "id", None)
            or owner_approval["asset_id"] != getattr(asset, "id", None)
            or owner_approval["owner_id"] != authenticated_owner_id
            or owner_approval["approved"] is not True
            or owner_approval["action"] != "share_campaign_asset_with_growth"):
        raise PermissionError("owner approval does not cover this asset handoff")
    return staging_asset_event(
        {
            "organization_id": organization_id,
            "campaign_id": campaign_id,
            "asset_id": getattr(asset, "id", None),
            "project_id": getattr(project, "id", None),
            "status": "completed",
            "asset_kind": getattr(asset, "kind", None),
            "review_state": "owner_approved",
        },
        organization_id=organization_id,
        source_identity=authenticated_studio_principal,
        occurred_at=occurred_at,
        enabled=enabled,
    )


def read_studio_asset_for_growth(
    *,
    studio_store: object,
    approval_reader: object,
    project_id: str,
    asset_id: str,
    campaign_id: str,
    organization_id: str,
    authenticated_owner_id: str,
    authenticated_studio_principal: str,
    occurred_at: datetime,
    enabled: bool | None = None,
) -> AgentEvent:
    """Owner-scoped repository lookup, default-off, no outbound transport.

    studio_store is expected to be the trusted server-side CreativeStudioStore
    with get_project(project_id, owner_id) and list_assets(project_id, owner_id).
    approval_reader must be a *trusted server-side* callable returning a
    persisted approval for this exact tenant/owner/project/asset/action.
    No such persistent approval mechanism is wired in this PR. Missing
    approvals fail closed; this is not a route or service integration.
    """
    if enabled is None:
        enabled = os.getenv("NOVA_STUDIO_GROWTH_STAGING_ADAPTER_ENABLED") == "true"
    if enabled is not True or os.getenv("NOVA_STUDIO_GROWTH_LIVE_ENABLED") == "true":
        raise PermissionError("Studio-Growth adapter disabled")
    for label, value in (
        ("project_id", project_id), ("asset_id", asset_id),
        ("campaign_id", campaign_id), ("organization_id", organization_id),
        ("owner_id", authenticated_owner_id),
        ("studio_principal", authenticated_studio_principal),
    ):
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise PermissionError("invalid verified " + label)
    if not callable(approval_reader):
        raise PermissionError("trusted approval reader required")
    # Never inspect source media paths, project text or external URLs.
    project = studio_store.get_project(project_id, authenticated_owner_id)
    if project is None:
        raise PermissionError("no owner-scoped project")
    assets = studio_store.list_assets(project_id, authenticated_owner_id)
    matches = [item for item in assets if getattr(item, "id", None) == asset_id]
    if len(matches) != 1:
        raise PermissionError("asset missing or ambiguous")
    # Approval must come from the server-side reader, not client-supplied JSON.
    approval = approval_reader(
        organization_id=organization_id,
        owner_id=authenticated_owner_id,
        project_id=project_id,
        asset_id=asset_id,
        action="share_campaign_asset_with_growth",
    )
    return staged_studio_record_event(
        project=project,
        asset=matches[0],
        owner_approval=approval,
        campaign_id=campaign_id,
        organization_id=organization_id,
        authenticated_owner_id=authenticated_owner_id,
        authenticated_studio_principal=authenticated_studio_principal,
        occurred_at=occurred_at,
        enabled=True,
    )


def preview_growth_campaign_from_studio(
    event: AgentEvent,
    growth_profile: Mapping[str, object],
    *,
    enabled: bool | None = None,
) -> dict[str, object]:
    """Read-only synthetic Growth profile compatibility preview.

    Accepts the dict shape returned by GrowthAgentService.get_profile(org_id).
    Does not POST a lead, send a message, change a profile, publish an asset,
    or store a campaign. There is no current Growth campaign intake endpoint.
    A real integration requires a separately reviewed server-side API.
    """
    if enabled is None:
        enabled = os.getenv("NOVA_STUDIO_GROWTH_STAGING_ADAPTER_ENABLED") == "true"
    if enabled is not True or os.getenv("NOVA_STUDIO_GROWTH_LIVE_ENABLED") == "true":
        raise PermissionError("Growth campaign preview disabled")
    if (not isinstance(event, AgentEvent) or event.synthetic is not True
            or event.event_type != EventType.ASSET_READY
            or event.source_agent != Agent.CREATIVE_STUDIO
            or event.target_agent != Agent.GROWTH):
        raise PermissionError("approved fictional Studio handoff required")
    if not isinstance(growth_profile, Mapping):
        raise PermissionError("trusted Growth profile snapshot required")
    if (growth_profile.get("configured") is not True
            or growth_profile.get("organization_id") != event.organization_id
            or growth_profile.get("is_synthetic_demo") is not True
            or growth_profile.get("activated") is not False
            or growth_profile.get("agent_disabled") is not True):
        raise PermissionError("only inactive, disabled, fictional Growth profile allowed")
    # Crucially exclude all Growth profile contact fields, customer records,
    # provider credentials, website URLs, and raw Studio content.
    return {
        "mode": "synthetic_read_only_preview",
        "organization_id": event.organization_id,
        "campaign_id": event.correlation_id,
        "asset_reference": event.payload_reference,
        "target_agent": Agent.GROWTH.value,
        "growth_campaign_intake_connected": False,
        "lead_created": False,
        "publishing_enabled": False,
        "outbound_messages_enabled": False,
    }
