import html
import hashlib
import json
import os
import re
import time
from datetime import datetime, UTC
from typing import Any
from xml.etree import ElementTree
from urllib.parse import parse_qs, quote_plus, urlparse

import requests

from app.providers.resilience import get_breaker, resilient_call, RetryBudget  # type: ignore

_CACHE_TTL_S = int(os.getenv("SEARCH_CACHE_TTL", "300"))
_SEARCH_CACHE: dict[str, tuple[float, dict]] = {}
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


def _cache_key(query: str, max_results: int, news_mode: bool) -> str:
    raw = f"{query.strip().lower()}|{max_results}|{1 if news_mode else 0}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict | None:
    entry = _SEARCH_CACHE.get(key)
    if not entry:
        _SEARCH_DIAGNOSTICS["cache_misses"] += 1
        return None
    expires_at, payload = entry
    if expires_at < time.time():
        _SEARCH_CACHE.pop(key, None)
        _SEARCH_DIAGNOSTICS["cache_misses"] += 1
        return None
    _SEARCH_DIAGNOSTICS["cache_hits"] += 1
    return json.loads(json.dumps(payload))


def _cache_put(key: str, payload: dict) -> None:
    _SEARCH_CACHE[key] = (time.time() + _CACHE_TTL_S, json.loads(json.dumps(payload)))


def _diag_count(bucket: str, key: str) -> None:
    store = _SEARCH_DIAGNOSTICS[bucket]
    store[key] = int(store.get(key, 0)) + 1


def get_search_diagnostics() -> dict:
    last = _SEARCH_DIAGNOSTICS["last_queries"][-20:]
    return {
        "cache": {
            "size": len(_SEARCH_CACHE),
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


def _extract_ddg_results(markup: str, limit: int = 5) -> list[dict]:
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
        parsed = urlparse(href)
        final_url = href
        if parsed.path == "/l/":
            uddg = parse_qs(parsed.query).get("uddg")
            if uddg:
                final_url = uddg[0]
        results.append(
            {
                "title": _clean_text(re.sub(r"<[^>]+>", " ", title_html)),
                "url": final_url,
                "snippet": _clean_text(re.sub(r"<[^>]+>", " ", snippet_html)),
            }
        )
    return [item for item in results if item["title"] and item["url"]]


def _tavily_search(query: str, max_results: int) -> dict | None:
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
        timeout=(3.05, 12),
    )
    response.raise_for_status()
    payload = response.json()
    results = [
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
    }


def _duckduckgo_search(query: str, max_results: int) -> dict:
    response = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Amicor/1.0; +https://amicor.local)"
        },
        timeout=(3.05, 10),
    )
    response.raise_for_status()
    return {
        "provider": "duckduckgo",
        "answer": "",
        "results": _extract_ddg_results(response.text, limit=max_results),
    }


def _google_news_search(query: str, max_results: int) -> dict:
    response = requests.get(
        "https://news.google.com/rss/search",
        params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        timeout=(3.05, 10),
        headers={"User-Agent": "Amicor/1.0 search client"},
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.text)
    items = []
    for item in root.findall(".//item")[:max_results]:
        items.append(
            {
                "title": _clean_text(item.findtext("title", default="News result")),
                "url": _clean_text(item.findtext("link", default="")),
                "snippet": _clean_text(item.findtext("description", default="")),
            }
        )
    return {"provider": "google-news-rss", "answer": "", "results": items}


def _wikipedia_search(query: str, max_results: int) -> dict:
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
        timeout=(3.05, 10),
        headers={"User-Agent": "Amicor/1.0 search client"},
    )
    response.raise_for_status()
    payload = response.json()
    results = []
    for item in payload.get("query", {}).get("search", [])[:max_results]:
        title = _clean_text(item.get("title", "Wikipedia"))
        results.append(
            {
                "title": title,
                "url": f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}",
                "snippet": _clean_text(re.sub(r"<[^>]+>", " ", item.get("snippet", ""))),
            }
        )
    return {"provider": "wikipedia", "answer": "", "results": results}


