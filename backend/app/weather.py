import re
from typing import Any

import requests

from app.providers.resilience import get_breaker  # type: ignore

_HEADERS = {"User-Agent": "Amicor/1.0 weather client"}


def _extract_location(message: str) -> str | None:
    lower = message.lower()
    patterns = [
        r"weather in ([a-zA-Z\s,]+)",
        r"forecast for ([a-zA-Z\s,]+)",
        r"in ([a-zA-Z\s,]+)$",
        r"for ([a-zA-Z\s,]+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            candidate = match.group(1).strip(" ?!.,")
            candidate = re.sub(r"\b(today|tomorrow|tonight|this weekend|next week)\b", "", candidate)
            candidate = re.sub(r"\s+", " ", candidate).strip(" ,")
            return candidate
    return None


def resolve_location(message: str, fallback_label: str = "your area") -> dict[str, Any]:
    query = _extract_location(message)
    if query:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query, "count": 1, "language": "en", "format": "json"},
            timeout=(3.05, 10),
            headers=_HEADERS,
        )
        geo.raise_for_status()
        geo_payload: dict[str, Any] = geo.json()
        results: list[dict[str, Any]] = list(geo_payload.get("results") or [])
        if results:
            item: dict[str, Any] = results[0]
            return {
                "name": str(item.get("name", query)).title(),
                "region": item.get("admin1") or item.get("country"),
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "timezone": item.get("timezone", "UTC"),
                "source": "open-meteo-geocoding",
            }

    ip_geo = requests.get("https://ipwho.is/", timeout=(3.05, 6), headers=_HEADERS)
    ip_geo.raise_for_status()
    payload: dict[str, Any] = ip_geo.json()
    if not payload.get("success", True):
        raise ValueError("Location detection unavailable")
    return {
        "name": payload.get("city") or fallback_label,
        "region": payload.get("region") or payload.get("country"),
        "latitude": payload["latitude"],
        "longitude": payload["longitude"],
        "timezone": payload.get("timezone", {}).get("id", "UTC"),
        "source": "ipwho.is",
    }


def _weather_code_description(code: int) -> str:
    mapping = {
        0: "clear sky",
        1: "mainly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "foggy",
        48: "rime fog",
        51: "light drizzle",
        53: "moderate drizzle",
        55: "dense drizzle",
        61: "light rain",
        63: "moderate rain",
        65: "heavy rain",
        71: "light snow",
        73: "moderate snow",
        75: "heavy snow",
        80: "rain showers",
        95: "thunderstorm",
    }
    return mapping.get(code, "mixed conditions")


def _open_meteo_weather(location: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": location["timezone"],
            "forecast_days": 3,
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
        },
        timeout=(3.05, 10),
        headers=_HEADERS,
    )
    response.raise_for_status()
    return response.json()


def _wttr_fallback(location: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(
        f"https://wttr.in/{location['name']}?format=j1",
        timeout=(3.05, 10),
        headers=_HEADERS,
    )
    response.raise_for_status()
    return response.json()


def get_weather(message: str) -> dict[str, Any]:
    provider_errors: list[str] = []
    location = resolve_location(message)

    # Circuit breakers for weather providers
    breaker_meteo  = get_breaker("open_meteo",   failure_threshold=3, recovery_timeout=30)
    breaker_wttr   = get_breaker("wttr_in",      failure_threshold=4, recovery_timeout=20)

    if breaker_meteo.is_available():
        try:
            payload = _open_meteo_weather(location)
            current = payload["current"]
            daily = payload["daily"]
            response = (
                f"Current weather for {location['name']}"
                + (f", {location['region']}" if location.get("region") else "")
                + f": {current['temperature_2m']}°F, feels like {current['apparent_temperature']}°F, "
                  f"{_weather_code_description(int(current['weather_code']))}, wind {current['wind_speed_10m']} mph.\n"
                  f"Forecast: Today {daily['temperature_2m_max'][0]}°/{daily['temperature_2m_min'][0]}°F with {daily['precipitation_probability_max'][0]}% precipitation chance; "
                  f"Tomorrow {daily['temperature_2m_max'][1]}°/{daily['temperature_2m_min'][1]}°F."
            )
            breaker_meteo.record_success()
            return {
                "response": response,
                "sources": [
                    {"title": "Open-Meteo Forecast", "url": "https://open-meteo.com/", "label": "open-meteo.com"},
                    {"title": "Location Source", "url": "https://geocoding-api.open-meteo.com/", "label": location["source"]},
                ],
                "status": "success",
                "meta": {"provider": "open-meteo", "timezone": location["timezone"], "location": location["name"]},
            }
        except Exception as exc:
            breaker_meteo.record_failure()
            provider_errors.append(f"open-meteo: {exc}")
    else:
        provider_errors.append(f"open-meteo: circuit open (health={breaker_meteo.health_score:.2f})")

    if breaker_wttr.is_available():
        try:
            payload = _wttr_fallback(location)
            current = payload.get("current_condition", [{}])[0]
            upcoming = payload.get("weather", [{}])[:2]
            response = (
                f"Current weather for {location['name']}: {current.get('temp_F', '?')}°F with "
                f"{current.get('weatherDesc', [{}])[0].get('value', 'unavailable')}. "
                f"Forecast: today high {upcoming[0].get('maxtempF', '?')}°F, low {upcoming[0].get('mintempF', '?')}°F; "
                f"tomorrow high {upcoming[1].get('maxtempF', '?')}°F, low {upcoming[1].get('mintempF', '?')}°F."
            )
            breaker_wttr.record_success()
            return {
                "response": response,
                "sources": [
                    {"title": "wttr.in Forecast", "url": "https://wttr.in/", "label": "wttr.in"},
                ],
                "status": "partial",
                "meta": {"provider": "wttr.in", "provider_errors": provider_errors, "location": location["name"]},
            }
        except Exception as exc:
            breaker_wttr.record_failure()
            provider_errors.append(f"wttr.in: {exc}")
    else:
        provider_errors.append(f"wttr.in: circuit open (health={breaker_wttr.health_score:.2f})")

    return {
        "response": "Weather is temporarily unavailable. " + "; ".join(provider_errors),
        "sources": [],
        "status": "error",
        "meta": {"provider_errors": provider_errors},
    }
