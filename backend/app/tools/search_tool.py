from app.web_search import search_web  # type: ignore

def handle_search(message: str) -> str:
    return search_web(message)
