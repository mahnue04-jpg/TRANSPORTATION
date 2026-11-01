"""Current public questions must use web evidence, never a generic no-access answer."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.nova.today import live_tools, service
from app.core.nova.today.schemas import NovaTodayBrainRequest


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
        return {"sources": [{"title": "Official player update (test fixture)", "url": "https://www.nba.com/timberwolves/fixture", "snippet": "Availability is unconfirmed in this test fixture.", "label": "NBA"}]}

    monkeypatch.setattr(service, "fetch_web_search", search)
    result = service.ask_today(_DB(), NovaTodayBrainRequest(question=question), organization_id="org-1", user=SimpleNamespace(user_id="user-1"))
    assert calls and "Anthony Edwards" in calls[0]
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
    monkeypatch.setattr(service, "fetch_web_search", lambda *a, **kw: {"sources": [{"title": "Official availability fixture", "url": "https://www.nba.com/fixture", "snippet": "Status not established in fixture."}]})
    monkeypatch.setattr(service.NovaCoreService, "_can_use_llm", lambda: True)

    def ask(*a, **kw):
        prompts.append(kw["question"])
        return SimpleNamespace(answer="I'm sorry, but I don't have access to live or external information.")

    monkeypatch.setattr(service.NovaCoreService, "ask", ask)
    result = service._grounded_web_research_answer(_DB(), question="Is Anthony Edwards playing tonight?", query="Anthony Edwards availability tonight", organization_id="org-1")
    assert "availability" in prompts[0]
    assert "do not infer today's status" in prompts[0].lower()
    assert "don't have access" not in result.answer
    assert "Official availability fixture" in result.answer
    assert result.sources
