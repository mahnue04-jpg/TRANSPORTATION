"""News capability module — uses web search with a news-focused query."""
from app.web_search import search_web

TRIGGERS = ["news", "headline", "what happened"]


def handle(message: str, history: list = None) -> str:
    query = message.strip() or "latest news today"
    return search_web(query)
