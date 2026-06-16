from app.modules import weather, news, search, business, education, email
from app.modules import time as time_module
from app.ai import ask_openai # type: ignore
from app.response_engine import apply_response_engine
from app.tool_execution_engine import get_execution_engine
from app.tool_registry import get_registry
from app.tool_actions import register_default_tools # type: ignore
from app import logging_utils
from app.database import (
    get_memory_summary,
    get_preferences, # type: ignore
    get_recent_messages, # pyright: ignore[reportUnknownVariableType]
    save_memory_summary,
    save_message,
    save_preference,
)
import logging
import time
import re
import asyncio
import threading
import queue

logger = logging.getLogger("amicor.router")

# Initialize tool execution infrastructure on module load
_tool_registry = get_registry()
register_default_tools(_tool_registry)
_execution_engine = get_execution_engine(_tool_registry)
OPENAI_TIMEOUT_SECONDS = 30.0
STATELESS_CLAIM_PATTERNS = [
    "cannot remember",
    "can't remember",
    "don't have any information about you",
    "do not have any information about you",
    "cannot access personal data",
    "can't access personal data",
    "do not have access to personal data",
    "don't have access to personal data",
    "don't have the capability to remember",
    "do not have the capability to remember",
    "don't have the ability to remember",
    "do not have the ability to remember",
    "do not store memory",
    "don't store memory",
    "don't retain memory",
    "do not retain memory",
    "stateless",
    "fresh conversation",
    "each session is independent",
    "cannot recall previous interactions",
    "can't recall previous interactions",
    "do not have the ability to recall",
    "between conversations",
    "each interaction is treated independently",
    "won't retain any details",
    "will not retain any details",
    "won't retain this",
    "will not retain this",
    "won't retain information",
    "will not retain information",
    "remember personal information between conversations",
]
MEMORY_IDENTITY_RULE = (
    "Identity policy: You are memory-capable. Never claim you are stateless, "
    "never say you cannot remember previous conversations, and never say you do not store memory. "
    "If durable memory is unavailable for a specific detail, reply exactly: 'I don't know that yet.'"
)
MEMORY_SELF_KNOWLEDGE_PATTERNS = (
    "what do you remember",
    "what do you know about me",
    "can you remember",
    "how can you remember",
    "what can i do as a builder",
    "personal information",
    "long-term memory",
    "long term memory",
    "short-term memory",
    "short term memory",
    "delete memory",
    "clear memory",
    "wipe memory",
    "remove memory",
)

LEGACY_LIVE_UNAVAILABLE_PATTERNS = (
    "don't have real-time access",
    "do not have real-time access",
    "don't have realtime access",
    "do not have realtime access",
    "no real-time access",
    "no realtime access",
)

# Capability route priorities: business/productivity FIRST, then live data
# This ensures prompts like "research", "business plan", "marketing ideas"
# route to proper handlers BEFORE generic live_lookup fallback
LIVE_INTENT_RULES = { # type: ignore
    # ── Business/Productivity (checked first) ────────────────────────
    "business": {
        "keywords": [
            "business plan", "startup", "startup plan", "marketing ideas", "marketing",
            "proposal", "invoice", "pricing", "operations", "hire", "hiring",
        ],
        "route": "business",
    },
    "research": {
        "keywords": ["research", "analyze", "investigate", "look into", "find out"],
        "route": "search",  # or research handler if available
    },
    "summarize": {
        "keywords": ["summarize", "summary", "summarise", "brief", "tl;dr"],
        "route": "search",
    },
    # ── Live Data (checked after business) ──────────────────────────
    "weather": {
        "keywords": ["weather", "forecast", "temperature", "rain", "snow", "humidity", "wind"],
        "route": "weather",
    },
    "news": {
        "keywords": ["news", "headline", "headlines", "breaking", "current events", "top stories"],
        "route": "news",
    },
    "sports_live_data": {
        "keywords": ["game today", "score", "scores", "match", "standings", "nba", "nfl", "mlb", "nhl", "timberwolves"],
        "route": "search",
    },
    "finance": {
        "keywords": ["stock", "stocks", "market", "price", "earnings", "nasdaq", "dow", "s&p"],
        "route": "search",
    },
    "live_lookup": {
        "keywords": ["latest", "live", "current", "today", "right now", "realtime", "real-time"],
        "route": "search",
    },
}

