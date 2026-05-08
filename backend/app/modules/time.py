"""Time capability module."""
from datetime import datetime, timezone, timedelta

TRIGGERS = ["time", "what time", "current time"]

_TZ_MAP = {
    "new york":    ("UTC-5/UTC-4", -5),
    "los angeles": ("UTC-8/UTC-7", -8),
    "london":      ("UTC+0/UTC+1",  0),
    "paris":       ("UTC+1/UTC+2",  1),
    "tokyo":       ("UTC+9",        9),
    "sydney":      ("UTC+10/UTC+11", 10),
    "dubai":       ("UTC+4",        4),
    "chicago":     ("UTC-6/UTC-5", -6),
}


def handle(message: str, history: list = None) -> str:
    lower = message.lower()
    for city, (label, offset) in _TZ_MAP.items():
        if city in lower:
            now = datetime.now(timezone(timedelta(hours=offset)))
            return (
                f"The current time in {city.title()} is approximately "
                f"{now.strftime('%I:%M %p, %A %B %d, %Y')} ({label})."
            )
    now = datetime.now(timezone.utc)
    return f"The current UTC time is {now.strftime('%I:%M %p, %A %B %d, %Y')} UTC."
