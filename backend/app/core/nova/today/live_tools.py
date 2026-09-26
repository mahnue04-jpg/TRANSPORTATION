"""Read-only live utilities and lightweight per-user conversational memory for Nova Today."""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.core.nova.memory import memory_store
from app.web_search import search_web


_WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_user_profile(organization_id: str, user_id: str) -> dict[str, Any]:
    state = memory_store.read(organization_id)
    profiles = state.get("user_profiles")
    if not isinstance(profiles, dict):
        return {}
    row = profiles.get(str(user_id))
    return dict(row) if isinstance(row, dict) else {}


def update_user_profile(organization_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    state = memory_store.read(organization_id)
    profiles = state.get("user_profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    current = profiles.get(str(user_id))
    current = dict(current) if isinstance(current, dict) else {}
    current.update({k: v for k, v in dict(patch or {}).items() if v is not None})
    profiles[str(user_id)] = current
    memory_store.write(organization_id, {"user_profiles": profiles})
    return current


def extract_name_statement(text: str) -> str | None:
    value = _clean(text)
    patterns = (
        r"(?i)^my name is\s+([A-Za-z][A-Za-z .'-]{0,79})[.!?]?$",
        r"(?i)^please call me\s+([A-Za-z][A-Za-z .'-]{0,79})[.!?]?$",
        r"(?i)^call me\s+([A-Za-z][A-Za-z .'-]{0,79})[.!?]?$",
    )
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            return _clean(match.group(1)).rstrip(".!?")
    return None


def extract_location_statement(text: str) -> str | None:
    value = _clean(text)
    patterns = (
        r"(?i)^i live in\s+(.{2,100}?)[.!?]?$",
        r"(?i)^my location is\s+(.{2,100}?)[.!?]?$",
        r"(?i)^remember my location as\s+(.{2,100}?)[.!?]?$",
    )
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            return _clean(match.group(1)).rstrip(".!?")
    return None


def asks_for_name(text: str) -> bool:
    lowered = _clean(text).lower()
    return any(
        phrase in lowered
        for phrase in (
            "what is my name",
            "what's my name",
            "do you remember my name",
            "who am i",
        )
    )


def extract_weather_location(text: str) -> str | None:
    value = _clean(text)
    patterns = (
        r"(?i)(?:weather|forecast).*?\b(?:in|for)\s+(.+?)[?!.]?$",
        r"(?i)^(.+?)\s+weather[?!.]?$",
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            candidate = _clean(match.group(1)).rstrip("?!.")
            if candidate and candidate.lower() not in {"the", "today", "tomorrow"}:
                return candidate
    return None


def is_weather_request(text: str) -> bool:
    lowered = _clean(text).lower()
    return "weather" in lowered or "forecast" in lowered


def is_news_request(text: str) -> bool:
    lowered = _clean(text).lower()
    return any(token in lowered for token in ("news", "headline", "headlines"))


def extract_news_query(text: str) -> str | None:
    value = _clean(text)
    lowered = value.lower()
    if not is_news_request(value):
        return None
    generic = {
        "news",
        "the news",
        "latest news",
        "what is the news",
        "what's the news",
        "show me the news",
        "headlines",
        "latest headlines",
    }
    normalized = re.sub(r"[^a-z ]+", "", lowered).strip()
    if normalized in generic:
        return None
    candidate = re.sub(r"(?i)\b(latest|current|today'?s|today|show me|what is|what's|give me|news|headlines?)\b", " ", value)
    candidate = _clean(candidate).strip(" ?!.,")
    return candidate or None


def fetch_weather(location: str) -> dict[str, Any]:
    place = _clean(location)
    if not place:
        raise ValueError("location is required")

    with httpx.Client(timeout=12.0, follow_redirects=True) as client:
        geo = client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": place, "count": 1, "language": "en", "format": "json"},
            headers={"User-Agent": "AMICOR-Nova/1.0"},
        )
        geo.raise_for_status()
        results = (geo.json() or {}).get("results") or []
        if not results:
            raise ValueError("location not found")
        row = results[0]
        latitude = row["latitude"]
        longitude = row["longitude"]
        label_parts = [row.get("name"), row.get("admin1"), row.get("country")]
        label = ", ".join(str(x) for x in label_parts if x)

        forecast = client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto",
            },
            headers={"User-Agent": "AMICOR-Nova/1.0"},
        )
        forecast.raise_for_status()
        payload = forecast.json() or {}

    current = payload.get("current") or {}
    code = int(current.get("weather_code") or 0)
    return {
        "location": label or place,
        "temperature_f": current.get("temperature_2m"),
        "apparent_f": current.get("apparent_temperature"),
        "humidity_pct": current.get("relative_humidity_2m"),
        "wind_mph": current.get("wind_speed_10m"),
        "condition": _WEATHER_CODES.get(code, f"weather code {code}"),
        "observed_at": current.get("time"),
        "source": "Open-Meteo",
    }


