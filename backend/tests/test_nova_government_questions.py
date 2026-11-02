"""Government-page public questions share the Home/Today read-only research path."""
from types import SimpleNamespace

import pytest

from app.core.nova.government import service
from app.core.nova.government.schemas import NovaGovBrainRequest
from app.core.nova.today import service as today
from app.core.nova.today.schemas import NovaTodayBrainOut
from test_nova_today_government_research import QUESTION


@pytest.mark.parametrize("item_id", [None, "previously-selected-saved-item"])
def test_public_government_question_is_not_replaced_by_saved_work(monkeypatch, item_id):
    def forbidden(*args, **kwargs):
        pytest.fail("Public research must not read saved government items or use the old organization-only prompt")
    monkeypatch.setattr(service, "list_items", forbidden)
    monkeypatch.setattr(service.NovaCoreService, "ask", forbidden)
    calls = []
    def ask(db, payload, *, organization_id, user):
        calls.append((db, payload, organization_id, user))
        return NovaTodayBrainOut(answer="Official source passage fixture", answer_parts=[{"text": "Passage fixture"}],
            sources=[{"title": "Official fixture", "url": "https://sam.gov/entity-registration"}],
            fact_label="OFFICIAL SOURCE EXCERPTS — APPLICABILITY NOT DETERMINED", next_actions=[],
            generated_at="2026-11-02T00:00:00Z", verification_status="unknown")
    monkeypatch.setattr(today, "ask_today", ask)
    user = SimpleNamespace(user_id="fixture-owner")
    result = service.ask_government(None, NovaGovBrainRequest(action="ask", question=QUESTION, item_id=item_id),
                                    organization_id="fixture-org", user=user)
    assert len(calls) == 1
    assert calls[0][1].question == QUESTION and calls[0][1].source_ref_id is None
    assert calls[0][2:] == ("fixture-org", user)
    assert result.action == "ask" and result.answer == "Official source passage fixture"
    assert result.answer_parts[0].text == "Passage fixture"
    assert result.sources[0].url == "https://sam.gov/entity-registration"
    assert result.next_actions == []


def test_research_failure_is_preserved_without_a_saved_or_general_answer_fallback(monkeypatch):
    monkeypatch.setattr(service, "list_items", lambda *a, **kw: pytest.fail("No saved fallback"))
    monkeypatch.setattr(today, "ask_today", lambda *a, **kw: NovaTodayBrainOut(
        answer="Candidate pages could not be read.", fact_label="LIVE INFORMATION NOT VERIFIED",
        generated_at="2026-11-02T00:00:00Z", sources=[], verification_status="unavailable"))
    result = service.ask_government(None, NovaGovBrainRequest(question=QUESTION), organization_id="fixture", user=SimpleNamespace())
    assert result.fact_label == "LIVE INFORMATION NOT VERIFIED" and result.sources == []
    assert result.answer == "Candidate pages could not be read."


def test_saved_government_tools_keep_their_existing_item_requirement(monkeypatch):
    monkeypatch.setattr(service, "list_items", lambda *a, **kw: [])
    monkeypatch.setattr(today, "ask_today", lambda *a, **kw: pytest.fail("Saved tools must remain separate"))
    result = service.ask_government(None, NovaGovBrainRequest(action="explain_requirement", question=QUESTION),
                                    organization_id="fixture", user=SimpleNamespace())
    assert result.fact_label == "USER ACTION REQUIRED"
    assert "Open a saved item first" in result.answer


def test_explicit_saved_question_does_not_enter_public_research(monkeypatch):
    monkeypatch.setattr(service, "list_items", lambda *a, **kw: [])
    monkeypatch.setattr(today, "ask_today", lambda *a, **kw: pytest.fail("Explicit saved questions stay in the saved-work handler"))
    monkeypatch.setattr(service.NovaCoreService, "ask", lambda *a, **kw: SimpleNamespace(
        answer="Saved-work fixture", next_actions=[], generated_at="2026-11-02T00:00:00Z"))
    result = service.ask_government(None, NovaGovBrainRequest(question="Explain my saved government record."),
                                    organization_id="fixture", user=SimpleNamespace())
    assert result.answer == "Saved-work fixture" and result.sources == []


def test_government_page_reaches_the_real_shared_public_research_handler(monkeypatch):
    from app.core.nova.today import hosted_search
    monkeypatch.setattr(service, "list_items", lambda *a, **kw: pytest.fail("No saved-work read for this public question"))
    monkeypatch.setattr(hosted_search, "enabled", lambda: True)
    calls = []
    def research(question):
        calls.append(question)
        return {"answer": "Retrieved official passage fixture", "answer_parts": [{"text": "Retrieved official passage fixture"}],
                "sources": [{"title": "Official fixture", "url": "https://sam.gov/entity-registration"}],
                "government_evidence_checked": True}
    monkeypatch.setattr(hosted_search, "search_public_web", research)
    result = service.ask_government(None, NovaGovBrainRequest(question=QUESTION, item_id="stale-selection"),
                                    organization_id="fixture-org", user=SimpleNamespace(user_id="fixture-user"))
    assert calls == [QUESTION]
    assert result.answer == "Retrieved official passage fixture"
    assert result.fact_label == "OFFICIAL SOURCE EXCERPTS — APPLICABILITY NOT DETERMINED"
    assert result.sources[0].url == "https://sam.gov/entity-registration"