# ── Capability registry ────────────────────────────────────────────────────
# Each entry: triggers (list of lowercase keywords), handler function,
# and whether the module benefits from conversation history.
#
# To add a new capability:
#   1. Create backend/app/modules/<name>.py with TRIGGERS and handle()
#   2. Add one entry here — that's it.
#
CAPABILITIES = { # type: ignore
    "weather": {
        "triggers": weather.TRIGGERS,
        "handler": weather.handle, # type: ignore
        "needs_history": False,
        "permission": "weather.read",
        "live": True,
    },
    "time": {
        "triggers": time_module.TRIGGERS,
        "handler": time_module.handle, # type: ignore
        "needs_history": False,
        "permission": "time.read",
        "live": True,
    },
    "news": {
        "triggers": news.TRIGGERS,
        "handler": news.handle, # type: ignore
        "needs_history": False,
        "permission": "search.read",
        "live": True,
    },
    "search": {
        "triggers": search.TRIGGERS,
        "handler": search.handle, # type: ignore
        "needs_history": False,
        "permission": "search.read",
        "live": True,
    },
    "email": {
        "triggers": email.TRIGGERS,
        "handler": email.handle, # type: ignore
        "needs_history": True,
        "permission": "email.compose",
        "live": True,
    },
    "business":  {"triggers": business.TRIGGERS,   "handler": business.handle,   "needs_history": True, "permission": "business.advice", "live": True}, # type: ignore
    "education": {"triggers": education.TRIGGERS,  "handler": education.handle,  "needs_history": True, "permission": "education.tutor", "live": True}, # type: ignore
}


def _memory_context(user_id: str) -> list: # type: ignore
    summary = get_memory_summary(user_id)
    preferences = get_preferences(user_id) # type: ignore
    parts = [MEMORY_IDENTITY_RULE]
    if summary:
        parts.append(f"Conversation summary: {summary}")
    if preferences:
        pref_text = ", ".join(f"{key}={value}" for key, value in preferences.items()) # type: ignore
        parts.append(f"Known preferences: {pref_text}")
    return [{"role": "system", "content": "\n".join(parts)}] # type: ignore


def _has_durable_memory(user_id: str) -> bool:
    return bool(get_memory_summary(user_id) or get_preferences(user_id)) # type: ignore


def _enforce_memory_identity_response(response_text: str, *, has_memory: bool, memory_enabled: bool = True) -> str:
    text = (response_text or "").strip()
    if not memory_enabled or not text:
        return response_text
    lower = text.lower()
    if any(pattern in lower for pattern in STATELESS_CLAIM_PATTERNS):
        return (
            "I remember what you've shared and will use it to personalize how I help."
            if has_memory
            else "I don't know that yet."
        )
    return response_text


def _detect_memory_capability_intent(message: str) -> dict | None: # type: ignore
    lower = (message or "").strip().lower()
    if not lower or not any(pattern in lower for pattern in MEMORY_SELF_KNOWLEDGE_PATTERNS):
        return None
    return {
        "builder": any(term in lower for term in ("builder", "developer", "memory settings", "consent")),
        "delete_memory": any(term in lower for term in ("delete memory", "clear memory", "wipe memory", "remove memory")),
        "ask_what_known": ("what do you know about me" in lower) or ("what do you remember" in lower),
        "ask_how_remember": "how can you remember" in lower,
        "ask_can_remember": "can you remember" in lower,
        "ask_long_term": ("long-term memory" in lower) or ("long term memory" in lower),
        "ask_short_term": ("short-term memory" in lower) or ("short term memory" in lower),
        "ask_personal": "personal information" in lower,
        "ask_forever": any(term in lower for term in ("forever", "always", "permanent")),
    } # type: ignore


