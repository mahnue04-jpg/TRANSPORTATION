import html
import hashlib
import json
import os
import re
import time
import logging
from datetime import datetime, UTC
from typing import Any
from xml.etree import ElementTree
from urllib.parse import parse_qs, quote_plus, urlparse

import requests

from app.providers.resilience import get_breaker
from app import logging_utils

_CACHE_TTL_S = int(os.getenv("SEARCH_CACHE_TTL", "300"))
PROVIDER_TIMEOUT_SECONDS = 15
logger = logging.getLogger("amicor.web_search")
_SEARCH_CACHE: dict[str, tuple[float, dict]] = {} # type: ignore
_SEARCH_DIAGNOSTICS: dict[str, Any] = {
    "cache_hits": 0,
    "cache_misses": 0,
    "provider_calls": {},
    "provider_failures": {},
    "fallback_events": 0,
    "last_queries": [],
}


def _clean_text(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", html.unescape(value or "")).strip()
    return cleaned


def _sanitize_query_text(value: str) -> str:
    text = value or ""
    text = re.sub(r"\[MEMORY_CONTEXT\].*?\[/MEMORY_CONTEXT\]", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\[(?:SYSTEM|INTERNAL|ROUTE|TOOL|PROVIDER)_[A-Z_]+\]", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:short_term_memory|long_term_memory|user_id|memory_context)\b\s*[:=]\s*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:short_term_memory|long_term_memory|user_id|memory_context)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _cache_key(query: str, max_results: int, news_mode: bool) -> str:
    raw = f"{query.strip().lower()}|{max_results}|{1 if news_mode else 0}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict | None: # type: ignore
    entry = _SEARCH_CACHE.get(key) # type: ignore
    if not entry:
        _SEARCH_DIAGNOSTICS["cache_misses"] += 1
        return None
    expires_at, payload = entry # type: ignore
    if expires_at < time.time():
        _SEARCH_CACHE.pop(key, None) # type: ignore
        _SEARCH_DIAGNOSTICS["cache_misses"] += 1
        return None
    _SEARCH_DIAGNOSTICS["cache_hits"] += 1
    return json.loads(json.dumps(payload))


def _cache_put(key: str, payload: dict) -> None: # type: ignore
    _SEARCH_CACHE[key] = (time.time() + _CACHE_TTL_S, json.loads(json.dumps(payload)))


def _diag_count(bucket: str, key: str) -> None:
    store = _SEARCH_DIAGNOSTICS[bucket]
    store[key] = int(store.get(key, 0)) + 1


def get_search_diagnostics() -> dict: # type: ignore
    last = _SEARCH_DIAGNOSTICS["last_queries"][-20:]
    return {
        "cache": {
            "size": len(_SEARCH_CACHE), # type: ignore
            "ttl_seconds": _CACHE_TTL_S,
            "hits": _SEARCH_DIAGNOSTICS["cache_hits"],
            "misses": _SEARCH_DIAGNOSTICS["cache_misses"],
        },
        "providers": {
            "calls": dict(_SEARCH_DIAGNOSTICS["provider_calls"]),
            "failures": dict(_SEARCH_DIAGNOSTICS["provider_failures"]),
            "fallback_events": _SEARCH_DIAGNOSTICS["fallback_events"],
        },
        "last_queries": list(last),
    }


def _extract_ddg_results(markup: str, limit: int = 5) -> list[dict]: # type: ignore
    anchors = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(.*?)</div>',
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    )
    results = []
    for index, (href, title_html) in enumerate(anchors[:limit]):
        snippet_html = ""
        if index < len(snippets):
            snippet_html = snippets[index][0] or snippets[index][1]
        parsed = urlparse(href) # type: ignore
        final_url = href
        if parsed.path == "/l/": # type: ignore
            uddg = parse_qs(parsed.query).get("uddg") # type: ignore
            if uddg:
                final_url = uddg[0] # type: ignore
        results.append( # type: ignore
            {
                "title": _clean_text(re.sub(r"<[^>]+>", " ", title_html)),
                "url": final_url,
                "snippet": _clean_text(re.sub(r"<[^>]+>", " ", snippet_html)),
            }
        )
    return [item for item in results if item["title"] and item["url"]] # type: ignore


def _tavily_search(query: str, max_results: int) -> dict | None: # type: ignore
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return None
    response = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": True,
        },
        timeout=PROVIDER_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    results = [ # type: ignore
        {
            "title": item.get("title") or item.get("url", "Result"),
            "url": item.get("url", ""),
            "snippet": _clean_text(item.get("content", "")),
        }
        for item in payload.get("results", [])[:max_results]
        if item.get("url")
    ]
    return {
        "provider": "tavily",
        "answer": _clean_text(payload.get("answer", "")),
        "results": results,
    } # pyright: ignore[reportUnknownVariableType]


