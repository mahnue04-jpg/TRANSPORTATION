import html
import os
import re
from datetime import datetime, UTC
from xml.etree import ElementTree
from urllib.parse import parse_qs, quote_plus, urlparse

import requests


def _clean_text(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", html.unescape(value or "")).strip()
    return cleaned


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
    provider_errors = []
    payload = None
    providers = [_tavily_search]
    if news_mode:
        providers.extend([_google_news_search, _duckduckgo_search])
    else:
        providers.extend([_duckduckgo_search, _wikipedia_search])
    for provider in providers:
        try:
            payload = provider(normalized_query, max_results)
            if payload and payload.get("results"):
                break
        except Exception as exc:
            provider_errors.append(f"{provider.__name__}: {exc}")
    if not payload or not payload.get("results"):
        detail = "; ".join(provider_errors) if provider_errors else "No search provider returned results."
        return {
            "response": f"Search is temporarily unavailable. {detail}",
            "sources": [],
            "status": "error",
            "meta": {"provider_errors": provider_errors},
        }

    results = payload.get("results", [])
    sources = [
        {"title": item["title"], "url": item["url"], "label": urlparse(item["url"]).netloc or item["url"]}
        for item in results[:4]
    ]
    response = _summarize_results(normalized_query, results, payload.get("answer", ""))
    return {
        "response": response,
        "sources": sources,
        "status": "success",
        "meta": {
            "provider": payload.get("provider", "unknown"),
            "result_count": len(results),
            "query": normalized_query,
        },
    }
