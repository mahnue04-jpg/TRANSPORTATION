"""Distributed diaspora network engine for regional clustering and coordination."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from threading import RLock
from typing import Any

from app.modules.health_isf.regional_cluster_models import DistributedCoordinationSignal, RegionalTenantCluster


class DiasporaNetworkEngine:
    def __init__(self) -> None:
        self._lock = RLock()
        self._clusters: dict[str, dict[str, RegionalTenantCluster]] = defaultdict(dict)
        self._signals: dict[str, list[DistributedCoordinationSignal]] = defaultdict(list)

    def upsert_cluster(self, cluster: RegionalTenantCluster) -> RegionalTenantCluster:
        with self._lock:
            self._clusters[cluster.organization_id][cluster.cluster_id] = cluster
            return cluster

    def append_signal(self, signal: DistributedCoordinationSignal) -> DistributedCoordinationSignal:
        with self._lock:
            self._signals[signal.organization_id].append(signal)
            return signal

    def snapshot(self, organization_id: str) -> dict[str, Any]:
        with self._lock:
            clusters = list(self._clusters.get(organization_id, {}).values())
            signals = list(self._signals.get(organization_id, []))[-500:]

        grouped_by_region: dict[str, int] = defaultdict(int)
        for cluster in clusters:
            grouped_by_region[cluster.region_code] += len(cluster.tenant_ids)

        return {
            "organization_id": organization_id,
            "regional_tenant_clustering": [
                {
                    "cluster_id": cluster.cluster_id,
                    "region_code": cluster.region_code,
                    "tenant_count": len(cluster.tenant_ids),
                    "provider_count": len(cluster.provider_ids),
                    "metadata": cluster.metadata,
                }
                for cluster in clusters
            ],
            "community_operational_routing": {
                "region_distribution": dict(grouped_by_region),
                "active_coordination_signals": len(signals),
            },
            "provider_ecosystem_grouping": [
                {
                    "cluster_id": cluster.cluster_id,
                    "provider_ids": cluster.provider_ids,
                }
                for cluster in clusters
            ],
            "distributed_operational_coordination": [
                {
                    "signal_id": signal.signal_id,
                    "signal_type": signal.signal_type,
                    "region_code": signal.region_code,
                    "payload": signal.payload,
                }
                for signal in signals[-100:]
            ],
            "cross_region_operational_awareness": {
                "regions": sorted(grouped_by_region.keys()),
                "cross_region_ready": len(grouped_by_region.keys()) > 1,
            },
            "generated_at": datetime.utcnow().isoformat(),
            "tenant_isolated": True,
            "governed": True,
        }


_engine = DiasporaNetworkEngine()


def get_diaspora_network_engine() -> DiasporaNetworkEngine:
    return _engine