def _summarize_results(query: str, results: list[dict], answer: str = "") -> str:
    lines = []
    if answer:
        lines.append(answer)
    if results:
        lines.append(f"Search results for '{query}':")
        for index, item in enumerate(results[:4], start=1):
            snippet = item.get("snippet") or "No summary available."
            lines.append(f"{index}. {item['title']}: {snippet}")
    return "\n".join(lines)[:1800]


def search_web(query: str, max_results: int = 4, news_mode: bool = False) -> dict:
    normalized_query = query.strip()
    if news_mode:
        today = datetime.now(UTC).strftime("%B %d, %Y")
        normalized_query = f"{normalized_query} latest news {today}".strip()

    cache_key = _cache_key(normalized_query, max_results, news_mode)
    cached = _cache_get(cache_key)
    if cached:
        cached.setdefault("meta", {})
        cached["meta"]["cache_hit"] = True
        return cached

    _SEARCH_DIAGNOSTICS["last_queries"].append(
        {
            "query": normalized_query[:180],
            "news_mode": news_mode,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )

    # ── Build provider chain with circuit breakers ─────────────────────────
    if news_mode:
        provider_chain = [
            ("tavily",       get_breaker("tavily", failure_threshold=3, recovery_timeout=30),       lambda q, n: _tavily_search(q, n)),
            ("google-news",  get_breaker("google_news", failure_threshold=3, recovery_timeout=60),  lambda q, n: _google_news_search(q, n)),
            ("duckduckgo",   get_breaker("duckduckgo", failure_threshold=4, recovery_timeout=20),   lambda q, n: _duckduckgo_search(q, n)),
        ]
    else:
        provider_chain = [
            ("tavily",       get_breaker("tavily", failure_threshold=3, recovery_timeout=30),       lambda q, n: _tavily_search(q, n)),
            ("duckduckgo",   get_breaker("duckduckgo", failure_threshold=4, recovery_timeout=20),   lambda q, n: _duckduckgo_search(q, n)),
            ("wikipedia",    get_breaker("wikipedia", failure_threshold=5, recovery_timeout=60),    lambda q, n: _wikipedia_search(q, n)),
        ]

    used_provider = "unknown"
    payload = None
    provider_errors: list[str] = []
    provider_latency_ms: dict[str, int] = {}

    for pname, breaker, fn in provider_chain:
        if not breaker.is_available():
            provider_errors.append(f"{pname}: circuit open (health={breaker.health_score:.2f})")
            continue
        try:
            _diag_count("provider_calls", pname)
            t0 = time.perf_counter()
            result = fn(normalized_query, max_results)
            provider_latency_ms[pname] = int((time.perf_counter() - t0) * 1000)
            if result and result.get("results"):
                breaker.record_success()
                payload = result
                used_provider = pname
                break
            else:
                breaker.record_failure()
                _diag_count("provider_failures", pname)
                provider_errors.append(f"{pname}: empty results")
        except Exception as exc:
            breaker.record_failure()
            _diag_count("provider_failures", pname)
            provider_errors.append(f"{pname}: {exc}")

    if not payload or not payload.get("results"):
        detail = "; ".join(provider_errors) if provider_errors else "No search provider returned results."
        return {
            "response": f"Search is temporarily unavailable. {detail}",
            "sources": [],
            "status": "error",
            "meta": {
                "provider_errors": provider_errors,
                "provider": "none",
            },
        }

    results = payload.get("results", [])
    sources = [
        {"title": item["title"], "url": item["url"], "label": urlparse(item["url"]).netloc or item["url"]}
        for item in results[:4]
    ]
    response = _summarize_results(normalized_query, results, payload.get("answer", ""))
    status = "partial" if provider_errors else "success"
    if provider_errors:
        _SEARCH_DIAGNOSTICS["fallback_events"] += 1

    final_payload = {
        "response": response,
        "sources": sources,
        "status": status,
        "meta": {
            "provider": used_provider,
            "result_count": len(results),
            "query": normalized_query,
            "fallback_used": bool(provider_errors),
            "provider_errors": provider_errors if provider_errors else [],
            "provider_latency_ms": provider_latency_ms,
            "cache_hit": False,
        },
    }
    _cache_put(cache_key, final_payload)
    return final_payload
