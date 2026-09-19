from __future__ import annotations

from app.core.nova.today import live_tools


def test_extract_name_statement_and_recall_profile(tmp_path, monkeypatch):
    store = live_tools.memory_store.__class__(str(tmp_path / "nova_memory.json"))
    monkeypatch.setattr(live_tools, "memory_store", store)

    assert live_tools.extract_name_statement("My name is Saye.") == "Saye"
    live_tools.update_user_profile("org-1", "user-1", {"preferred_name": "Saye"})
    profile = live_tools.read_user_profile("org-1", "user-1")
    assert profile["preferred_name"] == "Saye"
    assert live_tools.asks_for_name("What is my name?") is True


def test_extract_location_and_weather_location():
    assert live_tools.extract_location_statement("I live in Minneapolis, Minnesota.") == "Minneapolis, Minnesota"
    assert live_tools.extract_weather_location("What's the weather in Minneapolis?") == "Minneapolis"


def test_rank_news_query_extraction():
    assert live_tools.extract_news_query("latest news") is None
    assert live_tools.extract_news_query("latest news about artificial intelligence") == "about artificial intelligence"


def test_format_weather():
    answer = live_tools.format_weather(
        {
            "location": "Minneapolis, Minnesota, United States",
            "temperature_f": 72,
            "apparent_f": 71,
            "humidity_pct": 50,
            "wind_mph": 8,
            "condition": "clear sky",
        }
    )
    assert "Minneapolis" in answer
    assert "72°F" in answer
    assert "Open-Meteo" in answer


def test_format_news():
    answer = live_tools.format_news(
        [
            {
                "title": "Example headline",
                "source": "Example News",
                "link": "https://example.com/story",
                "published": "today",
            }
        ],
        "AI",
    )
    assert "Here is a quick news briefing for AI:" in answer
    assert "Example headline (Example News)" in answer
    assert "https://" not in answer


def test_direct_answer_uses_serializable_timestamp(monkeypatch):
    from types import SimpleNamespace

    from app.core.nova.today import service
    from app.core.nova.today.schemas import NovaTodayBrainRequest

    monkeypatch.setattr(service, "read_user_profile", lambda organization_id, user_id: {})
    monkeypatch.setattr(
        service,
        "update_user_profile",
        lambda organization_id, user_id, patch: dict(patch),
    )

    account = SimpleNamespace(display_name=None)
    class _Query:
        def filter(self, *args, **kwargs):
            return self
        def first(self):
            return account
    class _DB:
        def query(self, *args, **kwargs):
            return _Query()
        def add(self, value):
            pass
        def commit(self):
            pass
        def refresh(self, value):
            pass

    result = service._today_live_or_memory_answer(
        _DB(),
        NovaTodayBrainRequest(question="My name is Saye"),
        organization_id="org-1",
        user=SimpleNamespace(user_id="user-1"),
    )

    assert result is not None
    assert result.answer == "Got it. I’ll remember your name as Saye."
    assert isinstance(result.generated_at, str)
    assert "T" in result.generated_at


def test_news_format_is_concise_and_has_no_raw_url():
    answer = live_tools.format_news(
        [
            {
                "title": "Example headline - Example News",
                "source": "Example News",
                "link": "https://news.google.com/rss/articles/example",
                "published": "today",
            }
        ]
    )
    assert "Here is a quick news briefing:" in answer
    assert "Example headline (Example News)" in answer
    assert "https://" not in answer


def test_direct_answer_recalls_account_display_name(monkeypatch):
    from types import SimpleNamespace

    from app.core.nova.today import service
    from app.core.nova.today.schemas import NovaTodayBrainRequest

    monkeypatch.setattr(service, "read_user_profile", lambda organization_id, user_id: {})

    account = SimpleNamespace(display_name="Saye")

    class _Query:
        def filter(self, *args, **kwargs):
            return self
        def first(self):
            return account

    class _DB:
        def query(self, *args, **kwargs):
            return _Query()

    result = service._today_live_or_memory_answer(
        _DB(),
        NovaTodayBrainRequest(question="What is my name?"),
        organization_id="org-1",
        user=SimpleNamespace(user_id="user-1"),
    )

    assert result is not None
    assert result.answer == "Your name is Saye."
    assert result.fact_label == "USER-SAVED INFORMATION"


def test_web_search_capability_and_known_sites():
    assert live_tools.is_web_search_capability_question("Can you search the web?") is True
    assert live_tools.is_web_search_request("Look up the latest movie playing today") is True
    assert live_tools.extract_known_site("Open YouTube") == ("YouTube", "https://www.youtube.com/")
    assert live_tools.extract_known_site("Can you pull up YouTube for me?") == ("YouTube", "https://www.youtube.com/")
    assert live_tools.extract_known_site("Take me directly to Facebook") == ("Facebook", "https://www.facebook.com/")
    assert live_tools.extract_known_site("Please bring up Instagram") == ("Instagram", "https://www.instagram.com/")
    assert live_tools.extract_known_site("Visit LinkedIn") == ("LinkedIn", "https://www.linkedin.com/")
    assert live_tools.extract_known_site("Tell me about YouTube") is None
    assert "Minneapolis" in live_tools.extract_web_query("look up movies playing today", "Minneapolis, Minnesota")


def test_fetch_web_search_passthrough(monkeypatch):
    monkeypatch.setattr(
        live_tools,
        "search_web",
        lambda query, max_results=5, news_mode=False: {
            "response": "Search results for movies.",
            "sources": [
                {"title": "Example", "url": "https://example.com", "label": "example.com"},
            ],
            "status": "success",
        },
    )
    result = live_tools.fetch_web_search("movies playing today")
    assert result["status"] == "success"
    assert result["sources"][0]["url"] == "https://example.com"
