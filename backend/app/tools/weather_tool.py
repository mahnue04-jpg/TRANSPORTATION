from app.weather import get_weather  # type: ignore

def handle_weather(message: str) -> str:
    city = "miami"
    lower = message.lower()
    if "weather in" in lower:
        city = lower.split("weather in", 1)[1].strip()
    return get_weather(city)