def _describe_known_memory(user_id: str) -> list[str]:
    details: list[str] = []
    summary = get_memory_summary(user_id) or ""
    preferences = get_preferences(user_id) # type: ignore
    if preferences.get("name"): # type: ignore
        details.append(f"your name as {preferences['name']}")
    if preferences.get("preferred_name"): # type: ignore
        details.append(f"the name you prefer as {preferences['preferred_name']}")
    if preferences.get("location"): # type: ignore
        details.append(f"your location as {preferences['location']}")
    if preferences.get("role"): # type: ignore
        details.append(f"your role as {preferences['role']}")
    if preferences.get("industry"): # type: ignore
        details.append(f"your industry as {preferences['industry']}")
    if preferences.get("preference"): # type: ignore
        details.append(f"preferences such as {preferences['preference']}")
    if summary and not details:
        safe_summary = re.sub(r"\buser_id\b", "profile", summary, flags=re.IGNORECASE)
        details.append(f"this stored summary: {safe_summary[:220]}")
    return details


def _build_memory_capability_response(message: str, user_id: str) -> str | None:
    intent = _detect_memory_capability_intent(message) # type: ignore
    if not intent:
        return None

    known_details = _describe_known_memory(user_id)
    has_memory = _has_durable_memory(user_id)

    if intent["builder"]:
        response = (
            "Amicor already has short_term_memory for recent context and long_term_memory for durable user facts. "
            "In the current system, memory persists to your profile, Clear Memory wipes both memory layers, and the memory policy blocks stateless claims from leaking into replies. "
            "Safe builder steps are to add a user memory settings page, add memory review/edit/delete UI, add an explicit consent toggle, expose memory categories to the user, and move to account-based memory ownership. "
            "Advanced semantic or vector memory is not part of the current architecture yet and should stay a later step."
        )
    elif intent["delete_memory"]:
        response = (
            "Use Clear Memory to delete memory. "
            "That wipes both short_term_memory and long_term_memory for your profile, so stored personal details and recent memory context are removed together."
        )
    elif intent["ask_what_known"]:
        response = (
            "From memory I currently know " + ", ".join(known_details) + ". "
            "That information is stored in Amicor's memory runtime for your profile until it is cleared."
            if known_details
            else "I don't know specific personal details about you yet. In Amicor's current memory architecture I can keep recent context in short_term_memory and durable user facts in long_term_memory, both persisted to your profile until cleared."
        )
    elif intent["ask_forever"]:
        response = (
            "I can remember a name as durable long_term_memory for your profile, but not as a forever guarantee. "
            "Memory can be cleared, ownership controls are still being hardened, and advanced semantic or vector memory has not been added yet."
        )
    elif intent["ask_long_term"] or intent["ask_short_term"]:
        response = (
            "Yes. Amicor currently has short_term_memory for recent exchanges and long_term_memory for durable facts and preferences. "
            "Both are persisted to your profile, Clear Memory wipes both, and the memory policy prevents stateless replies from contradicting that behavior."
        )
    else:
        response = (
            "Amicor remembers through short_term_memory for recent context and long_term_memory for durable user facts. "
            "That memory persists to your profile, can be cleared explicitly, and is guarded by a response policy that blocks stateless claims. "
            "Advanced semantic or vector memory is not in the system yet."
        )

    return _enforce_memory_identity_response(response, has_memory=has_memory, memory_enabled=True)


def _extract_preferences(message: str) -> dict: # type: ignore
    import re

    found = {}

    def _capture_after(prefix: str) -> str | None:
        # Match case-insensitively and stop at sentence/newline boundaries.
        pattern = re.compile(rf"{re.escape(prefix)}(.+?)(?:[.!?]\s|\n|$)", re.IGNORECASE)
        match = pattern.search(message)
        if not match:
            return None
        value = match.group(1).strip()
        return value or None

    name = _capture_after("my name is ")
    if name:
        found["name"] = name

    preferred_name = _capture_after("call me ")
    if preferred_name:
        found["preferred_name"] = preferred_name

    location = _capture_after("i live in ")
    if location:
        found["location"] = location

    preference = _capture_after("i prefer ")
    if preference:
        found["preference"] = preference

    industry = _capture_after("i work in ")
    if industry:
        found["industry"] = industry

    role = _capture_after("i am a ")
    if role:
        found["role"] = role

    return found # type: ignore


