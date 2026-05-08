from app.tools.weather_tool import handle_weather
from app.tools.search_tool import handle_search
from app.tools.news_tool import handle_news
from app.tools.time_tool import handle_time
from app.ai import ask_openai

WEATHER_TRIGGERS = ["weather"]
NEWS_TRIGGERS = ["news", "headline", "what happened"]
SEARCH_TRIGGERS = ["search", "look up", "find", "latest"]
TIME_TRIGGERS = ["time", "what time", "current time"]


def route_message(message: str) -> dict:
    lower = message.lower()

    if any(t in lower for t in WEATHER_TRIGGERS):
        return {"tool": "weather", "response": handle_weather(message)}

    if any(t in lower for t in TIME_TRIGGERS):
        return {"tool": "time", "response": handle_time(message)}

    if any(t in lower for t in NEWS_TRIGGERS):
        return {"tool": "news", "response": handle_news(message)}

    if any(t in lower for t in SEARCH_TRIGGERS):
        return {"tool": "search", "response": handle_search(message)}

    return {"tool": "openai", "response": ask_openai(message)}
