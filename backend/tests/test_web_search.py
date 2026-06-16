import unittest
from unittest.mock import patch

from app.web_search import _fallback_response, _sanitize_query_text, search_web


class _FakeBreaker:
    def __init__(self, available: bool = True, health_score: float = 1.0) -> None:
        self._available = available
        self.health_score = health_score

    def is_available(self) -> bool:
        return self._available

    def record_success(self) -> None:
        return None

    def record_failure(self) -> None:
        return None


class WebSearchQuerySanitizationTests(unittest.TestCase):
    def test_sanitize_query_text_removes_memory_context_wrapper(self) -> None:
        raw = "[MEMORY_CONTEXT]\nshort_term_memory=Search the latest headlines\n[/MEMORY_CONTEXT]\n\nSearch the latest headlines"
        self.assertEqual(_sanitize_query_text(raw), "Search the latest headlines")

    def test_sanitize_query_text_removes_internal_labels(self) -> None:
        raw = "search latest news user_id=abc123 memory_context=whatever"
        self.assertEqual(_sanitize_query_text(raw), "search latest news abc123 whatever")

    def test_fallback_response_uses_news_specific_copy(self) -> None:
        self.assertEqual(
            _fallback_response(news_mode=True),
            "I couldn't fetch live news right now. Please try again in a moment or check Reuters, Bloomberg, CNBC, or Google News.",
        )

    def test_fallback_response_uses_generic_search_copy(self) -> None:
        self.assertEqual(
            _fallback_response(news_mode=False),
            "I couldn't fetch live search results right now. Please try again in a moment.",
        )


class WebSearchProviderFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        from app import web_search

        web_search._SEARCH_CACHE.clear()

    @patch("app.web_search.logging_utils.log_request_lifecycle")
    @patch("app.web_search.get_breaker")
    @patch("app.web_search._wikipedia_search")
    @patch("app.web_search._duckduckgo_search")
    @patch("app.web_search._tavily_search")
    def test_search_web_falls_back_to_duckduckgo_when_tavily_fails(
        self,
        tavily_mock,
        duckduckgo_mock,
        wikipedia_mock,
        get_breaker_mock,
        _log_mock,
    ) -> None:
        get_breaker_mock.side_effect = lambda *_args, **_kwargs: _FakeBreaker()
        tavily_mock.side_effect = RuntimeError("tavily unavailable")
        duckduckgo_mock.return_value = {
            "provider": "duckduckgo",
            "answer": "",
            "results": [
                {
                    "title": "Fallback hit",
                    "url": "https://example.com/a",
                    "snippet": "ok",
                }
            ],
        }
        wikipedia_mock.return_value = {
            "provider": "wikipedia",
            "answer": "",
            "results": [],
        }

        payload = search_web("latest transport news", max_results=3, news_mode=False)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["meta"]["provider"], "duckduckgo")
        self.assertGreaterEqual(len(payload["sources"]), 1)

    @patch("app.web_search.logging_utils.log_request_lifecycle")
    @patch("app.web_search.get_breaker")
    @patch("app.web_search._google_news_search")
    @patch("app.web_search._duckduckgo_search")
    @patch("app.web_search._tavily_search")
    def test_search_web_news_mode_degrades_when_all_providers_empty(
        self,
        tavily_mock,
        duckduckgo_mock,
        google_news_mock,
        get_breaker_mock,
        _log_mock,
    ) -> None:
        get_breaker_mock.side_effect = lambda *_args, **_kwargs: _FakeBreaker()
        tavily_mock.return_value = {"provider": "tavily", "answer": "", "results": []}
        google_news_mock.return_value = {"provider": "google-news-rss", "answer": "", "results": []}
        duckduckgo_mock.return_value = {"provider": "duckduckgo", "answer": "", "results": []}

        payload = search_web("breaking markets", max_results=2, news_mode=True)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["sources"], [])
        self.assertFalse(payload["meta"]["search_available"])


if __name__ == "__main__":
    unittest.main()
