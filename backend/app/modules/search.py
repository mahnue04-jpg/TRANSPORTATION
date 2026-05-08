"""Web search capability module."""
from app.web_search import search_web

TRIGGERS = ["search", "look up", "find", "latest"]


def handle(message: str, history: list = None) -> str:
    return search_web(message)
