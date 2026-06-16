"""Service wrapper for geospatial map state with websocket-friendly payloads."""

from __future__ import annotations

from typing import Any

from app.modules.health_isf.geo_models import DriverPosition, GeoPoint, IncidentGeoSignal, ProviderZone
from app.modules.health_isf.geospatial_engine import get_geospatial_engine


class OperationalMapService:
    @staticmethod
    def update_provider_zone(
        *,
        organization_id: str,
        provider_id: str,
        center_lat: float,
        center_lng: float,
        radius_km: float,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        engine = get_geospatial_engine()
        engine.upsert_provider_zone(
            ProviderZone(
                provider_id=provider_id,
                organization_id=organization_id,
                center=GeoPoint(lat=center_lat, lng=center_lng),
                radius_km=radius_km,
                metadata=metadata or {},
            )
        )
        return engine.build_map_state(organization_id)

    @staticmethod
    def update_driver_position(
        *,
        organization_id: str,
        driver_id: str,
        lat: float,
        lng: float,
        heading: float | None = None,
        speed_kph: float | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        engine = get_geospatial_engine()
        engine.upsert_driver_position(
            DriverPosition(
                driver_id=driver_id,
                organization_id=organization_id,
                location=GeoPoint(lat=lat, lng=lng),
                heading=heading,
                speed_kph=speed_kph,
                status=status,
            )
        )
        return engine.build_map_state(organization_id)

    @staticmethod
    def update_incident_signal(
        *,
        organization_id: str,
        incident_id: str,
        lat: float,
        lng: float,
        severity: str,
        category: str,
    ) -> dict[str, Any]:
        engine = get_geospatial_engine()
        engine.upsert_incident_signal(
            IncidentGeoSignal(
                incident_id=incident_id,
                organization_id=organization_id,
                location=GeoPoint(lat=lat, lng=lng),
                severity=severity,
                category=category,
            )
        )
        return engine.build_map_state(organization_id)

    @staticmethod
    def get_map_state(*, organization_id: str) -> dict[str, Any]:
        return get_geospatial_engine().build_map_state(organization_id)

    @staticmethod
    def replay(*, organization_id: str, cursor: int) -> dict[str, Any]:
        return get_geospatial_engine().replay_state(organization_id, cursor)