def _duckduckgo_search(query: str, max_results: int) -> dict: # pyright: ignore[reportMissingTypeArgument, reportUnknownParameterType]
    response = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Amicor/1.0; +https://amicor.local)"
        },
        timeout=PROVIDER_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return {
        "provider": "duckduckgo",
        "answer": "",
        "results": _extract_ddg_results(response.text, limit=max_results),
    } # pyright: ignore[reportUnknownVariableType]


def _google_news_search(query: str, max_results: int) -> dict: # pyright: ignore[reportMissingTypeArgument, reportUnknownParameterType]
    response = requests.get(
        "https://news.google.com/rss/search",
        params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        timeout=PROVIDER_TIMEOUT_SECONDS,
        headers={"User-Agent": "Amicor/1.0 search client"},
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.text)
    items = []
    for item in root.findall(".//item")[:max_results]:
        items.append( # type: ignore
            {
                "title": _clean_text(item.findtext("title", default="News result")),
                "url": _clean_text(item.findtext("link", default="")),
                "snippet": _clean_text(item.findtext("description", default="")),
            }
        )
    return {"provider": "google-news-rss", "answer": "", "results": items} # type: ignore


def _wikipedia_search(query: str, max_results: int) -> dict: # type: ignore
    response = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "utf8": 1,
            "format": "json",
            "srlimit": max_results,
        },
        timeout=PROVIDER_TIMEOUT_SECONDS,
        headers={"User-Agent": "Amicor/1.0 search client"},
    )
    response.raise_for_status()
    payload = response.json()
    results = []
    for item in payload.get("query", {}).get("search", [])[:max_results]:
        title = _clean_text(item.get("title", "Wikipedia"))
        results.append( # type: ignore
            {
                "title": title,
                "url": f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}",
                "snippet": _clean_text(re.sub(r"<[^>]+>", " ", item.get("snippet", ""))),
            }
        )
    return {"provider": "wikipedia", "answer": "", "results": results} # type: ignore


def _summarize_results(query: str, results: list[dict], answer: str = "") -> str: # type: ignore
    lines = []
    if answer:
        lines.append(answer) # type: ignore
    if results:
        lines.append(f"Search results for '{query}':") # type: ignore
        for index, item in enumerate(results[:4], start=1): # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            snippet = item.get("snippet") or "No summary available." # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
            lines.append(f"{index}. {item['title']}: {snippet}") # pyright: ignore[reportUnknownMemberType]
    return "\n".join(lines)[:1800] # pyright: ignore[reportUnknownArgumentType]


def _fallback_response(*, news_mode: bool) -> str:
    if news_mode:
        return "I couldn't fetch live news right now. Please try again in a moment or check Reuters, Bloomberg, CNBC, or Google News."
    return "I couldn't fetch live search results right now. Please try again in a moment."


