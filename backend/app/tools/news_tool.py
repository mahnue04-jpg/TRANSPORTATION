from app.web_search import search_web  # type: ignore

def handle_news(message: str) -> str:
    query = message if message.strip() else "latest news today"
    return search_web(query, news_mode=True)
