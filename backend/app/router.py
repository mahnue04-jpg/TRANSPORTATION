from app.modules import weather, news, search, business, education, email
from app.modules import time as time_module
from app.ai import ask_openai
from app.database import (
    get_memory_summary,
    get_preferences,
    get_recent_messages,
    save_memory_summary,
    save_message,
    save_preference,
)

# ── Capability registry ────────────────────────────────────────────────────
# Each entry: triggers (list of lowercase keywords), handler function,
# and whether the module benefits from conversation history.
#
# To add a new capability:
#   1. Create backend/app/modules/<name>.py with TRIGGERS and handle()
#   2. Add one entry here — that's it.
#
CAPABILITIES = {
    "weather": {
        "triggers": weather.TRIGGERS,
        "handler": weather.handle,
        "needs_history": False,
        "permission": "weather.read",
        "live": True,
    },
    "time": {
        "triggers": time_module.TRIGGERS,
        "handler": time_module.handle,
        "needs_history": False,
        "permission": "time.read",
        "live": True,
    },
    "news": {
        "triggers": news.TRIGGERS,
        "handler": news.handle,
        "needs_history": False,
        "permission": "search.read",
        "live": True,
    },
    "search": {
        "triggers": search.TRIGGERS,
        "handler": search.handle,
        "needs_history": False,
        "permission": "search.read",
        "live": True,
    },
    "email": {
        "triggers": email.TRIGGERS,
        "handler": email.handle,
        "needs_history": True,
        "permission": "email.compose",
        "live": True,
    },
    "business":  {"triggers": business.TRIGGERS,   "handler": business.handle,   "needs_history": True, "permission": "business.advice", "live": True},
    "education": {"triggers": education.TRIGGERS,  "handler": education.handle,  "needs_history": True, "permission": "education.tutor", "live": True},
}


def _memory_context(user_id: str) -> list:
    summary = get_memory_summary(user_id)
    preferences = get_preferences(user_id)
    parts = []
    if summary:
        parts.append(f"Conversation summary: {summary}")
    if preferences:
        pref_text = ", ".join(f"{key}={value}" for key, value in preferences.items())
        parts.append(f"Known preferences: {pref_text}")
    if not parts:
        return []
    return [{"role": "system", "content": "\n".join(parts)}]


def _extract_preferences(message: str) -> dict:
    lower = message.lower()
    found = {}
    if "my name is " in lower:
        found["name"] = message.split("my name is ", 1)[1].split(".")[0].strip()
    if "call me " in lower:
        found["preferred_name"] = message.split("call me ", 1)[1].split(".")[0].strip()
    if "i live in " in lower:
        found["location"] = message.split("i live in ", 1)[1].split(".")[0].strip()
    if "i prefer " in lower:
        found["preference"] = message.split("i prefer ", 1)[1].split(".")[0].strip()
    return found


def _summarize_history(history: list) -> str | None:
    if not history:
        return None
    user_points = [item["content"] for item in history if item["role"] == "user"][-3:]
    assistant_points = [item["content"] for item in history if item["role"] == "assistant"][-2:]
    parts = []
    if user_points:
        parts.append("Recent user topics: " + " | ".join(user_points))
    if assistant_points:
        parts.append("Recent assistant help: " + " | ".join(assistant_points))
    return "; ".join(parts)[:1000] if parts else None


def _normalize_result(tool_name: str, raw_result, capability: dict) -> dict:
    if isinstance(raw_result, dict):
        response = raw_result.get("response") or raw_result.get("reply") or "No response."
        return {
            "tool": tool_name,
            "response": response,
            "sources": raw_result.get("sources", []),
            "status": raw_result.get("status", "success"),
            "capability": {
                "name": tool_name,
                "permission": capability["permission"],
                "live": capability["live"],
            },
            "meta": raw_result.get("meta", {}),
        }
    return {
        "tool": tool_name,
        "response": raw_result,
        "sources": [],
        "status": "success",
        "capability": {
            "name": tool_name,
            "permission": capability["permission"],
            "live": capability["live"],
        },
        "meta": {},
    }


def route_message(message: str, user_id: str = "default") -> dict:
    lower = message.lower()
    history_with_memory = _memory_context(user_id) + get_recent_messages(user_id, limit=10)
    user_preferences = _extract_preferences(message)
    for key, value in user_preferences.items():
        save_preference(user_id, key, value)

    for name, cap in CAPABILITIES.items():
        if any(t in lower for t in cap["triggers"]):
            history = history_with_memory if cap["needs_history"] else None
            response = cap["handler"](message, history=history, user_id=user_id)
            result = _normalize_result(name, response, cap)
            save_message(user_id, "user", message)
            save_message(user_id, "assistant", result["response"])
            summary = _summarize_history(get_recent_messages(user_id, limit=12))
            if summary:
                save_memory_summary(user_id, summary)
            return result

    # ── OpenAI fallback — always includes conversation history ────────────
    history = history_with_memory
    save_message(user_id, "user", message)
    response = ask_openai(message, history=history)
    save_message(user_id, "assistant", response)
    summary = _summarize_history(get_recent_messages(user_id, limit=12))
    if summary:
        save_memory_summary(user_id, summary)
    return {
        "tool": "openai",
        "response": response,
        "sources": [],
        "status": "success",
        "capability": {"name": "openai", "permission": "assistant.chat", "live": True},
        "meta": {},
    }
