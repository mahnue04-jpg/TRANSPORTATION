"""Government-page public questions share the Home/Today read-only research path."""
import importlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.nova.government import service
from app.core.nova.government.schemas import NovaGovBrainRequest
from app.core.nova.today.schemas import NovaTodayBrainOut
from test_nova_today_government_research import QUESTION

gov_api = importlib.import_module("app.core.nova.government.router")
today = importlib.import_module("app.core.nova.today.router")


@pytest.mark.parametrize("item_id", [None, "previously-selected-saved-item"])
def test_public_government_question_is_not_replaced_by_saved_work(monkeypatch, item_id):
    monkeypatch.setattr(gov_api, "_resolve_org", lambda user, requested: "fixture-org")
    def forbidden(*args, **kwargs):
        pytest.fail("Public research must not read saved government items or use the old organization-only prompt")
    monkeypatch.setattr(service, "list_items", forbidden)
    monkeypatch.setattr(service.NovaCoreService, "ask", forbidden)
    calls = []
    def ask(payload, *, user, db):
        calls.append((db, payload, payload.organization_id, user))
        return NovaTodayBrainOut(answer="Official source passage fixture", answer_parts=[{"text": "Passage fixture"}],
            sources=[{"title": "Official fixture", "url": "https://sam.gov/entity-registration"}],
            fact_label="OFFICIAL SOURCE EXCERPTS — APPLICABILITY NOT DETERMINED", next_actions=[],
            generated_at="2026-11-02T00:00:00Z", verification_status="unknown")
    monkeypatch.setattr(today, "ask_today", ask)
    user = SimpleNamespace(user_id="fixture-owner")
    result = gov_api.ask_government(NovaGovBrainRequest(action="ask", question=QUESTION, item_id=item_id),
                                    user=user, db=None)
    assert len(calls) == 1
    assert calls[0][1].question == QUESTION and calls[0][1].source_ref_id is None
    assert calls[0][2:] == ("fixture-org", user)
    assert result.action == "ask" and result.answer == "Official source passage fixture"
    assert result.answer_parts[0].text == "Passage fixture"
    assert result.sources[0].url == "https://sam.gov/entity-registration"
    assert result.next_actions == []


def test_research_failure_is_preserved_without_a_saved_or_general_answer_fallback(monkeypatch):
    monkeypatch.setattr(gov_api, "_resolve_org", lambda user, requested: "fixture-org")
    monkeypatch.setattr(service, "list_items", lambda *a, **kw: pytest.fail("No saved fallback"))
    monkeypatch.setattr(today, "ask_today", lambda *a, **kw: NovaTodayBrainOut(
        answer="Candidate pages could not be read.", fact_label="LIVE INFORMATION NOT VERIFIED",
        generated_at="2026-11-02T00:00:00Z", sources=[], verification_status="unavailable"))
    result = gov_api.ask_government(NovaGovBrainRequest(question=QUESTION), user=SimpleNamespace(), db=None)
    assert result.fact_label == "LIVE INFORMATION NOT VERIFIED" and result.sources == []
    assert result.answer == "Candidate pages could not be read."


def test_saved_government_tools_keep_their_existing_item_requirement(monkeypatch):
    monkeypatch.setattr(gov_api, "_resolve_org", lambda user, requested: "fixture-org")
    monkeypatch.setattr(service, "list_items", lambda *a, **kw: [])
    monkeypatch.setattr(today, "ask_today", lambda *a, **kw: pytest.fail("Saved tools must remain separate"))
    result = gov_api.ask_government(NovaGovBrainRequest(action="explain_requirement", question=QUESTION),
                                    user=SimpleNamespace(), db=None)
    assert result.fact_label == "USER ACTION REQUIRED"
    assert "Open a saved item first" in result.answer


def test_explicit_saved_question_does_not_enter_public_research(monkeypatch):
    monkeypatch.setattr(gov_api, "_resolve_org", lambda user, requested: "fixture-org")
    monkeypatch.setattr(service, "list_items", lambda *a, **kw: [])
    monkeypatch.setattr(today, "ask_today", lambda *a, **kw: pytest.fail("Explicit saved questions stay in the saved-work handler"))
    monkeypatch.setattr(service.NovaCoreService, "ask", lambda *a, **kw: SimpleNamespace(
        answer="Saved-work fixture", next_actions=[], generated_at="2026-11-02T00:00:00Z"))
    result = gov_api.ask_government(NovaGovBrainRequest(question="Explain my saved government record."),
                                    user=SimpleNamespace(), db=None)
    assert result.answer == "Saved-work fixture" and result.sources == []


def test_government_page_reaches_the_real_shared_public_research_handler(monkeypatch):
    monkeypatch.setattr(gov_api, "_resolve_org", lambda user, requested: "fixture-org")
    from app.core.nova.today import hosted_search
    monkeypatch.setattr(today, "_resolve_org", lambda user, requested: "fixture-org")
    monkeypatch.setattr(today, "customer_access", lambda *a, **kw: {"trial_expired": False})
    usage_calls = []
    monkeypatch.setattr(today, "consume_free_ask", lambda db, **kw: usage_calls.append(kw) or {"is_free": False})
    monkeypatch.setattr(service, "list_items", lambda *a, **kw: pytest.fail("No saved-work read for this public question"))
    monkeypatch.setattr(hosted_search, "enabled", lambda: True)
    calls = []
    def research(question):
        calls.append(question)
        return {"answer": "Retrieved official passage fixture", "answer_parts": [{"text": "Retrieved official passage fixture"}],
                "sources": [{"title": "Official fixture", "url": "https://sam.gov/entity-registration"}],
                "government_evidence_checked": True}
    monkeypatch.setattr(hosted_search, "search_public_web", research)
    result = gov_api.ask_government(NovaGovBrainRequest(question=QUESTION, item_id="stale-selection"),
                                    user=SimpleNamespace(user_id="fixture-user"), db=None)
    assert calls == [QUESTION]
    assert usage_calls == [{"organization_id": "fixture-org"}]
    assert result.answer == "Retrieved official passage fixture"
    assert result.fact_label == "OFFICIAL SOURCE EXCERPTS — APPLICABILITY NOT DETERMINED"
    assert result.sources[0].url == "https://sam.gov/entity-registration"


@pytest.mark.parametrize("expired,expected_status", [(True, 403), (False, 429)])
def test_government_public_research_preserves_existing_ask_access_limits(monkeypatch, expired, expected_status):
    from app.core.nova.today import hosted_search
    monkeypatch.setattr(gov_api, "_resolve_org", lambda user, requested: "fixture-org")
    monkeypatch.setattr(today, "_resolve_org", lambda user, requested: "fixture-org")
    monkeypatch.setattr(today, "customer_access", lambda *a, **kw: {"trial_expired": expired})
    def consume(db, **kwargs):
        assert not expired, "Expired trials must stop before daily usage is consumed"
        return {"is_free": True, "allowed": False}
    monkeypatch.setattr(today, "consume_free_ask", consume)
    monkeypatch.setattr(hosted_search, "search_public_web", lambda *a: pytest.fail("No inference for a blocked account"))
    monkeypatch.setattr(service, "ask_government", lambda *a, **kw: pytest.fail("No fallback around access limits"))
    with pytest.raises(HTTPException) as error:
        gov_api.ask_government(NovaGovBrainRequest(question=QUESTION), user=SimpleNamespace(user_id="fixture"), db=None)
    assert error.value.status_code == expected_status
