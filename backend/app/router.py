from app.tools.weather_tool import handle_weather
from app.tools.search_tool import handle_search
from app.tools.news_tool import handle_news
from app.tools.time_tool import handle_time
from app.ai import ask_openai
from app.business import handle_business_request
from app.database import save_message, get_recent_messages

WEATHER_TRIGGERS  = ["weather"]
NEWS_TRIGGERS     = ["news", "headline", "what happened"]
SEARCH_TRIGGERS   = ["search", "look up", "find", "latest"]
TIME_TRIGGERS     = ["time", "what time", "current time"]
BUSINESS_TRIGGERS = [
    "business", "startup", "start a", "start my", "checklist",
    "business plan", "business idea", "business ideas",
    "construction", "salon", "landscaping", "trucking", "transport",
    "production", "manufacturing",
    "pricing", "price my", "how much should i charge",
    "marketing", "advertise", "promote",
    "proposal", "client proposal", "quote for",
    "invoice", "invoicing",
    "hire", "hiring", "job description", "onboarding",
    "permit", "license", "llc", "sole proprietor", "incorporate",
    "operations", "workflow", "profit margin",
]


def route_message(message: str, user_id: str = "default") -> dict:
    lower = message.lower()

    # ── Stateless tool routes ──────────────────────────────────────────
    if any(t in lower for t in WEATHER_TRIGGERS):
        response = handle_weather(message)
        save_message(user_id, "user", message)
        save_message(user_id, "assistant", response)
        return {"tool": "weather", "response": response}

    if any(t in lower for t in TIME_TRIGGERS):
        response = handle_time(message)
        save_message(user_id, "user", message)
        save_message(user_id, "assistant", response)
        return {"tool": "time", "response": response}

    if any(t in lower for t in NEWS_TRIGGERS):
        response = handle_news(message)
        save_message(user_id, "user", message)
        save_message(user_id, "assistant", response)
        return {"tool": "news", "response": response}

    if any(t in lower for t in SEARCH_TRIGGERS):
        response = handle_search(message)
        save_message(user_id, "user", message)
        save_message(user_id, "assistant", response)
        return {"tool": "search", "response": response}

    # ── Business advisor — includes conversation history ───────────────
    if any(t in lower for t in BUSINESS_TRIGGERS):
        history = get_recent_messages(user_id, limit=10)
        save_message(user_id, "user", message)
        response = handle_business_request(message, history=history)
        save_message(user_id, "assistant", response)
        return {"tool": "business", "response": response}

    # ── General OpenAI fallback — includes conversation history ───────
    history = get_recent_messages(user_id, limit=10)
    save_message(user_id, "user", message)
    response = ask_openai(message, history=history)
    save_message(user_id, "assistant", response)
    return {"tool": "openai", "response": response}