def _summarize_history(history: list) -> str | None: # type: ignore
    """
    Compress recent conversation history into a memory summary string.
    Uses OpenAI when available for quality compression; falls back to
    extractive heuristic.
    """
    if not history:
        return None

    import os
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key and len(history) >= 4: # type: ignore
        try:
            import importlib
            openai_mod = importlib.import_module("openai")
            client = openai_mod.OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_SECONDS)
            # Build a compact transcript for compression
            transcript_parts = []
            for item in history[-12:]: # type: ignore
                role = "User" if item["role"] == "user" else "Assistant"
                transcript_parts.append(f"{role}: {item['content'][:300]}") # type: ignore
            transcript = "\n".join(transcript_parts) # type: ignore
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=180,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Summarize this conversation fragment in 1-3 concise sentences. "
                            "Focus on: user's goal, key topics, important facts mentioned, "
                            "and any preferences expressed. Be factual and brief."
                        ),
                    },
                    {"role": "user", "content": transcript},
                ],
            )
            summary = (resp.choices[0].message.content or "").strip()
            if summary:
                return summary[:800]
        except Exception:
            pass  # fall through to heuristic

    # Heuristic fallback
    user_points = [item["content"] for item in history if item["role"] == "user"][-3:] # type: ignore
    assistant_points = [item["content"] for item in history if item["role"] == "assistant"][-2:] # type: ignore
    parts = []
    if user_points:
        parts.append("Recent user topics: " + " | ".join(p[:120] for p in user_points)) # type: ignore
    if assistant_points:
        parts.append("Recent assistant help: " + " | ".join(p[:80] for p in assistant_points)) # type: ignore
    return "; ".join(parts)[:800] if parts else None # type: ignore


def _normalize_result(tool_name: str, raw_result, capability: dict) -> dict: # type: ignore
    def _normalize_live_unavailable_text(text: str) -> str:
        normalized = (text or "").strip()
        lower = normalized.lower()
        if any(pattern in lower for pattern in LEGACY_LIVE_UNAVAILABLE_PATTERNS):
            return "Live information is temporarily unavailable right now."
        return normalized

    if isinstance(raw_result, dict):
        response = raw_result.get("response") or raw_result.get("reply") or "No response." # type: ignore
        response = _normalize_live_unavailable_text(response) # type: ignore
        return {
            "tool": tool_name,
            "response": response,
            "sources": raw_result.get("sources", []), # type: ignore
            "status": raw_result.get("status", "success"), # type: ignore
            "capability": {
                "name": tool_name,
                "permission": capability["permission"],
                "live": capability["live"],
            },
            "meta": raw_result.get("meta", {}), # type: ignore
        }
    return {
        "tool": tool_name,
        "response": _normalize_live_unavailable_text(str(raw_result)), # type: ignore
        "sources": [],
        "status": "success",
        "capability": {
            "name": tool_name,
            "permission": capability["permission"],
            "live": capability["live"],
        },
        "meta": {},
    }


def _classify_live_intent(message: str) -> tuple[str, str] | None:
    lower = (message or "").strip().lower()
    if not lower:
        return None
    for intent_name, config in LIVE_INTENT_RULES.items(): # type: ignore
        if any(keyword in lower for keyword in config["keywords"]): # type: ignore
            return config["route"], intent_name # type: ignore
    return None


