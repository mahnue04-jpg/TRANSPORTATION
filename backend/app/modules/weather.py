"""Weather capability module."""
from app.weather import get_weather

TRIGGERS = ["weather"]


def handle(message: str, history: list = None) -> str:
    city = "miami"
    lower = message.lower()
    if "weather in" in lower:
        city = lower.split("weather in", 1)[1].strip()
    return get_weather(city)
