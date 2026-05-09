"""Weather capability module."""
from app.weather import get_weather

TRIGGERS = ["weather", "forecast", "temperature", "rain", "snow"]


def handle(message: str, history: list = None, user_id: str = "default") -> dict:
    return get_weather(message)