def format_weather(result: dict[str, Any]) -> str:
    return (
        f"Current weather for {result.get('location')}: "
        f"{result.get('temperature_f')}°F, {result.get('condition')}. "
        f"Feels like {result.get('apparent_f')}°F. "
        f"Humidity {result.get('humidity_pct')}%. "
        f"Wind {result.get('wind_mph')} mph. "
        "Source: Open-Meteo."
    )


def fetch_news(query: str | None = None, *, limit: int = 5) -> list[dict[str, str]]:
    if query:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    else:
        url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"

    with httpx.Client(timeout=12.0, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "AMICOR-Nova/1.0"})
        response.raise_for_status()
        root = ET.fromstring(response.text)

    items: list[dict[str, str]] = []
    for item in root.findall("./channel/item")[: max(1, min(10, int(limit)))]:
        title = _clean(item.findtext("title"))
        link = _clean(item.findtext("link"))
        pub_date = _clean(item.findtext("pubDate"))
        source_node = item.find("source")
        source = _clean(source_node.text if source_node is not None else "")
        if title and link:
            items.append(
                {
                    "title": title,
                    "link": link,
                    "published": pub_date,
                    "source": source or "Google News",
                }
            )
    return items


def _clean_news_title(title: str, source: str) -> str:
    value = _clean(title)
    source_value = _clean(source)
    suffix = f" - {source_value}"
    if source_value and value.lower().endswith(suffix.lower()):
        value = value[: -len(suffix)].rstrip(" -")
    return value


def format_news(items: list[dict[str, str]], query: str | None = None) -> str:
    if not items:
        return "I could not find current news results right now."
    heading = f"Here is a quick news briefing for {query}:" if query else "Here is a quick news briefing:"
    lines = [heading]
    for index, item in enumerate(items, 1):
        source = _clean(item.get("source") or "Source")
        title = _clean_news_title(str(item.get("title") or ""), source)
        lines.append(f"{index}. {title} ({source})")
    lines.append("I can open the first source link if you want to read more.")
    return "\n".join(lines)


_KNOWN_SITES = {
    "youtube": ("YouTube", "https://www.youtube.com/"),
    "facebook": ("Facebook", "https://www.facebook.com/"),
    "instagram": ("Instagram", "https://www.instagram.com/"),
    "tiktok": ("TikTok", "https://www.tiktok.com/"),
    "linkedin": ("LinkedIn", "https://www.linkedin.com/"),
    "reddit": ("Reddit", "https://www.reddit.com/"),
    "x": ("X", "https://x.com/"),
    "twitter": ("X", "https://x.com/"),
}


def is_web_search_capability_question(text: str) -> bool:
    lowered = _clean(text).lower()
    return any(
        phrase in lowered
        for phrase in (
            "can you search the web",
            "can you search web",
            "can you browse the web",
            "can you browse internet",
            "can you search the internet",
            "do you search the web",
        )
    )


def is_web_search_request(text: str) -> bool:
    lowered = _clean(text).lower()
    if is_weather_request(text) or is_news_request(text):
        return False
    if is_web_search_capability_question(text):
        return False
    return any(
        phrase in lowered
        for phrase in (
            "search the web",
            "search web",
            "search the internet",
            "look up",
            "lookup",
            "find online",
            "find on the web",
            "latest movie",
            "movies playing",
            "movie playing",
            "open youtube",
            "open facebook",
            "open instagram",
            "open tiktok",
            "open linkedin",
            "open reddit",
            "open twitter",
            "open x",
        )
    )


def extract_known_site(text: str) -> tuple[str, str] | None:
    lowered = _clean(text).lower()
    action_phrases = (
        "open",
        "look up",
        "lookup",
        "go to",
        "show me",
        "take me to",
        "take me directly to",
        "pull up",
        "bring up",
        "launch",
        "visit",
        "access",
        "navigate to",
    )
    if not any(phrase in lowered for phrase in action_phrases):
        return None
    for key, value in _KNOWN_SITES.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", lowered):
            return value
    return None


def extract_web_query(text: str, preferred_location: str | None = None) -> str:
    value = _clean(text)
    query = re.sub(
        r"(?i)\b(can you|please|nova|search the web for|search web for|search the internet for|"
        r"search the web|search web|search the internet|look up|lookup|find online|find on the web)\b",
        " ",
        value,
    )
    query = _clean(query).strip(" ?!.,")
    lowered = query.lower()
    if preferred_location and ("movie" in lowered or "movies" in lowered) and not any(
        token in lowered for token in (" near ", " in ", " around ", " minneapolis", " saint paul", " st paul")
    ):
        query = f"{query} near {preferred_location}".strip()
    return query or value


def fetch_web_search(query: str, *, max_results: int = 5) -> dict[str, Any]:
    result = search_web(query, max_results=max_results, news_mode=False)
    if not isinstance(result, dict):
        return {"response": "I couldn't fetch live web results right now.", "sources": [], "status": "degraded"}
    return result


def format_web_search(result: dict[str, Any], query: str) -> str:
    response = _clean(str(result.get("response") or ""))
    if response:
        return response
    return f"I searched the web for {query}, but I couldn't summarize the results right now."
