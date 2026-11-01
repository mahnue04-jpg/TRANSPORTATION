from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.core.nova.today import hosted_search, service


def payload():
    text = "Anthony Edwards availability is unconfirmed in this test fixture. citefixture0"
    start = text.index("cite")
    return {
        "status": "completed",
        "output": [
            {"type": "web_search_call", "status": "completed"},
            {"type": "message", "content": [{"type": "output_text", "text": text, "annotations": [{"type": "url_citation", "start_index": start, "end_index": len(text), "url": "https://www.nba.com/timberwolves/fixture", "title": "Fixture availability report"}]}]},
        ],
        "usage": {"input_tokens": 100, "output_tokens": 30},
    }


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    monkeypatch.setenv("NOVA_HOSTED_WEB_SEARCH_ENABLED", "true")
    monkeypatch.delenv("NOVA_PUBLIC_SEARCH_PROBE_ID", raising=False)
    hosted_search._CACHE.clear()


def test_forced_search_is_bounded_cited_and_cached(monkeypatch):
    from app import ai
    calls = []
    options = []
    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(model_dump=payload)
    class Client:
        responses = SimpleNamespace(create=create)
        def with_options(self, **kw):
            options.append(kw)
            return self
    monkeypatch.setattr(ai, "get_client", lambda: Client())
    a = hosted_search.search_public_web("What is Anthony Edwards' current status?")
    b = hosted_search.search_public_web("“What is Anthony Edwards’ current status?”")
    assert a == b and len(calls) == 1
    assert options == [{"timeout": 28.0, "max_retries": 0}]
    assert calls[0]["tools"][0]["type"] == "web_search"
    assert calls[0]["tools"][0]["external_web_access"] is True
    assert calls[0]["tools"][0]["user_location"]["timezone"] == "America/Chicago"
    assert calls[0]["tool_choice"] == "required"
    assert calls[0]["include"] == ["web_search_call.action.sources"]
    assert calls[0]["max_tool_calls"] == 1
    assert calls[0]["max_output_tokens"] == 1600
    assert calls[0]["store"] is False
    assert a["sources"][0]["url"].startswith("https://www.nba.com/")
    assert "[1]" in a["answer"]
    assert "".join(p["text"] for p in a["answer_parts"]) == a["answer"]


@pytest.mark.parametrize("failure", ["incomplete", "no_search", "no_citation", "bad_url", "bad_range"])
def test_uncited_or_unsearched_responses_are_rejected(failure):
    data = payload()
    content = data["output"][1]["content"][0]
    if failure == "incomplete": data["status"] = "incomplete"
    elif failure == "no_search": data["output"].pop(0)
    elif failure == "no_citation": content["annotations"] = []
    elif failure == "bad_url": content["annotations"][0]["url"] = "javascript:alert(1)"
    else: content["annotations"][0]["end_index"] = 999999
    with pytest.raises(hosted_search.HostedSearchUnavailable):
        hosted_search._parse_response(data)


def test_disabled_feature_cannot_call_provider(monkeypatch):
    monkeypatch.setenv("NOVA_HOSTED_WEB_SEARCH_ENABLED", "false")
    with pytest.raises(hosted_search.HostedSearchUnavailable):
        hosted_search.search_public_web("current sports status")


def test_service_uses_the_cited_answer_without_scraped_search(monkeypatch):
    result = hosted_search._parse_response(payload())
    monkeypatch.setattr(hosted_search, "search_public_web", lambda q: result)
    monkeypatch.setattr(service, "fetch_news", lambda *a, **kw: pytest.fail("must not scrape when hosted search succeeds"))
    monkeypatch.setattr(service, "fetch_web_search", lambda *a, **kw: pytest.fail("must not scrape when hosted search succeeds"))
    out = service._grounded_web_research_answer(object(), question="What is Anthony Edwards' current status?", query="Anthony Edwards current status", organization_id="fixture")
    assert out.answer_parts[-1].url.startswith("https://www.nba.com/")
    assert out.fact_label == "LIVE WEB SOURCES"
    assert out.verification_status == "unknown"
    assert out.next_actions == []


def test_probe_claim_is_atomic_and_limits_calls_to_three(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_PUBLIC_SEARCH_PROBE_ID", "fixture-probe")
    monkeypatch.setenv("NOVA_PUBLIC_SEARCH_PROBE_ROOT", str(tmp_path))
    calls = []
    def search(q):
        calls.append(q)
        return hosted_search._parse_response(payload())
    monkeypatch.setattr(hosted_search, "search_public_web", search)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: hosted_search.run_probe_if_configured(), range(2)))
    hosted_search.run_probe_if_configured()
    assert calls == [service.resolve_public_sports_followup(q, hosted_search.PROBE_PUBLIC_TOPICS.get(q)) for q in hosted_search.PROBE_QUESTIONS]
    saved = json.loads((tmp_path / 'nova_public_search_probes/fixture-probe.json').read_text())
    assert len(saved["results"]) == 3
    assert all(r["status"] == "completed" for r in saved["results"])


