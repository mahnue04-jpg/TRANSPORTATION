"""Read-only live utilities and lightweight per-user conversational memory for Nova Today."""
from __future__ import annotations

import re
import math
from datetime import datetime
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.core.nova.today.reasoning import is_self_contained_math_request

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
            # Spoken requests often finish with a time phrase or Nova's name.
            # Keep those conversational suffixes out of the geocoder city query.
            for _ in range(3):
                candidate = re.sub(
                    r"(?i)[,\s]+(?:(?:mrs\.?\s+)?nova|please|today|tonight|right now|currently)[,\s]*$",
                    "",
                    candidate,
                ).strip(" ,?!.")
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
        "what is the latest news",
        "what's the latest news",
        "what is the latest news today",
        "what's the latest news today",
        "show me the news",
        "show me the latest news",
        "headlines",
        "latest headlines",
        "latest headlines today",
    }
    normalized = re.sub(r"[^a-z ]+", "", lowered).strip()
    if normalized in generic:
        return None
    candidate = re.sub(
        r"(?i)\b(latest|current|today'?s|today|show me|what is|what's|give me|news|headlines?)\b",
        " ",
        value,
    )
    candidate = _clean(candidate).strip(" ?!.,")
    stop_only = {"the", "a", "an", "about", "on", "for", "of"}
    if candidate.lower() in stop_only:
        return None
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
    required = ("temperature_2m", "apparent_temperature", "relative_humidity_2m", "wind_speed_10m", "weather_code")
    if any(isinstance(current.get(key), bool) or not isinstance(current.get(key), (int, float)) or not math.isfinite(current[key]) for key in required):
        raise ValueError("weather observation is incomplete")
    try:
        datetime.fromisoformat(current.get("time") or "")
    except (TypeError, ValueError):
        raise ValueError("weather observation time is missing or invalid") from None
    code = int(current["weather_code"])
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


def format_news_search_fallback(result: dict[str, Any], query: str | None = None) -> str:
    sources = [
        item for item in (result.get("sources") or [])
        if isinstance(item, dict) and _clean(item.get("title"))
    ]
    if not sources:
        return "I could not find current news results right now."

    heading = f"Here is a quick news briefing for {query}:" if query else "Here is a quick news briefing:"
    lines = [heading]
    for index, item in enumerate(sources[:5], 1):
        title = _clean(str(item.get("title") or ""))
        label = _clean(str(item.get("label") or "Source"))
        lines.append(f"{index}. {title} ({label})")
    lines.append("Open a source link below to read the full story.")
    return "\n".join(lines)



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


def _private_work_question(text: str) -> bool:
    lowered = _clean(text).lower().replace("’", "'")
    return bool(re.search(
        r"\b(?:workspace|tasks?|projects?|invoices?|mailbox|approvals?|saved records?|my account|our account)\b"
        r"|\b(?:my|our)\b.{0,100}\b(?:accounts?|subscriptions?|fantasy|staff|employees?|clients?|saved)\b",
        lowered,
    ))


def _sports_entity(text: str):
    lowered = _clean(text).lower()
    matches = list(re.finditer(
        r"\b(?:sports?|nba|wnba|nfl|nhl|mlb|basketball|football|baseball|hockey|soccer|"
        r"timberwolves|wolves|vikings|lions|lynx|twins|lakers|celtics|warriors|"
        r"76ers|sixers|knicks|nets|raptors|cavaliers|cavs|bucks|bulls|pacers|pistons|"
        r"hawks|hornets|wizards|nuggets|thunder|trail blazers|grizzlies|pelicans|rockets|"
        r"spurs|mavericks|clippers|kings|jazz|heat|magic|suns|packers|bears|chiefs|bills|"
        r"ravens|bengals|browns|steelers|texans|colts|jaguars|titans|broncos|chargers|"
        r"raiders|cowboys|eagles|giants|commanders|patriots|jets|dolphins|falcons|"
        r"panthers|saints|buccaneers|49ers|niners|rams|seahawks|cardinals)\b",
        lowered,
    ))
    if not matches:
        return None
    ambiguous = {
        "bills", "bucks", "bulls", "twins", "bears", "giants", "jets", "dolphins",
        "lions", "panthers", "cardinals", "saints", "rams", "suns", "kings", "nets",
        "heat", "magic", "jazz", "thunder", "rockets",
    }
    clear = [match for match in matches if match.group(0) not in ambiguous]
    if clear:
        return clear[0]
    city_context = re.search(
        r"\b(?:buffalo|detroit|minnesota|milwaukee|chicago|new york|miami|orlando|utah|"
        r"phoenix|sacramento|houston|oklahoma city|philadelphia|baltimore|atlanta|"
        r"arizona|new orleans|los angeles|carolina|jacksonville)\b",
        lowered,
    )
    if city_context or _sports_followup_intent(text) or len({match.group(0) for match in matches}) > 1:
        return matches[0]
    return None


