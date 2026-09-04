"""Isolated Driver Mobile routing sidecar.

Nominatim geocoding + public OSRM road routes, with haversine fallback.
Never writes ride.estimated_distance_miles or ride.estimated_duration_minutes.
Never transitions ride/assignment state, billing, payout, or driver reset.
HTTP is disabled under pytest unless AMICOR_ROUTING_HTTP=1.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.models import (
    HealthISFDriverLocationPing,
    HealthISFGeocodeCache,
    HealthISFRide,
    HealthISFRideRoutePlan,
)
from app.modules.health_isf.ride_execution_engine import RideLifecycleManager

logger = logging.getLogger("amicor.health_isf.driver_mobile_routing")

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
PHOTON_SEARCH_URL = "https://photon.komoot.io/api/"
OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
USER_AGENT = "AMICOR-HealthISF/1.0 (driver-mobile-routing; https://github.com/mahnue04-jpg/TRANSPORTATION)"
HTTP_TIMEOUT_SECONDS = 4.0
GEOCODE_TIMEOUT_SECONDS = 4.0
NOMINATIM_MIN_INTERVAL_SECONDS = 1.1
HAVERSINE_MPH = 27.0
EARTH_RADIUS_MILES = 3958.8
HOUSE_LEVEL_QUALITY = 3
ROAD_LEVEL_QUALITY = 1

LEG_DRIVER_TO_PICKUP = "driver_to_pickup"
LEG_PICKUP_TO_DESTINATION = "pickup_to_destination"

REASON_NOMINATIM_UNAVAILABLE = "nominatim_unavailable"
REASON_INVALID_ADDRESS = "invalid_address"
REASON_OSRM_UNAVAILABLE = "osrm_unavailable"
REASON_DRIVER_GPS_UNAVAILABLE = "driver_gps_unavailable"
REASON_DURATION_UNAVAILABLE = "duration_unavailable"
REASON_CLEARED = "cleared"

_last_nominatim_monotonic = 0.0


class RoutingHttpDisabled(RuntimeError):
    """Raised when outbound routing HTTP is disabled (tests by default)."""


def _http_disabled() -> bool:
    flag = str(os.environ.get("AMICOR_ROUTING_HTTP") or "").strip().lower()
    if flag in {"1", "true", "on", "yes"}:
        return False
    if flag in {"0", "false", "off", "no"}:
        return True
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        from datetime import timezone

        return value.replace(tzinfo=timezone.utc)
    return value


def normalize_address_key(address: str) -> str:
    return " ".join(str(address or "").strip().lower().split())


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + (
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return EARTH_RADIUS_MILES * 2 * math.asin(min(1.0, math.sqrt(a)))


def haversine_route(origin: dict[str, float], destination: dict[str, float]) -> dict[str, Any]:
    miles = max(
        0.1,
        haversine_miles(
            float(origin["latitude"]),
            float(origin["longitude"]),
            float(destination["latitude"]),
            float(destination["longitude"]),
        ),
    )
    duration = max(1, int(round((miles / HAVERSINE_MPH) * 60.0)))
    return {
        "distance_miles": round(miles, 2),
        "duration_minutes": duration,
        "points": [
            [float(origin["latitude"]), float(origin["longitude"])],
            [float(destination["latitude"]), float(destination["longitude"])],
        ],
        "provider": "haversine",
    }


def _timeout_for_url(url: str) -> float:
    lowered = str(url or "").lower()
    if (
        "nominatim.openstreetmap.org" in lowered
        or "geocoding.geo.census.gov" in lowered
        or "photon.komoot.io" in lowered
    ):
        return GEOCODE_TIMEOUT_SECONDS
    return HTTP_TIMEOUT_SECONDS


def _fetch_json(url: str) -> Any:
    if _http_disabled():
        raise RoutingHttpDisabled(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=_timeout_for_url(url)) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _throttle_nominatim() -> None:
    global _last_nominatim_monotonic
    elapsed = time.monotonic() - _last_nominatim_monotonic
    if elapsed < NOMINATIM_MIN_INTERVAL_SECONDS:
        time.sleep(NOMINATIM_MIN_INTERVAL_SECONDS - elapsed)
    _last_nominatim_monotonic = time.monotonic()


def _address_query_variants(address: str) -> list[str]:
    raw = " ".join(str(address or "").split())
    if not raw:
        return []
    variants = [raw]
    street, sep, remainder = raw.partition(",")
    expansions = (
        (r"\bN\b", "North"),
        (r"\bS\b", "South"),
        (r"\bE\b", "East"),
        (r"\bW\b", "West"),
        (r"\bAve\b", "Avenue"),
        (r"\bSt\b", "Street"),
        (r"\bDr\b", "Drive"),
        (r"\bRd\b", "Road"),
        (r"\bBlvd\b", "Boulevard"),
        (r"\bLn\b", "Lane"),
        (r"\bCt\b", "Court"),
    )
    expanded_street = street
    for pattern, replacement in expansions:
        expanded_street = re.sub(pattern, replacement, expanded_street)
    expanded = expanded_street + (sep + remainder if sep else "")
    if expanded not in variants:
        variants.append(expanded)
    if "united states" not in raw.lower() and ", usa" not in raw.lower():
        variants.append(f"{raw}, United States")
    return variants


def _nominatim_quality(row: dict[str, Any]) -> int:
    addresstype = str(row.get("addresstype") or "").strip().lower()
    osm_class = str(row.get("class") or "").strip().lower()
    osm_type = str(row.get("type") or "").strip().lower()
    if addresstype in {"house", "building"} or osm_type in {"house", "residential", "apartments", "yes"}:
        return HOUSE_LEVEL_QUALITY
    if osm_class in {"building", "place"} and osm_type not in {"city", "town", "state", "county"}:
        return 2
    if addresstype in {"road", "street"} or osm_class == "highway":
        return ROAD_LEVEL_QUALITY
    return ROAD_LEVEL_QUALITY


def _result_from_coords(
    *,
    latitude: float,
    longitude: float,
    display_name: str | None,
    provider: str,
    quality: int,
) -> dict[str, Any]:
    return {
        "latitude": latitude,
        "longitude": longitude,
        "display_name": (display_name or "")[:512] or None,
        "provider": provider,
        "quality": quality,
    }


def _pick_nominatim_row(rows: Any) -> dict[str, Any] | None:
    if not isinstance(rows, list):
        return None
    best: dict[str, Any] | None = None
    best_score = -1
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            latitude = float(row.get("lat"))
            longitude = float(row.get("lon"))
        except (TypeError, ValueError):
            continue
        score = _nominatim_quality(row)
        if score > best_score:
            best_score = score
            best = _result_from_coords(
                latitude=latitude,
                longitude=longitude,
                display_name=str(row.get("display_name") or ""),
                provider="nominatim",
                quality=score,
            )
        if score >= HOUSE_LEVEL_QUALITY:
            return best
    return best


def _geocode_via_nominatim(address: str) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for query_address in _address_query_variants(address):
        _throttle_nominatim()
        query = urllib.parse.urlencode(
            {
                "q": query_address,
                "format": "json",
                "limit": "5",
                "countrycodes": "us",
                "addressdetails": "1",
            }
        )
        rows = _fetch_json(f"{NOMINATIM_SEARCH_URL}?{query}")
        picked = _pick_nominatim_row(rows)
        if picked is None:
            continue
        if best is None or int(picked.get("quality") or 0) > int(best.get("quality") or 0):
            best = picked
        if int(picked.get("quality") or 0) >= HOUSE_LEVEL_QUALITY:
            return picked
    return best


def _geocode_via_census(address: str) -> dict[str, Any] | None:
    try:
        for query_address in _address_query_variants(address):
            query = urllib.parse.urlencode(
                {
                    "address": query_address,
                    "benchmark": "Public_AR_Current",
                    "format": "json",
                }
            )
            payload = _fetch_json(f"{CENSUS_GEOCODER_URL}?{query}")
            matches = ((payload or {}).get("result") or {}).get("addressMatches") or []
            if not matches or not isinstance(matches[0], dict):
                continue
            coords = matches[0].get("coordinates") or {}
            try:
                latitude = float(coords.get("y"))
                longitude = float(coords.get("x"))
            except (TypeError, ValueError):
                continue
            return _result_from_coords(
                latitude=latitude,
                longitude=longitude,
                display_name=str(matches[0].get("matchedAddress") or query_address),
                provider="census",
                quality=HOUSE_LEVEL_QUALITY,
            )
    except RoutingHttpDisabled:
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    return None


def _street_tokens(value: str) -> set[str]:
    ignore = {
        "n",
        "s",
        "e",
        "w",
        "north",
        "south",
        "east",
        "west",
        "ave",
        "avenue",
        "st",
        "street",
        "dr",
        "drive",
        "rd",
        "road",
        "mn",
        "minnesota",
        "usa",
        "united",
        "states",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if token not in ignore and not token.isdigit()
    }


def _geocode_via_photon(address: str) -> dict[str, Any] | None:
    house_match = re.match(r"\s*(\d+[A-Za-z]?)", str(address or ""))
    house_number = house_match.group(1) if house_match else ""
    wanted_tokens = _street_tokens(address)
    query = urllib.parse.urlencode({"q": address, "limit": "5", "lang": "en"})
    payload = _fetch_json(f"{PHOTON_SEARCH_URL}?{query}")
    features = (payload or {}).get("features") or []
    fallback: dict[str, Any] | None = None
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        coords = ((feature.get("geometry") or {}).get("coordinates") or [])
        if len(coords) < 2:
            continue
        try:
            longitude = float(coords[0])
            latitude = float(coords[1])
        except (TypeError, ValueError):
            continue
        country = str(props.get("countrycode") or props.get("country") or "").upper()
        if country and country not in {"US", "USA", "UNITED STATES"}:
            continue
        display = ", ".join(
            part
            for part in [
                " ".join(
                    piece
                    for piece in [str(props.get("housenumber") or ""), str(props.get("street") or props.get("name") or "")]
                    if piece
                ).strip(),
                str(props.get("city") or ""),
                str(props.get("state") or ""),
            ]
            if part
        )
        result = _result_from_coords(
            latitude=latitude,
            longitude=longitude,
            display_name=display or str(address),
            provider="photon",
            quality=HOUSE_LEVEL_QUALITY if str(props.get("housenumber") or "") == house_number else ROAD_LEVEL_QUALITY,
        )
        street_value = " ".join(
            part for part in [str(props.get("street") or ""), str(props.get("name") or "")] if part
        )
        if house_number and str(props.get("housenumber") or "") == house_number:
            if not wanted_tokens or wanted_tokens.intersection(_street_tokens(street_value)):
                return result
        if fallback is None:
            fallback = result
    return fallback


def _persist_geocode(
    db: Session,
    *,
    address: str,
    key: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    cache_row = HealthISFGeocodeCache(
        id=uuid4(),
        address_key=key,
        query_address=str(address)[:512],
        latitude=float(result["latitude"]),
        longitude=float(result["longitude"]),
        display_name=str(result.get("display_name") or "")[:512] or None,
        provider=str(result.get("provider") or "nominatim")[:32],
        created_at=now(),
        updated_at=now(),
    )
    db.add(cache_row)
    db.commit()
    return {
        "latitude": float(cache_row.latitude),
        "longitude": float(cache_row.longitude),
        "display_name": cache_row.display_name,
        "provider": str(cache_row.provider or "nominatim"),
        "cached": False,
    }


def geocode_address(db: Session, address: str) -> Optional[dict[str, Any]]:
    key = normalize_address_key(address)
    if not key:
        return None
    cached = (
        db.query(HealthISFGeocodeCache)
        .filter(HealthISFGeocodeCache.address_key == key)
        .first()
    )
    if cached:
        return {
            "latitude": float(cached.latitude),
            "longitude": float(cached.longitude),
            "display_name": cached.display_name,
            "provider": str(cached.provider or "nominatim"),
            "cached": True,
        }

    nominatim_result: dict[str, Any] | None = None
    transport_error = False
    try:
        nominatim_result = _geocode_via_nominatim(address)
    except RoutingHttpDisabled:
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        transport_error = True
        logger.warning("nominatim_unavailable address=%s error=%s", key[:80], exc)
    except Exception as exc:
        transport_error = True
        logger.warning("nominatim_failed address=%s error=%s", key[:80], exc)

    if nominatim_result and int(nominatim_result.get("quality") or 0) >= HOUSE_LEVEL_QUALITY:
        return _persist_geocode(db, address=address, key=key, result=nominatim_result)

    census_result: dict[str, Any] | None = None
    try:
        census_result = _geocode_via_census(address)
    except RoutingHttpDisabled:
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, Exception) as exc:
        logger.warning("census_geocode_unavailable address=%s error=%s", key[:80], exc)

    if census_result:
        return _persist_geocode(db, address=address, key=key, result=census_result)
    if nominatim_result:
        return _persist_geocode(db, address=address, key=key, result=nominatim_result)

    photon_result: dict[str, Any] | None = None
    try:
        photon_result = _geocode_via_photon(address)
    except RoutingHttpDisabled:
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, Exception) as exc:
        logger.warning("photon_geocode_unavailable address=%s error=%s", key[:80], exc)

    if photon_result:
        return _persist_geocode(db, address=address, key=key, result=photon_result)
    return {"error": REASON_NOMINATIM_UNAVAILABLE if transport_error else REASON_INVALID_ADDRESS}


def route_between(origin: dict[str, float], destination: dict[str, float]) -> dict[str, Any]:
    fallback = haversine_route(origin, destination)
    url = OSRM_ROUTE_URL.format(
        lon1=float(origin["longitude"]),
        lat1=float(origin["latitude"]),
        lon2=float(destination["longitude"]),
        lat2=float(destination["latitude"]),
    ) + "?overview=full&geometries=geojson"
    try:
        payload = _fetch_json(url)
    except RoutingHttpDisabled:
        fallback["provider"] = "haversine"
        fallback["osrm_error"] = REASON_OSRM_UNAVAILABLE
        return fallback
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("osrm_unavailable error=%s", exc)
        fallback["osrm_error"] = REASON_OSRM_UNAVAILABLE
        return fallback
    except Exception as exc:
        logger.warning("osrm_failed error=%s", exc)
        fallback["osrm_error"] = REASON_OSRM_UNAVAILABLE
        return fallback

    routes = payload.get("routes") if isinstance(payload, dict) else None
    if not routes:
        fallback["osrm_error"] = REASON_OSRM_UNAVAILABLE
        return fallback
    route = routes[0]
    geometry = (route.get("geometry") or {}).get("coordinates") or []
    points: list[list[float]] = []
    for pair in geometry:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        points.append([float(pair[1]), float(pair[0])])
    if len(points) < 2:
        points = fallback["points"]
    meters = float(route.get("distance") or 0.0)
    seconds = float(route.get("duration") or 0.0)
    miles = max(0.1, meters / 1609.344) if meters > 0 else fallback["distance_miles"]
    duration = max(1, int(round(seconds / 60.0))) if seconds > 0 else fallback["duration_minutes"]
    return {
        "distance_miles": round(miles, 2),
        "duration_minutes": duration,
        "points": points,
        "provider": "osrm",
    }


def latest_driver_gps(
    db: Session,
    *,
    driver_id: str,
    ride_id: str | None = None,
) -> Optional[dict[str, float]]:
    query = db.query(HealthISFDriverLocationPing).filter(
        HealthISFDriverLocationPing.driver_id == driver_id
    )
    if ride_id:
        ride_ping = (
            query.filter(HealthISFDriverLocationPing.ride_id == ride_id)
            .order_by(HealthISFDriverLocationPing.created_at.desc())
            .first()
        )
        if ride_ping:
            return {"latitude": float(ride_ping.latitude), "longitude": float(ride_ping.longitude)}
    ping = query.order_by(HealthISFDriverLocationPing.created_at.desc()).first()
    if not ping:
        return None
    return {"latitude": float(ping.latitude), "longitude": float(ping.longitude)}


def _parse_payload(route: HealthISFRideRoutePlan | None) -> dict[str, Any]:
    if route is None or not route.path_points_json:
        return {}
    try:
        payload = json.loads(route.path_points_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if isinstance(payload, list):
        return {"type": "driver_mobile_route", "points": payload}
    if isinstance(payload, dict):
        return payload
    return {}


def _decode_computed_at(raw: Any) -> datetime | None:
    if not raw:
        return None
    text = str(raw)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _remaining_minutes(duration_minutes: int | None, computed_at: datetime | None) -> Optional[int]:
    if duration_minutes is None or int(duration_minutes) <= 0:
        return None
    if computed_at is None:
        return int(duration_minutes)
    elapsed = max(0, int(((_as_utc(now()) - computed_at).total_seconds()) / 60))
    return max(1, int(duration_minutes) - elapsed)


def _empty_snapshot(*, reason: str | None = None, ride: HealthISFRide | None = None) -> dict[str, Any]:
    return {
        "eta_minutes": None,
        "pickup_eta_minutes": None,
        "destination_eta_minutes": None,
        "route_leg": None,
        "route_polyline": [],
        "pickup_latitude": None,
        "pickup_longitude": None,
        "dropoff_latitude": None,
        "dropoff_longitude": None,
        "driver_latitude": None,
        "driver_longitude": None,
        "driver_gps_available": False,
        "eta_unavailable_reason": reason,
        "routing_provider": None,
        "geocode_provider": None,
        "ride_id": str(ride.id) if ride is not None else None,
        "trip_leg": str(getattr(ride, "trip_leg", None) or "") or None,
        "round_trip_group_id": str(getattr(ride, "round_trip_group_id", None) or "") or None,
    }


def _coord(payload: dict[str, Any], key: str) -> Optional[dict[str, float]]:
    row = payload.get(key)
    if not isinstance(row, dict):
        return None
    try:
        return {"latitude": float(row["latitude"]), "longitude": float(row["longitude"])}
    except (KeyError, TypeError, ValueError):
        return None


def routing_snapshot_for_ride(
    db: Session,
    *,
    ride: HealthISFRide | None,
    driver_id: str | None = None,
) -> dict[str, Any]:
    if ride is None:
        return _empty_snapshot()
    route = (
        db.query(HealthISFRideRoutePlan)
        .filter(HealthISFRideRoutePlan.ride_id == str(ride.id))
        .first()
    )
    payload = _parse_payload(route)
    if route is None or route.cleared_at is not None or payload.get("cleared"):
        return _empty_snapshot(reason=REASON_CLEARED if route and route.cleared_at else None, ride=ride)

    pickup = _coord(payload, "pickup")
    dropoff = _coord(payload, "dropoff")
    driver = _coord(payload, "driver")
    gps = None
    if driver_id:
        gps = latest_driver_gps(db, driver_id=str(driver_id), ride_id=str(ride.id))
    if gps:
        driver = gps

    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    leg = str(payload.get("leg") or route.route_leg or "") or None
    pickup_eta = payload.get("pickup_eta_minutes")
    destination_eta = payload.get("destination_eta_minutes")
    duration = payload.get("duration_minutes")
    if duration is not None:
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = None
    computed_at = _decode_computed_at(payload.get("computed_at"))
    remaining = _remaining_minutes(duration if isinstance(duration, int) else None, computed_at)

    arrived_pickup_states = {"arrived", "arrived_pickup", "waiting_at_pickup"}
    onboard_states = {"rider_onboard", "rider_loaded", "in_progress", "trip_in_progress", "in_transit"}
    arrived_dest_states = {"arrived_destination"}

    if lifecycle in arrived_dest_states:
        destination_eta = 0
        pickup_eta = None
        leg = LEG_PICKUP_TO_DESTINATION
    elif lifecycle in onboard_states:
        pickup_eta = None
        if remaining is not None:
            destination_eta = remaining
        leg = LEG_PICKUP_TO_DESTINATION
    elif lifecycle in arrived_pickup_states:
        pickup_eta = 0
        destination_eta = None
        leg = LEG_DRIVER_TO_PICKUP
    else:
        destination_eta = None
        if remaining is not None and driver:
            pickup_eta = remaining
        elif not driver:
            pickup_eta = None
        leg = LEG_DRIVER_TO_PICKUP

    reason = payload.get("eta_unavailable_reason")
    if leg == LEG_DRIVER_TO_PICKUP and pickup_eta is None:
        reason = reason or (REASON_DRIVER_GPS_UNAVAILABLE if not driver else REASON_DURATION_UNAVAILABLE)
    elif leg == LEG_PICKUP_TO_DESTINATION and destination_eta is None:
        reason = reason or REASON_DURATION_UNAVAILABLE
    else:
        reason = None

    eta_minutes = pickup_eta if leg == LEG_DRIVER_TO_PICKUP else destination_eta
    polyline = payload.get("points") if isinstance(payload.get("points"), list) else []
    return {
        "eta_minutes": eta_minutes,
        "pickup_eta_minutes": pickup_eta,
        "destination_eta_minutes": destination_eta,
        "route_leg": leg,
        "route_polyline": polyline,
        "pickup_latitude": pickup["latitude"] if pickup else None,
        "pickup_longitude": pickup["longitude"] if pickup else None,
        "dropoff_latitude": dropoff["latitude"] if dropoff else None,
        "dropoff_longitude": dropoff["longitude"] if dropoff else None,
        "driver_latitude": driver["latitude"] if driver else None,
        "driver_longitude": driver["longitude"] if driver else None,
        "driver_gps_available": bool(driver),
        "eta_unavailable_reason": reason,
        "routing_provider": payload.get("routing_provider") or route.map_provider,
        "geocode_provider": payload.get("geocode_provider"),
        "ride_id": str(ride.id),
        "trip_leg": str(getattr(ride, "trip_leg", None) or "") or None,
        "round_trip_group_id": str(getattr(ride, "round_trip_group_id", None) or "") or None,
    }


def _persist_plan(
    db: Session,
    *,
    ride: HealthISFRide,
    pickup: dict[str, float] | None,
    dropoff: dict[str, float] | None,
    driver: dict[str, float] | None,
    points: list[list[float]],
    distance_miles: float | None,
    duration_minutes: int | None,
    leg: str,
    pickup_eta_minutes: int | None,
    destination_eta_minutes: int | None,
    routing_provider: str,
    geocode_provider: str | None,
    eta_unavailable_reason: str | None,
) -> HealthISFRideRoutePlan | None:
    if pickup is None:
        return None
    dest = dropoff or pickup
    payload = {
        "type": "driver_mobile_route",
        "leg": leg,
        "points": points,
        "pickup": pickup,
        "dropoff": dropoff,
        "driver": driver,
        "geocode_provider": geocode_provider,
        "routing_provider": routing_provider,
        "pickup_eta_minutes": pickup_eta_minutes,
        "destination_eta_minutes": destination_eta_minutes,
        "duration_minutes": duration_minutes,
        "distance_miles": distance_miles,
        "eta_unavailable_reason": eta_unavailable_reason,
        "computed_at": now().isoformat(),
        "cleared": False,
        "ride_id": str(ride.id),
        "trip_leg": str(getattr(ride, "trip_leg", None) or "") or None,
        "round_trip_group_id": str(getattr(ride, "round_trip_group_id", None) or "") or None,
    }
    route = (
        db.query(HealthISFRideRoutePlan)
        .filter(HealthISFRideRoutePlan.ride_id == str(ride.id))
        .first()
    )
    distance_value = float(distance_miles if distance_miles is not None else 0.1)
    duration_value = int(duration_minutes if duration_minutes and duration_minutes > 0 else 1)
    if route is None:
        route = HealthISFRideRoutePlan(
            id=uuid4(),
            organization_id=str(ride.organization_id),
            ride_id=str(ride.id),
            map_provider=routing_provider[:32],
            route_reference=f"dmr_{uuid4().replace('-', '')[:16]}",
            origin_latitude=float(pickup["latitude"]),
            origin_longitude=float(pickup["longitude"]),
            destination_latitude=float(dest["latitude"]),
            destination_longitude=float(dest["longitude"]),
            estimated_distance_miles=distance_value,
            estimated_duration_minutes=duration_value,
            traffic_multiplier=1.0,
            path_points_json=json.dumps(payload),
            route_leg=leg,
            remaining_eta_minutes=pickup_eta_minutes if leg == LEG_DRIVER_TO_PICKUP else destination_eta_minutes,
            eta_unavailable_reason=eta_unavailable_reason,
            cleared_at=None,
            created_at=now(),
            updated_at=now(),
        )
        db.add(route)
    else:
        route.map_provider = routing_provider[:32]
        route.origin_latitude = float(pickup["latitude"])
        route.origin_longitude = float(pickup["longitude"])
        route.destination_latitude = float(dest["latitude"])
        route.destination_longitude = float(dest["longitude"])
        route.estimated_distance_miles = distance_value
        route.estimated_duration_minutes = duration_value
        route.path_points_json = json.dumps(payload)
        route.route_leg = leg
        route.remaining_eta_minutes = pickup_eta_minutes if leg == LEG_DRIVER_TO_PICKUP else destination_eta_minutes
        route.eta_unavailable_reason = eta_unavailable_reason
        route.cleared_at = None
        route.updated_at = now()
    db.commit()
    db.refresh(route)
    return route


def clear_active_route(db: Session, *, ride_id: str) -> None:
    """Clear routing for one ride only. Does not touch sibling round-trip rides."""
    route = (
        db.query(HealthISFRideRoutePlan)
        .filter(HealthISFRideRoutePlan.ride_id == str(ride_id))
        .first()
    )
    if route is None:
        return
    payload = _parse_payload(route)
    payload["cleared"] = True
    payload["pickup_eta_minutes"] = None
    payload["destination_eta_minutes"] = None
    payload["points"] = []
    payload["driver"] = None
    payload["eta_unavailable_reason"] = REASON_CLEARED
    payload["computed_at"] = now().isoformat()
    route.path_points_json = json.dumps(payload)
    route.remaining_eta_minutes = None
    route.eta_unavailable_reason = REASON_CLEARED
    route.cleared_at = now()
    route.updated_at = now()
    db.commit()


def _geocode_pair(db: Session, ride: HealthISFRide) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None, str | None]:
    pickup_result = geocode_address(db, str(ride.pickup_address or ""))
    dropoff_result = geocode_address(db, str(ride.dropoff_address or ""))
    geocode_provider = None
    reason = None

    def _ok(row: dict[str, Any] | None) -> dict[str, float] | None:
        nonlocal geocode_provider, reason
        if not row:
            return None
        if row.get("error"):
            reason = str(row["error"])
            return None
        geocode_provider = str(row.get("provider") or "nominatim")
        return {"latitude": float(row["latitude"]), "longitude": float(row["longitude"])}

    return _ok(pickup_result), _ok(dropoff_result), geocode_provider, reason


def apply_lifecycle_routing(
    db: Session,
    *,
    ride_id: str,
    driver_id: str | None,
    event: str,
) -> dict[str, Any]:
    ride = db.query(HealthISFRide).filter(HealthISFRide.id == str(ride_id)).first()
    if ride is None:
        return _empty_snapshot(reason="ride_not_found")

    if event == "completed":
        clear_active_route(db, ride_id=str(ride.id))
        return _empty_snapshot(reason=REASON_CLEARED, ride=ride)

    pickup, dropoff, geocode_provider, geocode_reason = _geocode_pair(db, ride)
    gps = latest_driver_gps(db, driver_id=str(driver_id), ride_id=str(ride.id)) if driver_id else None

    if pickup is None:
        return _empty_snapshot(reason=geocode_reason or REASON_INVALID_ADDRESS, ride=ride)

    if event in {"accepted", "en_route_pickup"}:
        if gps is None:
            _persist_plan(
                db,
                ride=ride,
                pickup=pickup,
                dropoff=dropoff,
                driver=None,
                points=[],
                distance_miles=None,
                duration_minutes=None,
                leg=LEG_DRIVER_TO_PICKUP,
                pickup_eta_minutes=None,
                destination_eta_minutes=None,
                routing_provider="none",
                geocode_provider=geocode_provider,
                eta_unavailable_reason=REASON_DRIVER_GPS_UNAVAILABLE,
            )
            return routing_snapshot_for_ride(db, ride=ride, driver_id=driver_id)
        routed = route_between(gps, pickup)
        _persist_plan(
            db,
            ride=ride,
            pickup=pickup,
            dropoff=dropoff,
            driver=gps,
            points=list(routed.get("points") or []),
            distance_miles=routed.get("distance_miles"),
            duration_minutes=routed.get("duration_minutes"),
            leg=LEG_DRIVER_TO_PICKUP,
            pickup_eta_minutes=routed.get("duration_minutes"),
            destination_eta_minutes=None,
            routing_provider=str(routed.get("provider") or "haversine"),
            geocode_provider=geocode_provider,
            eta_unavailable_reason=None,
        )
        return routing_snapshot_for_ride(db, ride=ride, driver_id=driver_id)

    if event == "arrived_pickup":
        existing = _parse_payload(
            db.query(HealthISFRideRoutePlan).filter(HealthISFRideRoutePlan.ride_id == str(ride.id)).first()
        )
        points = existing.get("points") if isinstance(existing.get("points"), list) else []
        _persist_plan(
            db,
            ride=ride,
            pickup=pickup,
            dropoff=dropoff,
            driver=gps or _coord(existing, "driver"),
            points=points,
            distance_miles=existing.get("distance_miles"),
            duration_minutes=0,
            leg=LEG_DRIVER_TO_PICKUP,
            pickup_eta_minutes=0,
            destination_eta_minutes=None,
            routing_provider=str(existing.get("routing_provider") or "none"),
            geocode_provider=geocode_provider or existing.get("geocode_provider"),
            eta_unavailable_reason=None,
        )
        return routing_snapshot_for_ride(db, ride=ride, driver_id=driver_id)

    if event in {"rider_loaded", "trip_in_progress"}:
        if dropoff is None:
            _persist_plan(
                db,
                ride=ride,
                pickup=pickup,
                dropoff=None,
                driver=gps,
                points=[],
                distance_miles=None,
                duration_minutes=None,
                leg=LEG_PICKUP_TO_DESTINATION,
                pickup_eta_minutes=None,
                destination_eta_minutes=None,
                routing_provider="none",
                geocode_provider=geocode_provider,
                eta_unavailable_reason=geocode_reason or REASON_INVALID_ADDRESS,
            )
            return routing_snapshot_for_ride(db, ride=ride, driver_id=driver_id)
        origin = gps if (event == "trip_in_progress" and gps) else pickup
        routed = route_between(origin, dropoff)
        _persist_plan(
            db,
            ride=ride,
            pickup=pickup,
            dropoff=dropoff,
            driver=gps,
            points=list(routed.get("points") or []),
            distance_miles=routed.get("distance_miles"),
            duration_minutes=routed.get("duration_minutes"),
            leg=LEG_PICKUP_TO_DESTINATION,
            pickup_eta_minutes=None,
            destination_eta_minutes=routed.get("duration_minutes"),
            routing_provider=str(routed.get("provider") or "haversine"),
            geocode_provider=geocode_provider,
            eta_unavailable_reason=None,
        )
        return routing_snapshot_for_ride(db, ride=ride, driver_id=driver_id)

    if event == "arrived_destination":
        existing = _parse_payload(
            db.query(HealthISFRideRoutePlan).filter(HealthISFRideRoutePlan.ride_id == str(ride.id)).first()
        )
        points = existing.get("points") if isinstance(existing.get("points"), list) else []
        _persist_plan(
            db,
            ride=ride,
            pickup=pickup,
            dropoff=dropoff,
            driver=gps or _coord(existing, "driver"),
            points=points,
            distance_miles=existing.get("distance_miles"),
            duration_minutes=0,
            leg=LEG_PICKUP_TO_DESTINATION,
            pickup_eta_minutes=None,
            destination_eta_minutes=0,
            routing_provider=str(existing.get("routing_provider") or "none"),
            geocode_provider=geocode_provider or existing.get("geocode_provider"),
            eta_unavailable_reason=None,
        )
        return routing_snapshot_for_ride(db, ride=ride, driver_id=driver_id)

    return routing_snapshot_for_ride(db, ride=ride, driver_id=driver_id)


def safe_apply_lifecycle_routing(
    db: Session,
    *,
    ride_id: str,
    driver_id: str | None,
    event: str,
) -> dict[str, Any]:
    try:
        return apply_lifecycle_routing(db, ride_id=ride_id, driver_id=driver_id, event=event)
    except Exception as exc:
        logger.warning(
            "driver_mobile_routing_failed event=%s ride_id=%s error=%s",
            event,
            ride_id,
            exc,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return _empty_snapshot(reason="routing_failed")