def test_probe_requires_owner_configuration(monkeypatch):
    monkeypatch.setattr(hosted_search, "search_public_web", lambda q: pytest.fail("probe must be explicitly configured"))
    hosted_search.run_probe_if_configured()


def test_annotation_over_prose_does_not_delete_the_reported_fact():
    data = payload()
    content = data["output"][1]["content"][0]
    text = "Availability is not confirmed in this fixture."
    content["text"] = text
    content["annotations"][0]["start_index"] = 0
    content["annotations"][0]["end_index"] = len(text)
    result = hosted_search._parse_response(data)
    assert result["answer"] == text
    assert result["answer_parts"][0]["text"] == text
    assert result["answer_parts"][0]["url"].startswith("https://www.nba.com/")


def test_consulted_web_sources_are_visible_when_inline_annotations_are_absent():
    data = payload()
    data["output"][1]["content"][0].update(text="Fixture game starts at 7 PM CT.", annotations=[])
    data["output"][0]["action"] = {"sources": [{"type": "url", "url": "https://www.nba.com/fixture-schedule"}]}
    result = hosted_search._parse_response(data)
    assert "Sources consulted: [1]" in result["answer"]
    assert result["answer_parts"][-2]["url"] == "https://www.nba.com/fixture-schedule"


def test_actual_sports_feed_is_attributed_without_inventing_a_webpage(monkeypatch):
    data = payload()
    data["output"][1]["content"][0].update(text="Fixture game starts at 7 PM CT.", annotations=[])
    data["output"][0]["action"] = {"sources": [{"type": "url", "url": "oai-sports"}]}
    result = hosted_search._parse_response(data)
    assert result["source_feed"] == "Live sports data feed"
    assert result["sources"] == []
    assert "Source: Live sports data feed." in result["answer"]
    monkeypatch.setattr(hosted_search, "search_public_web", lambda q: result)
    out = service._grounded_web_research_answer(object(), question="What NBA games are scheduled tonight?", query="NBA tonight", organization_id="fixture")
    assert out.fact_label == "LIVE SPORTS FEED"
    assert out.source_href is None


def test_unknown_non_url_sources_do_not_pass_provenance_check():
    data = payload()
    data["output"][1]["content"][0]["annotations"] = []
    data["output"][0]["action"] = {"sources": [{"type": "url", "url": "unidentified-feed"}]}
    with pytest.raises(hosted_search.HostedSearchUnavailable):
        hosted_search._parse_response(data)


def test_tonight_resolves_to_minneapolis_date_after_utc_midnight():
    instant = datetime.fromisoformat("2026-11-01T01:40:00+00:00").astimezone(ZoneInfo("America/Chicago"))
    text = hosted_search._dated_search_question("What NBA games are scheduled tonight?", instant)
    assert "Saturday, October 31, 2026" in text
    assert "2026-10-31, evening, America/Chicago" in text
    assert "Central Time" in text
    assert "tonight" not in text


def test_relative_date_rollover_and_explicit_date_preservation():
    instant = datetime(2026, 10, 31, 21, tzinfo=ZoneInfo("America/Chicago"))
    assert "Sunday, November 01, 2026" in hosted_search._dated_search_question("NBA games tomorrow", instant)
    assert hosted_search._dated_search_question("NBA games on November 3, 2026", instant) == "NBA games on November 3, 2026"


@pytest.mark.parametrize("original, expected", [
    ("Saturday, Oct 31, 2026 at 05:00 PM PDT", "Saturday, Oct 31, 2026 at 07:00 PM CDT"),
    ("Sunday, Nov 01, 2026 at 05:00 PM PST", "Sunday, Nov 01, 2026 at 07:00 PM CST"),
    ("Saturday, Oct 31, 2026 at 11:30 PM PDT", "Sunday, Nov 01, 2026 at 01:30 AM CDT"),
])
def test_provider_pacific_schedule_times_are_converted_with_dst_and_date_rollover(original, expected):
    assert hosted_search._central_sports_times(original) == expected


def test_time_conversion_preserves_citation_links_and_answer_segments():
    data = payload()
    content = data["output"][1]["content"][0]
    content["text"] = "Fixture game: Saturday, Oct 31, 2026 at 05:00 PM PDT. citefixture0"
    content["annotations"][0].update(start_index=content["text"].index("cite"), end_index=len(content["text"]))
    result = hosted_search._parse_response(data)
    assert "07:00 PM CDT" in result["answer"]
    assert "PDT" not in result["answer"]
    assert result["sources"][0]["url"] == payload()["output"][1]["content"][0]["annotations"][0]["url"]
    assert "".join(p["text"] for p in result["answer_parts"]) == result["answer"]


