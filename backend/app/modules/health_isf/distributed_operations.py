"""Facade service for diaspora distributed operations snapshots."""

from __future__ import annotations

from typing import Any

from app.helpers import uuid4
from app.modules.health_isf.diaspora_network_engine import get_diaspora_network_engine
from app.modules.health_isf.regional_cluster_models import DistributedCoordinationSignal, RegionalTenantCluster


class DistributedOperationsService:
    @staticmethod
    def upsert_regional_cluster(
        *,
        organization_id: str,
        cluster_id: str,
        region_code: str,
        tenant_ids: list[str],
        provider_ids: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        engine = get_diaspora_network_engine()
        engine.upsert_cluster(
            RegionalTenantCluster(
                organization_id=organization_id,
                cluster_id=cluster_id,
                region_code=region_code,
                tenant_ids=tenant_ids,
                provider_ids=provider_ids,
                metadata=metadata or {},
            )
        )
        return engine.snapshot(organization_id)

    @staticmethod
    def append_coordination_signal(
        *,
        organization_id: str,
        signal_type: str,
        region_code: str,
        payload: dict[str, Any],
        signal_id: str | None = None,
    ) -> dict[str, Any]:
        engine = get_diaspora_network_engine()
        engine.append_signal(
            DistributedCoordinationSignal(
                organization_id=organization_id,
                signal_id=signal_id or str(uuid4()),
                signal_type=signal_type,
                region_code=region_code,
                payload=payload,
            )
        )
        return engine.snapshot(organization_id)

    @staticmethod
    def get_snapshot(*, organization_id: str) -> dict[str, Any]:
        return get_diaspora_network_engine().snapshot(organization_id)