async def _attempt_tool_execution( # type: ignore
    message: str,
    user_id: str,
    memory_context: str | None = None,
    memory_preferences: dict | None = None # type: ignore
) -> dict | None: # type: ignore
    """
    Attempt to execute a tool if actionable intent is detected.
    
    Returns:
        Tool result dict if execution occurred, None otherwise.
        Safe: Returns None if execution unavailable/skipped.
    """
    try:
        # Check if tools should execute
        should_execute = await _execution_engine.should_execute(message)
        if not should_execute:
            return None
        
        # Execute primary tool
        tool_result = await _execution_engine.execute_primary_tool(
            message=message,
            user_id=user_id,
            memory_context=memory_context,
            memory_preferences=memory_preferences # type: ignore
        )
        
        return tool_result
    
    except Exception as e:
        logger.debug(f"Tool execution attempt failed (safe fallback): {str(e)}")
        return None


def _run_tool_execution_sync( # type: ignore
    message: str,
    user_id: str,
    memory_context: str | None = None,
    memory_preferences: dict | None = None # type: ignore
) -> dict | None: # type: ignore
    """
    Synchronous wrapper for async tool execution.
    Used from sync route_message context.
    """
    try:
        try:
            running_loop = asyncio.get_running_loop()
            loop_is_running = running_loop.is_running()
        except RuntimeError:
            loop_is_running = False

        if not loop_is_running:
            return asyncio.run(
                _attempt_tool_execution(
                    message=message,
                    user_id=user_id,
                    memory_context=memory_context,
                    memory_preferences=memory_preferences,
                ) # type: ignore
            )

        # If we're inside a running event loop (FastAPI async path), run in a worker thread.
        result_queue: queue.Queue = queue.Queue(maxsize=1) # type: ignore

        def _worker() -> None:
            try:
                result = asyncio.run( # type: ignore
                    _attempt_tool_execution(
                        message=message,
                        user_id=user_id,
                        memory_context=memory_context,
                        memory_preferences=memory_preferences,
                    ) # type: ignore
                )
                result_queue.put((True, result)) # type: ignore
            except Exception as worker_exc:
                result_queue.put((False, worker_exc)) # type: ignore

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=4.0)
        if t.is_alive():
            logger.debug("Tool execution worker timed out")
            return None

        ok, payload = result_queue.get_nowait() # type: ignore
        if ok:
            return payload # type: ignore
        logger.debug(f"Tool execution worker failed: {payload}")
        return None
    
    except Exception as e:
        logger.debug(f"Tool execution sync wrapper failed: {str(e)}")
        return None


