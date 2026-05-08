from app.modules import weather, news, search, business
from app.modules import time as time_module
from app.ai import ask_openai
from app.database import save_message, get_recent_messages

# ── Capability registry ────────────────────────────────────────────────────
# Each entry: triggers (list of lowercase keywords), handler function,
# and whether the module benefits from conversation history.
#
# To add a new capability:
#   1. Create backend/app/modules/<name>.py with TRIGGERS and handle()
#   2. Add one entry here — that's it.
#
CAPABILITIES = {
    "weather":  {"triggers": weather.TRIGGERS,     "handler": weather.handle,     "needs_history": False},
    "time":     {"triggers": time_module.TRIGGERS,  "handler": time_module.handle,  "needs_history": False},
    "news":     {"triggers": news.TRIGGERS,         "handler": news.handle,         "needs_history": False},
    "search":   {"triggers": search.TRIGGERS,       "handler": search.handle,       "needs_history": False},
    "business": {"triggers": business.TRIGGERS,     "handler": business.handle,     "needs_history": True},
}


def route_message(message: str, user_id: str = "default") -> dict:
    lower = message.lower()

    for name, cap in CAPABILITIES.items():
        if any(t in lower for t in cap["triggers"]):
            history = get_recent_messages(user_id, limit=10) if cap["needs_history"] else None
            response = cap["handler"](message, history)
            save_message(user_id, "user", message)
            save_message(user_id, "assistant", response)
            return {"tool": name, "response": response}

    # ── OpenAI fallback — always includes conversation history ────────────
    history = get_recent_messages(user_id, limit=10)
    save_message(user_id, "user", message)
    response = ask_openai(message, history=history)
    save_message(user_id, "assistant", response)
    return {"tool": "openai", "response": response}