def test_dated_nba_rows_replace_conflicting_generated_time_summary():
    data = payload()
    data["output"][1]["content"][0].update(text="Fixture game at 8 PM CT.\n\n## NBA Schedule\n- Fixture A @ Fixture B on Saturday, Oct 31, 2026 at 05:00 PM PDT. Current score: A 1 - B 2\n", annotations=[])
    data["output"][0]["action"] = {"sources": [{"type": "url", "url": "https://www.nba.com/fixture-schedule"}]}
    result = hosted_search._prefer_dated_nba_schedule(hosted_search._parse_response(data), "What NBA games are scheduled tonight?")
    assert "8 PM CT" not in result["answer"]
    assert "07:00 PM CDT" in result["answer"]
    assert "Current score: A 1 - B 2" in result["answer"]
    assert result["answer"].count("Fixture A @ Fixture B") == 1
    assert "".join(p["text"] for p in result["answer_parts"]) == result["answer"]
    assert result["answer_parts"][-2]["url"] == "https://www.nba.com/fixture-schedule"


def test_dated_nba_schedule_selection_does_not_replace_player_status():
    result = {"answer": "Player fixture status.\n## NBA Schedule\n- A @ B on Saturday, Oct 31, 2026 at 07:00 PM CDT", "sources": []}
    assert hosted_search._prefer_dated_nba_schedule(result, "Anthony Edwards current status in NBA") is result


def test_prediction_label_is_explicit_and_citation_segments_still_match():
    result = hosted_search._label_prediction(hosted_search._parse_response(payload()), "Who do you think will win between the Lions and the Vikings?")
    assert result["answer"].startswith("Sports prediction — uncertain, not a guaranteed result.")
    assert "".join(p["text"] for p in result["answer_parts"]) == result["answer"]
    assert result["sources"]


def test_viewing_followup_does_not_inherit_prediction_status():
    question = service.resolve_public_sports_followup("Where can I watch it for free?", "Who will win between the Lions and the Vikings?")
    result = hosted_search._label_prediction(hosted_search._parse_response(payload()), question)
    assert not result["answer"].startswith("Sports prediction")


def test_viewing_answer_is_not_replaced_by_an_appended_nba_schedule():
    result = {
        "answer": "Fixture broadcaster and free-viewing terms.\n## NBA Schedule\n- A @ B on Saturday, Oct 31, 2026 at 07:00 PM CDT",
        "sources": [{"title": "Fixture", "url": "https://www.nba.com/fixture"}],
    }
    assert hosted_search._prefer_dated_nba_schedule(result, "Where can I watch NBA games for free?") is result


def test_viewing_queries_only_search_official_league_broadcaster_and_service_domains(monkeypatch):
    from app import ai
    calls = []
    class Client:
        def with_options(self, **kw): return self
        responses = SimpleNamespace(create=lambda **kw: (calls.append(kw) or SimpleNamespace(model_dump=payload)))
    monkeypatch.setattr(ai, "get_client", lambda: Client())
    question = service.resolve_public_sports_followup("How can I watch the game for free?", "Minnesota Timberwolves game, viewing from Minneapolis")
    hosted_search.search_public_web(question)
    domains = calls[0]["tools"][0]["filters"]["allowed_domains"]
    assert "nba.com" in domains and "dazn.com" in domains and "fox9.com" in domains
    assert "swipesports.com" not in domains
    assert calls[0]["max_tool_calls"] == 1
    assert calls[0]["max_output_tokens"] == 1600


def test_unqualified_free_app_claim_is_not_presented_as_verified_full_game_access():
    result = {
        "answer_parts": [
            {"text": "Broadcast: FOX 9 at noon.\n"},
            {"text": "[1]", "url": "https://www.nfl.com/fixture", "title": "Game fixture"},
            {"text": "\nStreaming via FOX app: You may stream the game for free through the FOX LOCAL app, no subscription required. "},
            {"text": "[2]", "url": "https://www.fox9.com/fixture", "title": "Pregame fixture"},
            {"text": "\nThese are the only confirmed free viewing options in Minneapolis."},
        ],
        "sources": [{"title": "Game fixture", "url": "https://www.nfl.com/fixture"}],
    }
    result["answer"] = "".join(p["text"] for p in result["answer_parts"])
    out = hosted_search._calibrate_viewing_claims(result, "Where can I watch the Lions versus Vikings game for free?")
    assert "FOX 9 at noon" in out["answer"]
    assert "You may stream the game for free" not in out["answer"]
    assert "has not been verified here" in out["answer"]
    assert "only confirmed free" not in out["answer"]
    assert "".join(p["text"] for p in out["answer_parts"]) == out["answer"]
    assert out["answer_parts"][3]["url"] == "https://www.fox9.com/fixture"


def test_scoped_free_offers_and_paid_requirements_are_kept_distinct():
    text = "DAZN app offers 15 designated free games.\nStreaming through NFL+ is not free; a subscription is required.\nAn eligible free trial requires checking current terms."
    result = {"answer": text, "answer_parts": [{"text": text}], "sources": []}
    out = hosted_search._calibrate_viewing_claims(result, "Where can I watch the Timberwolves game for free?")
    assert out["answer"] == text


def test_past_unannounced_availability_is_not_asserted_as_current():
    text = "The free-game channel and dates have not yet been announced."
    result = {"answer": text, "answer_parts": [{"text": text}], "sources": []}
    out = hosted_search._calibrate_viewing_claims(result, "Where can I watch the Timberwolves game for free?")
    assert "not yet been announced" not in out["answer"]
    assert "have not been verified here" in out["answer"]