def _sports_followup_intent(text: str) -> bool:
    return bool(re.search(
        r"\b(?:watch|stream|broadcast|channel|televised|listen|win|wins|winning|"
        r"prediction|predict|favourite|favorite|playing|starting|starters?|players?|rosters?|"
        r"line[\s-]?ups?|scores?|injur(?:y|ies)|standings|coach(?:es)?|schedules?)\b|\bwhat time\b|\bwhen\b.{0,50}\bstart\b",
        _clean(text).lower(),
    ))


def is_public_sports_request(text: str) -> bool:
    """Public sports facts/analysis use live research by default, not a phrase whitelist."""
    if _private_work_question(text):
        return False
    lowered = _clean(text).lower()
    context = _sports_entity(text) or (
        re.search(r"\b(?:games?|matches|matchups?|playoffs|super bowl)\b", lowered)
        and _sports_followup_intent(text)
    )
    if not context:
        return False
    conceptual = re.search(r"^(?:please\s+)?(?:explain|teach|define)\b", lowered) and re.search(
        r"\b(?:rules|basics|fundamentals|definition|meaning|pick.and.roll|offside)\b", lowered
    )
    fresh = re.search(r"\b(?:current|latest|recent|live|today|tonight|this season|new|changed)\b", lowered)
    return not (conceptual and not fresh)


def resolve_public_sports_followup(question: str, public_topic: str | None = None) -> str:
    """Use only the prior public question, never a saved/private answer."""
    original_question = question
    question = _clean(question)
    topic = _clean(public_topic or "")[:1200]
    if not topic or _private_work_question(question) or _sports_entity(question):
        return original_question
    if not is_public_sports_request(topic) or not _sports_followup_intent(question):
        return original_question
    # Explicit new matchups remain independent, even if their teams are unfamiliar.
    if re.search(r"\b(?:versus|vs\.?|against|between)\b", question, re.I):
        return original_question
    return f"Regarding the public sports topic: {topic}\nFollow-up question: {question}"



def is_sports_viewing_request(text: str) -> bool:
    intent = text.rsplit("\nFollow-up question: ", 1)[-1]
    return is_public_sports_request(text) and bool(re.search(
        r"\b(?:watch|view|stream|streams|streaming|broadcast|channel|televised|listen)\b",
        _clean(intent).lower(),
    ))


def is_sports_prediction_request(text: str) -> bool:
    intent = text.rsplit("\nFollow-up question: ", 1)[-1]
    return is_public_sports_request(text) and bool(re.search(
        r"\b(?:predict|prediction|predictions)\b|\bwho\b.{0,100}\b(?:win|wins|winning)\b"
        r"|\b(?:likely|favou?rite|chances)\b.{0,60}\b(?:win|winning)\b",
        _clean(intent).lower(),
    ))


def is_current_public_information_request(text: str) -> bool:
    """Recognize public status/events without diverting saved operational work."""
    lowered = _clean(text).lower().replace("’", "'")
    if _private_work_question(text):
        return False
    if is_public_sports_request(text):
        return True
    if re.search(r"\b(?:my|our)\b", lowered):
        return False
    status_or_event = re.search(
        r"\b(?:current|latest|recent|live)\s+(?:status|updates?|scores?|results?|standings|roster|lineup)\b"
        r"|\bwhat happened to\b|\bwhat(?:'s| is) (?:happening|going on) with\b"
        r"|\bany updates on\b",
        lowered,
    )
    if status_or_event:
        return True
    sports = re.search(
        r"\b(?:players?|athletes?|teams?|games?|matches|playing|injur(?:y|ies|ed)|"
        r"scores?|standings|lineup|roster|win|won|winning)\b",
        lowered,
    )
    freshness = re.search(
        r"\b(?:current|latest|recent|live|today|tonight|yesterday|updates?|"
        r"right now|last night|this week|this season)\b",
        lowered,
    )
    return bool(sports and freshness)


