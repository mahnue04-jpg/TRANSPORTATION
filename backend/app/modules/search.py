"""Web search capability module."""
from app.web_search import search_web

TRIGGERS = ["search", "look up", "find", "latest"]


def _query_from_message(message: str) -> str:
    lowered = message.lower()
    for token in ["search for", "search", "look up", "find", "latest", "please"]:
        lowered = lowered.replace(token, " ")
    query = " ".join(lowered.split()).strip(" ?!.,")
    return query or message.strip()


def handle(message: str, history: list = None, user_id: str = "default") -> dict:
    return search_web(_query_from_message(message))
