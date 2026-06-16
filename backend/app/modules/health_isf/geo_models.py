"""Geospatial models for operational map state and overlays."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class GeoPoint:
    lat: float
    lng: float


@dataclass(slots=True)
class ProviderZone:
    provider_id: str
    organization_id: str
    center: GeoPoint
    radius_km: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DriverPosition:
    driver_id: str
    organization_id: str
    location: GeoPoint
    heading: float | None = None
    speed_kph: float | None = None
    status: str | None = None


@dataclass(slots=True)
class IncidentGeoSignal:
    incident_id: str
    organization_id: str
    location: GeoPoint
    severity: str
    category: str


@dataclass(slots=True)
class DensityRegion:
    organization_id: str
    region_id: str
    center: GeoPoint
    signal_count: int
    intensity: float