def search_web(query: str, max_results: int = 4, news_mode: bool = False) -> dict: # type: ignore
    normalized_query = _sanitize_query_text(query)
    if news_mode:
        today = datetime.now(UTC).strftime("%B %d, %Y")
        normalized_query = f"{normalized_query} latest news {today}".strip()

    cache_key = _cache_key(normalized_query, max_results, news_mode)
    cached = _cache_get(cache_key) # pyright: ignore[reportUnknownVariableType]
    if cached:
        cached.setdefault("meta", {}) # type: ignore
        cached["meta"]["cache_hit"] = True
        return cached # pyright: ignore[reportUnknownVariableType]

    _SEARCH_DIAGNOSTICS["last_queries"].append(
        {
            "query": normalized_query[:180],
            "news_mode": news_mode,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )

    # ── Build provider chain with circuit breakers ─────────────────────────
    if news_mode:
        provider_chain = [ # type: ignore
            (
                "tavily",
                get_breaker(
                    "tavily",
                    failure_threshold=3,
                    recovery_timeout=30,
                ),
                lambda q, n: _tavily_search(q, n), # type: ignore
            ),
            (
                "google_news",
                get_breaker(
                    "google_news",
                    failure_threshold=3,
                    recovery_timeout=60,
                ),
                lambda q, n: _google_news_search(q, n), # pyright: ignore[reportUnknownLambdaType] # type: ignore
            ),
            (
                "duckduckgo",
                get_breaker(
                    "duckduckgo",
                    failure_threshold=4,
                    recovery_timeout=20,
                ),
                lambda q, n: _duckduckgo_search(q, n), # pyright: ignore[reportUnknownLambdaType] # type: ignore
            ),
        ]
    else:
        provider_chain = [ # pyright: ignore[reportUnknownVariableType]
            (
                "tavily",
                get_breaker(
                    "tavily",
                    failure_threshold=3,
                    recovery_timeout=30,
                ),
                lambda q, n: _tavily_search(q, n), # type: ignore
            ),
            (
                "duckduckgo",
                get_breaker(
                    "duckduckgo",
                    failure_threshold=4,
                    recovery_timeout=20,
                ),
                lambda q, n: _duckduckgo_search(q, n), # type: ignore
            ),
            (
                "wikipedia",
                get_breaker(
                    "wikipedia",
                    failure_threshold=5,
                    recovery_timeout=60,
                ),
                lambda q, n: _wikipedia_search(q, n), # type: ignore
            ),
        ]

    used_provider = "unknown"
    payload = None
    provider_errors: list[str] = []
    provider_latency_ms: dict[str, int] = {}

    for pname, breaker, fn in provider_chain: # type: ignore
        if not breaker.is_available(): # type: ignore
            provider_errors.append(f"{pname}: circuit open (health={breaker.health_score:.2f})") # type: ignore
            continue
        logging_utils.log_request_lifecycle(
            logger,
            logging.INFO,
            event="REQUEST_PROVIDER_BEGIN",
            route="/api/chat",
            provider=pname, # type: ignore
            status="begin",
        )
        try:
            _diag_count("provider_calls", pname) # type: ignore
            t0 = time.perf_counter()
            result = fn(normalized_query, max_results) # type: ignore
            provider_latency_ms[pname] = int((time.perf_counter() - t0) * 1000)
            if result and result.get("results"): # type: ignore
                breaker.record_success() # type: ignore
                logging_utils.log_request_lifecycle(
                    logger,
                    logging.INFO,
                    event="REQUEST_PROVIDER_SUCCESS",
                    route="/api/chat",
                    latency_ms=provider_latency_ms[pname],
                    provider=pname, # type: ignore
                    status="ok",
                )
                payload = result # type: ignore
                used_provider = pname # type: ignore
                break
            else:
                breaker.record_failure() # type: ignore
                _diag_count("provider_failures", pname) # type: ignore
                logging_utils.log_request_lifecycle(
                    logger,
                    logging.ERROR,
                    event="REQUEST_PROVIDER_FAIL",
                    route="/api/chat",
                    latency_ms=provider_latency_ms[pname],
                    provider=pname, # type: ignore
                    status="empty",
                    error="empty results",
                )
                provider_errors.append(f"{pname}: empty results")
        except Exception as exc:
            breaker.record_failure() # type: ignore
            _diag_count("provider_failures", pname) # type: ignore
            latency_ms = int((time.perf_counter() - t0) * 1000) # type: ignore
            err_msg = logging_utils.safe_exception_message(exc)
            if "timed out" in err_msg.lower() or isinstance(exc, requests.exceptions.Timeout):
                logging_utils.log_request_lifecycle(
                    logger,
                    logging.ERROR,
                    event="REQUEST_TIMEOUT",
                    route="/api/chat",
                    latency_ms=latency_ms,
                    provider=pname, # type: ignore
                    status="timeout",
                    error=err_msg,
                )
            logging_utils.log_request_lifecycle(
                logger,
                logging.ERROR,
                event="REQUEST_PROVIDER_FAIL",
                route="/api/chat",
                latency_ms=latency_ms,
                provider=pname, # type: ignore
                status="failed",
                error=err_msg,
            )
            provider_errors.append(f"{pname}: {exc}")

    if not payload or not payload.get("results"): # type: ignore
        # Log provider errors internally only — never expose to user
        if provider_errors:
            logger.warning(
                "SEARCH_PROVIDER_CHAIN_EXHAUSTED",
                extra={"errors": provider_errors, "query": normalized_query[:180]}
            )
        # User-facing fallback: graceful and conversational
        return {
            "response": _fallback_response(news_mode=news_mode),
            "sources": [],
            "status": "degraded",
            "meta": {
                "query": normalized_query,
                "search_available": False,
                # Provider errors stored internally only — not exposed to user
            },
        } # pyright: ignore[reportUnknownVariableType]

    results = payload.get("results", []) # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    sources = [ # type: ignore
        {"title": item["title"], "url": item["url"], "label": urlparse(item["url"]).netloc or item["url"]} # type: ignore
        for item in results[:4] # type: ignore
    ]
    response = _summarize_results(normalized_query, results, payload.get("answer", "")) # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    status = "partial" if provider_errors else "success"
    if provider_errors:
        _SEARCH_DIAGNOSTICS["fallback_events"] += 1
        # Log fallback event internally with provider details
        logger.info(
            "SEARCH_PROVIDER_FALLBACK",
            extra={
                "primary_provider_failed": provider_errors[0] if provider_errors else None,
                "fallback_provider": used_provider,
                "result_count": len(results), # pyright: ignore[reportUnknownArgumentType]
            } # pyright: ignore[reportUnknownArgumentType]
        )

    # Clean meta: exclude provider errors from user-facing response
    final_payload = { # pyright: ignore[reportUnknownVariableType]
        "response": response,
        "sources": sources,
        "status": status,
        "meta": {
            "provider": used_provider,
            "result_count": len(results), # type: ignore
            "query": normalized_query,
            "cache_hit": False,
            # Provider latency and errors intentionally omitted from user-facing meta
        },
    }
    _cache_put(cache_key, final_payload)
    return final_payload # type: ignore
