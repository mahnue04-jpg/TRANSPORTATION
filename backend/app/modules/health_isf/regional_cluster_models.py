"""Regional cluster models for diaspora distributed network coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RegionalTenantCluster:
    organization_id: str
    cluster_id: str
    region_code: str
    tenant_ids: list[str]
    provider_ids: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DistributedCoordinationSignal:
    organization_id: str
    signal_id: str
    signal_type: str
    region_code: str
    payload: dict[str, Any]
