"""Time capability module."""
import re
from datetime import datetime, timedelta, timezone

import requests

from app.weather import resolve_location

TRIGGERS = ["time", "what time", "current time"]

_TZ_MAP = {
    "new york": ("America/New_York", -4),
    "los angeles": ("America/Los_Angeles", -7),
    "london": ("Europe/London", 1),
    "paris": ("Europe/Paris", 2),
    "tokyo": ("Asia/Tokyo", 9),
    "sydney": ("Australia/Sydney", 10),
    "dubai": ("Asia/Dubai", 4),
    "chicago": ("America/Chicago", -5),
}


def _schedule_hint(now: datetime, message: str) -> str:
    lower = message.lower()
    hour_match = re.search(r"in (\d+) hour", lower)
    if hour_match:
        hours = int(hour_match.group(1))
        future = now + timedelta(hours=hours)
        return f" If you are planning ahead, {hours} hours from now will be {future.strftime('%I:%M %p on %A, %b %d')}."
    if "tomorrow" in lower:
        future = now + timedelta(days=1)
        return f" Tomorrow at this time it will be {future.strftime('%I:%M %p on %A, %b %d')}."
    return ""


def handle(message: str, history: list = None, user_id: str = "default") -> dict:
    lower = message.lower()
    timezone_name = None
    fallback_offset = 0
    location_name = "UTC"
    for city, zone_info in _TZ_MAP.items():
        if city in lower:
            timezone_name = zone_info[0]
            fallback_offset = zone_info[1]
            location_name = city.title()
            break
    if timezone_name is None:
        try:
            location = resolve_location(message, fallback_label="your current area")
            timezone_name = location["timezone"]
            location_name = location["name"]
        except Exception:
            timezone_name = "UTC"

    try:
        response = requests.get(
            f"https://worldtimeapi.org/api/timezone/{timezone_name}",
            timeout=(3.05, 8),
            headers={"User-Agent": "Amicor/1.0 time client"},
        )
        response.raise_for_status()
        payload = response.json()
        now = datetime.fromisoformat(payload["datetime"])
    except Exception:
        now = datetime.now(timezone(timedelta(hours=fallback_offset)))

    response = (
        f"The current local time in {location_name} is {now.strftime('%I:%M %p, %A %B %d, %Y')} ({timezone_name})."
        + _schedule_hint(now, message)
    )
    return {
        "response": response,
        "sources": [
            {"title": "IANA Time Zone Database", "url": "https://www.iana.org/time-zones", "label": timezone_name},
        ],
        "status": "success",
        "meta": {"timezone": timezone_name, "location": location_name},
    }
