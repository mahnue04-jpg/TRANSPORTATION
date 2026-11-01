"""Current public questions must use web evidence, never a generic no-access answer."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.nova.today import live_tools, service
from app.core.nova.today.schemas import NovaTodayBrainRequest


@pytest.fixture(autouse=True)
def offline_news(monkeypatch):
    monkeypatch.setattr(service, "fetch_news", lambda *a, **kw: [])


@pytest.mark.parametrize("question", [
    "What is the current status of Anthony Edwards from the Minnesota Timberwolves?",
    "What is Anthony Edwards' current status?",
    "What happened to Anthony Edwards?",
    "Is Anthony Edwards playing tonight?",
    "Anthony Edwards injury update",
    "What is the latest NBA score?",
    "Who won the basketball game last night?",
    "Any updates on the player injury?",
    "What's going on with Anthony Edwards?",
    "What’s going on with Anthony Edwards?",
])
def test_current_public_information_uses_live_search(question):
    assert live_tools.is_web_search_request(question)


@pytest.mark.parametrize("question", [
    "What is the current status of my project?",
    "What happened to my client?",
    "What happened to the workspace?",
    "Any updates on our tasks?",
    "What is the current status of my account?",
    "What needs my attention today?",
    "Explain basketball rules",
    "Who is Anthony Edwards?",
    "How many bones are in an adult human body?",
])
def test_internal_and_stable_questions_do_not_use_public_status_route(question):
    assert not live_tools.is_web_search_request(question)


class _DB:
    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None


@pytest.mark.parametrize("question", [
    "What is the current status of Anthony Edwards from the Minnesota Timberwolves?",
    "Is Anthony Edwards playing tonight?",
    "What happened to Anthony Edwards?",
])
def test_ask_uses_web_sources_instead_of_generic_brain(monkeypatch, question):
    calls = []
    monkeypatch.setattr(service, "_today_government_grounded_answer", lambda *a, **kw: None)
    monkeypatch.setattr(service, "_answer_saved_work_opportunity", lambda *a, **kw: None)
    monkeypatch.setattr(service, "read_user_profile", lambda *a: {})
    monkeypatch.setattr(service.NovaCoreService, "_can_use_llm", lambda: False)
    monkeypatch.setattr(service.NovaCoreService, "ask", lambda *a, **kw: pytest.fail("must not use ungrounded Brain"))

    def search(query, **kwargs):
        calls.append(query)
        return {"sources": [{"title": "Anthony Edwards Minnesota Timberwolves update (test fixture)", "url": "https://www.nba.com/timberwolves/fixture", "snippet": "Availability is unconfirmed in this test fixture.", "label": "NBA"}]}

    monkeypatch.setattr(service, "fetch_web_search", search)
    result = service.ask_today(_DB(), NovaTodayBrainRequest(question=question), organization_id="org-1", user=SimpleNamespace(user_id="user-1"))
    assert calls and "anthony edwards" in calls[0].lower()
    assert result.sources[0].url.startswith("https://www.nba.com/")
    assert result.next_actions == []
    assert "don't have access" not in result.answer
    assert "eligibility" not in result.answer


def test_no_search_results_do_not_fall_back_to_ungrounded_current_claims(monkeypatch):
    monkeypatch.setattr(service, "fetch_web_search", lambda *a, **kw: {"sources": []})
    monkeypatch.setattr(service.NovaCoreService, "ask", lambda *a, **kw: pytest.fail("no current facts without sources"))
    result = service._grounded_web_research_answer(_DB(), question="Is Anthony Edwards playing tonight?", query="Anthony Edwards availability tonight", organization_id="org-1")
    assert result.sources == []
    assert result.verification_status == "unavailable"
    assert "could not verify" in result.answer.lower()


def test_grounded_status_prompt_and_generic_denial_recovery(monkeypatch):
    prompts = []
    monkeypatch.setattr(service, "fetch_web_search", lambda *a, **kw: {"sources": [{"title": "Anthony Edwards availability fixture", "url": "https://www.nba.com/fixture", "snippet": "Status not established in fixture."}]})
    monkeypatch.setattr(service.NovaCoreService, "_can_use_llm", lambda: True)

    def ask(*a, **kw):
        prompts.append(kw["question"])
        return SimpleNamespace(answer="I'm sorry, but I don't have access to live or external information.")

    monkeypatch.setattr(service.NovaCoreService, "ask", ask)
    result = service._grounded_web_research_answer(_DB(), question="Is Anthony Edwards playing tonight?", query="Anthony Edwards availability tonight", organization_id="org-1")
    assert "availability" in prompts[0]
    assert "do not infer today's status" in prompts[0].lower()
    assert "don't have access" not in result.answer
    assert "Anthony Edwards availability fixture" in result.answer
    assert result.sources


def test_irrelevant_whatsapp_results_are_rejected_without_verification_claim(monkeypatch):
    junk = {"title": "WhatsApp Web", "url": "https://web.whatsapp.com", "snippet": "Private messaging and calling"}
    monkeypatch.setattr(service, "fetch_news", lambda *a, **kw: [{"title": junk["title"], "link": junk["url"], "source": "WhatsApp"}])
    monkeypatch.setattr(service, "fetch_web_search", lambda *a, **kw: {"sources": [junk]})
    monkeypatch.setattr(service.NovaCoreService, "ask", lambda *a, **kw: pytest.fail("irrelevant evidence must not reach the model"))
    result = service._grounded_web_research_answer(_DB(), question="What is Anthony Edwards' current status with the Minnesota Timberwolves?", query="What is Anthony Edwards' current status with the Minnesota Timberwolves?", organization_id="org-1")
    assert result.sources == []
    assert result.source_href is None
    assert result.verification_status == "unavailable"
    assert result.fact_label == "LIVE INFORMATION NOT VERIFIED"
    assert "WhatsApp" not in result.answer


def test_current_status_prefers_subject_news_and_preserves_dates_for_synthesis(monkeypatch):
    calls = []
    prompts = []
    def news(query, **kw):
        calls.append(query)
        return [
            {"title": "WhatsApp Web", "link": "https://web.whatsapp.com", "source": "WhatsApp"},
            {"title": "Timberwolves Anthony Edwards availability fixture", "link": "https://www.nba.com/timberwolves/fixture", "source": "NBA", "published": "Sat, 31 Oct 2026 10:00:00 GMT"},
        ]
    monkeypatch.setattr(service, "fetch_news", news)
    monkeypatch.setattr(service, "fetch_web_search", lambda *a, **kw: pytest.fail("relevant news should not trigger another provider"))
    monkeypatch.setattr(service.NovaCoreService, "_can_use_llm", lambda: True)
    def answer(*a, **kw):
        prompts.append(kw["question"])
        return SimpleNamespace(answer="The fixture does not establish current playing availability.")
    monkeypatch.setattr(service.NovaCoreService, "ask", answer)
    question = "What is Anthony Edwards' current status with the Minnesota Timberwolves?"
    result = service._grounded_web_research_answer(_DB(), question=question, query=question, organization_id="org-1")
    assert calls == ["anthony edwards minnesota timberwolves"]
    assert len(result.sources) == 1
    assert result.sources[0].label == "NBA"
    assert "Sat, 31 Oct 2026" in prompts[0]
    assert "WhatsApp" not in prompts[0]
    assert result.fact_label == "LIVE WEB SOURCES"
    assert result.verification_status == "unknown"


def test_public_source_requires_more_than_a_location_or_surname():
    terms = live_tools.public_query_terms("What is Anthony Edwards' current status with the Minnesota Timberwolves?")
    assert terms == ["anthony", "edwards", "minnesota", "timberwolves"]
    assert not live_tools.source_matches_public_query({"title": "WhatsApp in Minnesota"}, terms)
    assert not live_tools.source_matches_public_query({"title": "Anthony Edwards actor profile"}, terms)
    assert live_tools.source_matches_public_query({"title": "Timberwolves Anthony Edwards report"}, terms)


@pytest.mark.parametrize("question", [
    "Who are the starting players for the Minnesota Timberwolves?",
    "Show me the Timberwolves roster.",
    "Who are the Timberwolves starters?",
    "What is the Timberwolves starting five?",
    "Who is starting for the Timberwolves tonight?",
    "Show NBA starting lineups",
    "Show me NBA rosters",
    "Who is in the Lakers line-up?",
    "What is the Vikings depth chart?",
    "Who are our Timberwolves starters?",
])
def test_implicit_current_sports_facts_use_live_search(question):
    assert live_tools.is_current_public_information_request(question)
    assert live_tools.is_web_search_request(question)


@pytest.mark.parametrize("question", [
    "Show our staff roster",
    "What is my fantasy basketball roster?",
    "What is the current status of our NBA project?",
    "Show my NBA subscription",
])
def test_private_rosters_and_sports_project_work_stay_private(question):
    assert not live_tools.is_current_public_information_request(question)


@pytest.mark.parametrize("question", [
    "Who are the starting players for the Minnesota Timberwolves?",
    "Show me the Timberwolves roster.",
    "Who is starting for the Timberwolves tonight?",
])
def test_plain_lineup_question_reaches_hosted_search_through_ask_today(monkeypatch, question):
    from app.core.nova.today import hosted_search

    calls = []
    monkeypatch.setattr(service, "_today_government_grounded_answer", lambda *a, **kw: None)
    monkeypatch.setattr(service, "_answer_saved_work_opportunity", lambda *a, **kw: None)
    monkeypatch.setattr(service, "read_user_profile", lambda *a: {})
    monkeypatch.setattr(service.NovaCoreService, "ask", lambda *a, **kw: pytest.fail("lineup must not reach basic chat"))
    monkeypatch.setattr(hosted_search, "enabled", lambda: True)

    def search(q):
        calls.append(q)
        return {
            "answer": "Fixture lineup, reported on the fixture date. [1]",
            "answer_parts": [
                {"text": "Fixture lineup, reported on the fixture date. "},
                {"text": "[1]", "url": "https://www.nba.com/timberwolves/fixture", "title": "Fixture"},
            ],
            "sources": [{"title": "Fixture", "url": "https://www.nba.com/timberwolves/fixture", "label": "NBA"}],
        }

    monkeypatch.setattr(hosted_search, "search_public_web", search)
    result = service.ask_today(_DB(), NovaTodayBrainRequest(question=question), organization_id="org-1", user=SimpleNamespace(user_id="user-1"))
    assert calls == [question]
    assert result.fact_label == "LIVE WEB SOURCES"
    assert result.sources[0].url == "https://www.nba.com/timberwolves/fixture"
    assert result.next_actions == []
    assert "don't have access" not in result.answer