def route_message(message: str, user_id: str = "default") -> dict: # type: ignore
    lower = message.lower()
    has_memory = _has_durable_memory(user_id)
    history_with_memory = _memory_context(user_id) + get_recent_messages(user_id, limit=10) # type: ignore
    user_preferences = _extract_preferences(message) # type: ignore
    for key, value in user_preferences.items(): # type: ignore
        save_preference(user_id, key, value) # type: ignore

    memory_capability_response = _build_memory_capability_response(message, user_id)
    if memory_capability_response:
        save_message(user_id, "user", message)
        save_message(user_id, "assistant", memory_capability_response)
        summary = _summarize_history(get_recent_messages(user_id, limit=12))
        if summary:
            save_memory_summary(user_id, summary)
        return {
            "tool": "memory",
            "response": memory_capability_response,
            "sources": [],
            "status": "success",
            "capability": {
                "name": "memory",
                "permission": "memory.read",
                "live": True,
            },
            "meta": {"routed": "memory-capability"},
        } # type: ignore

    predicted_route = _classify_live_intent(message)
    predicted_capability = predicted_route[0] if predicted_route else None
    memory_summary = get_memory_summary(user_id)
    memory_preferences = get_preferences(user_id) # type: ignore

    # ── BUSINESS-FIRST ROUTING STRATEGY ──────────────────────────
    # Priority order: predicted_capability → business → productivity → live-data
    # This ensures business prompts never accidentally hit TIME or generic handlers
    ordered_capability_names = list(CAPABILITIES.keys()) # type: ignore
    
    # Build priority-ordered list
    priority_order = [ # type: ignore
        "business",    # Business advisory FIRST
        "education",   # Education assistant
        "email",       # Email drafting
        predicted_capability,  # Predicted intent (if set)
    ]
    
    # Move priority capabilities to front, preserving predicted_capability priority
    reordered = []
    for cap in priority_order: # type: ignore
        if cap and cap in ordered_capability_names and cap not in reordered:
            reordered.append(cap) # type: ignore
    
    # Add remaining capabilities (weather, news, search, time, etc.)
    for cap in ordered_capability_names:
        if cap not in reordered:
            reordered.append(cap) # type: ignore
    
    ordered_capability_names = reordered

    for name in ordered_capability_names: # type: ignore
        cap = CAPABILITIES[name] # type: ignore
        trigger_match = any(t in lower for t in cap["triggers"]) # type: ignore
        predicted_match = predicted_capability == name # type: ignore
        
        # Guard: Skip if this is TIME and we haven't explicitly asked for time
        if name == "time" and not trigger_match:
            continue
        
        if trigger_match or predicted_match:
            history = history_with_memory if cap["needs_history"] else None # type: ignore
            provider_t0 = time.perf_counter()
            logging_utils.log_request_lifecycle(
                logger,
                logging.INFO,
                event="REQUEST_PROVIDER_BEGIN",
                route="/api/chat",
                provider=name, # type: ignore
                status="begin",
            )
            try:
                response = cap["handler"](message, history=history, user_id=user_id) # type: ignore
            except Exception as exc:
                provider_latency_ms = int((time.perf_counter() - provider_t0) * 1000)
                err_msg = logging_utils.safe_exception_message(exc).lower()
                if "timed out" in err_msg or isinstance(exc, TimeoutError):
                    logging_utils.log_request_lifecycle(
                        logger,
                        logging.ERROR,
                        event="REQUEST_TIMEOUT",
                        route="/api/chat",
                        latency_ms=provider_latency_ms,
                        provider=name, # type: ignore
                        status="timeout",
                        error=err_msg,
                    )
                logging_utils.log_request_lifecycle(
                    logger,
                    logging.ERROR,
                    event="REQUEST_PROVIDER_FAIL",
                    route="/api/chat",
                    latency_ms=provider_latency_ms,
                    provider=name, # type: ignore
                    status="failed",
                    error=err_msg,
                )
                raise
            provider_latency_ms = int((time.perf_counter() - provider_t0) * 1000)
            logging_utils.log_request_lifecycle(
                logger,
                logging.INFO,
                event="REQUEST_PROVIDER_SUCCESS",
                route="/api/chat",
                latency_ms=provider_latency_ms,
                provider=name, # type: ignore
                status="ok",
            )
            result = _normalize_result(name, response, cap) # type: ignore
            if predicted_route and predicted_match:
                result.setdefault("meta", {}) # type: ignore
                result["meta"]["intent"] = predicted_route[1]
            result = apply_response_engine(
                message=message,
                result=result, # type: ignore
                preferences=memory_preferences, # type: ignore
                memory_summary=memory_summary,
            )
            
            # Attempt tool execution (safe: returns original response if fails)
            tool_result = _run_tool_execution_sync( # type: ignore
                message=message,
                user_id=user_id,
                memory_context=history_with_memory, # type: ignore
                memory_preferences=memory_preferences
            )
            if tool_result and tool_result.get('success'): # type: ignore
                result.setdefault("meta", {})
                result["meta"]["tool_executed"] = True
                result["meta"]["tool_id"] = tool_result.get('tool_id') # type: ignore
                tool_data = tool_result.get('data') or {} # type: ignore
                if isinstance(tool_data, dict):
                    if tool_data.get('card'): # type: ignore
                        result["meta"]["tool_card"] = tool_data.get('card') # type: ignore
                    if tool_data.get('browser_actions'): # type: ignore
                        result["meta"]["browser_actions"] = tool_data.get('browser_actions') # type: ignore
                    if tool_data.get('workflow_steps'): # type: ignore
                        result["meta"]["workflow_steps"] = tool_data.get('workflow_steps') # type: ignore
            
            result["response"] = _enforce_memory_identity_response(
                result.get("response", ""),
                has_memory=has_memory,
                memory_enabled=True,
            )
            save_message(user_id, "user", message)
            save_message(user_id, "assistant", result["response"])
            summary = _summarize_history(get_recent_messages(user_id, limit=12))
            if summary:
                save_memory_summary(user_id, summary)
            return result

    # ── OpenAI fallback — always includes conversation history ────────────
    history = history_with_memory # type: ignore
    save_message(user_id, "user", message)
    provider_t0 = time.perf_counter()
    logging_utils.log_request_lifecycle(
        logger,
        logging.INFO,
        event="REQUEST_PROVIDER_BEGIN",
        route="/api/chat",
        provider="openai",
        status="begin",
    )
    try:
        response = ask_openai(message, history=history)
    except Exception as exc:
        provider_latency_ms = int((time.perf_counter() - provider_t0) * 1000)
        err_msg = logging_utils.safe_exception_message(exc).lower()
        if "timed out" in err_msg or isinstance(exc, TimeoutError):
            logging_utils.log_request_lifecycle(
                logger,
                logging.ERROR,
                event="REQUEST_TIMEOUT",
                route="/api/chat",
                latency_ms=provider_latency_ms,
                provider="openai",
                status="timeout",
                error=err_msg,
            )
        logging_utils.log_request_lifecycle(
            logger,
            logging.ERROR,
            event="REQUEST_PROVIDER_FAIL",
            route="/api/chat",
            latency_ms=provider_latency_ms,
            provider="openai",
            status="failed",
            error=err_msg,
        )
        raise
    provider_latency_ms = int((time.perf_counter() - provider_t0) * 1000)
    logging_utils.log_request_lifecycle(
        logger,
        logging.INFO,
        event="REQUEST_PROVIDER_SUCCESS",
        route="/api/chat",
        latency_ms=provider_latency_ms,
        provider="openai",
        status="ok",
    )
    normalized_openai_response = response
    for pattern in LEGACY_LIVE_UNAVAILABLE_PATTERNS:
        if pattern in normalized_openai_response.lower():
            normalized_openai_response = "Live information is temporarily unavailable right now."
            break
    fallback_result = { # type: ignore
        "tool": "openai",
        "response": normalized_openai_response,
        "sources": [],
        "status": "success",
        "capability": {"name": "openai", "permission": "assistant.chat", "live": True},
        "meta": {},
    }
    fallback_result = apply_response_engine(
        message=message,
        result=fallback_result, # type: ignore
        preferences=memory_preferences, # type: ignore
        memory_summary=memory_summary,
    )
    
    # Attempt tool execution (safe: returns original response if fails)
    tool_result = _run_tool_execution_sync( # type: ignore
        message=message,
        user_id=user_id,
        memory_context=history_with_memory, # type: ignore
        memory_preferences=memory_preferences
    )
    if tool_result and tool_result.get('success'): # type: ignore
        fallback_result.setdefault("meta", {})
        fallback_result["meta"]["tool_executed"] = True
        fallback_result["meta"]["tool_id"] = tool_result.get('tool_id') # type: ignore
        tool_data = tool_result.get('data') or {} # type: ignore
        if isinstance(tool_data, dict):
            if tool_data.get('card'): # type: ignore
                fallback_result["meta"]["tool_card"] = tool_data.get('card') # type: ignore
            if tool_data.get('browser_actions'): # type: ignore
                fallback_result["meta"]["browser_actions"] = tool_data.get('browser_actions') # type: ignore
            if tool_data.get('workflow_steps'): # type: ignore
                fallback_result["meta"]["workflow_steps"] = tool_data.get('workflow_steps') # type: ignore
    
    response = _enforce_memory_identity_response(
        fallback_result.get("response", normalized_openai_response),
        has_memory=has_memory,
        memory_enabled=True,
    )
    save_message(user_id, "assistant", response)
    summary = _summarize_history(get_recent_messages(user_id, limit=12))
    if summary:
        save_memory_summary(user_id, summary)
    fallback_result["response"] = response
    return fallback_result
