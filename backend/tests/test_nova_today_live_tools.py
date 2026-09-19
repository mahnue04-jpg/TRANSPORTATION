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
    assert "Current news for AI" in answer
    assert "Example headline" in answer
    assert "https://example.com/story" in answer


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

    result = service._today_live_or_memory_answer(
        NovaTodayBrainRequest(question="My name is Saye"),
        organization_id="org-1",
        user=SimpleNamespace(user_id="user-1"),
    )

    assert result is not None
    assert result.answer == "Got it. I’ll remember your name as Saye."
    assert isinstance(result.generated_at, str)
    assert "T" in result.generated_at
