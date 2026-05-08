import os
import requests


def search_web(query: str) -> str:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "Web search unavailable (missing API key)."

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": 3,
                "include_answer": True,
            },
            timeout=10,
        )
        data = response.json()

        if data.get("answer"):
            return data["answer"]

        results = data.get("results", [])
        if not results:
            return "No results found."

        snippets = [r.get("content", "") for r in results[:3] if r.get("content")]
        return " ".join(snippets)[:1000]

    except Exception as e:
        return f"Web search error: {str(e)}"
