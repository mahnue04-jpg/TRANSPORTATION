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