def is_web_search_request(text: str) -> bool:
    """Recognize both explicit browsing commands and natural current-research questions."""
    lowered = _clean(text).lower()
    if is_self_contained_math_request(text):
        return False
    if is_weather_request(text):
        return False
    if is_web_search_capability_question(text):
        return False
    if is_public_sports_request(text):
        return True
    if is_news_request(text):
        return False
    if is_current_public_information_request(text):
        return True

    explicit = any(
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
    if explicit:
        return True

    external_topics = (
        "grant", "funding", "loan program", "contract", "rfp", "bid opportunity",
        "solicitation", "government program", "business program", "license", "permit",
        "regulation", "requirement", "deadline", "eligibility", "eligible", "price",
        "pricing", "rate", "fee", "vendor", "supplier", "program",
    )
    research_intent = (
        "available", "current", "latest", "today", "open now", "recommend",
        "recommendation", "best", "qualify", "eligible", "apply", "application",
        "deadline", "find", "search", "what kind", "which", "where can",
    )
    has_topic = any(term in lowered for term in external_topics)
    has_research_intent = any(term in lowered for term in research_intent)

    # Natural phrasing such as "free grants for my delivery company" is itself a
    # current external-research request even without the words "search the web".
    natural_funding = any(
        phrase in lowered
        for phrase in (
            "grants for", "grant for", "free grants", "funding for",
            "contracts for", "contract opportunities", "bid opportunities",
            "rfp opportunities",
        )
    )

    # Product, vendor, local-place, food, and visual-discovery questions require
    # current external results even when the user never says "search the web".
    discovery_actions = (
        "find", "show me", "pull up", "recommend", "compare", "buy", "shop for",
        "where can i get", "where can i buy", "near me", "nearby", "available",
        "photos of", "pictures of", "images of",
    )
    discovery_topics = (
        "toy", "toys", "toilet", "toilets", "car part", "car parts", "auto part",
        "auto parts", "vendor", "vendors", "supplier", "suppliers", "restaurant",
        "restaurants", "food", "grocery", "groceries", "store", "stores", "product",
        "products", "hotel", "hotels", "clinic", "clinics", "hospital", "hospitals",
        "pharmacy", "pharmacies", "mechanic", "mechanics",
    )
    discovery_request = (
        any(action in lowered for action in discovery_actions)
        and any(topic in lowered for topic in discovery_topics)
    )

    return natural_funding or discovery_request or (has_topic and has_research_intent)


_PUBLIC_QUERY_STOP_WORDS = frozenset(
    "what whats is are was were the a an of for from with to in on at about and or "
    "please tell me can you do does did how any my our current latest recent status "
    "update updates news live now today tonight yesterday right going happening "
    "happened playing play injury injured score scores mrs nova search web internet look up".split()
)


def public_query_terms(text: str) -> list[str]:
    """Keep the subject words, removing question wording and freshness cues."""
    tokens = re.findall(r"[a-z0-9]+", _clean(text).lower().replace("’", "'"))
    return list(dict.fromkeys(token for token in tokens if len(token) >= 3 and token not in _PUBLIC_QUERY_STOP_WORDS))


def source_matches_public_query(item: dict[str, Any], terms: list[str]) -> bool:
    if not terms:
        return False
    haystack = set(re.findall(r"[a-z0-9]+", " ".join(str(item.get(key) or "").lower() for key in ("title", "url", "snippet"))))
    # A surname or a location alone must not qualify an unrelated result.
    minimum = 1 if len(terms) == 1 else max(2, (len(terms) * 3 + 4) // 5)
    return sum(term in haystack for term in terms) >= minimum


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


def fetch_web_search(
    query: str,
    *,
    max_results: int = 5,
    require_domains: list[str] | None = None,
    require_terms: list[str] | None = None,
) -> dict[str, Any]:
    result = search_web(
        query,
        max_results=max_results,
        news_mode=False,
        require_domains=require_domains,
        require_terms=require_terms,
    )
    if not isinstance(result, dict):
        return {"response": "I couldn't fetch live web results right now.", "sources": [], "status": "degraded"}
    return result


def format_web_search(result: dict[str, Any], query: str) -> str:
    response = _clean(str(result.get("response") or ""))
    if response:
        return response
    return f"I searched the web for {query}, but I couldn't summarize the results right now."
