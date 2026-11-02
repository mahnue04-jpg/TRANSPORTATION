"""Public government research must not become a saved licensing next-step answer."""
from types import SimpleNamespace

import pytest

from app.core.nova.today import hosted_search, live_tools, service
from app.core.nova.today.schemas import NovaTodayBrainRequest


QUESTION = """A small Minnesota LLC wants to pursue its first federal government service contract.
Research the current requirements as of today using official SAM.gov, SBA.gov, and Acquisition.gov sources.
1. Does obtaining a Unique Entity ID automatically mean the business has an active SAM.gov registration?
What does the government charge for registration and renewal?
2. Does minority ownership alone qualify a business for the SBA 8(a) program or guarantee a government contract?
Explain the distinction between eligibility, certification, and winning an award.
3. Before bidding on a fixed-price contract, what should the owner check about payment timing,
upfront expenses, and working capital? Explain how a profitable contract could still create a cash shortage.
Give clickable official sources supporting each regulatory claim, identify when you checked them,
and distinguish requirements from business recommendations. Do not assume this particular company qualifies.
If you cannot verify something, identify the specific missing information."""


def evidence():
    # Synthetic transport fixture, not current regulatory evidence or a live model evaluation.
    return {"answer": "Official research fixture for all requested topics.",
            "answer_parts": [{"text": "Official research fixture for all requested topics."}],
            "sources": [{"title": "Official fixture", "url": "https://sam.gov/fixture"}]}


@pytest.mark.parametrize("question", [QUESTION,
    "Research current SBA 8(a) eligibility using official sources.",
    "Verify current federal contracting registration requirements using SAM.gov.",
    "Research official licensing requirements for my business today.",
])
def test_public_government_research_is_live(question):
    assert live_tools.is_public_government_research_request(question)
    assert live_tools.is_current_public_information_request(question)
    assert live_tools.is_web_search_request(question)


@pytest.mark.parametrize("question", [
    "What do I need to do next for this Minnesota Business License Requirements work item?",
    "Explain my saved government record and its current requirements.",
    "What is the current status of our saved license?",
    "Find government contract opportunities for logistics businesses.",
    "Calculate 12 hours at $20 each for this fictional contract.",
])
def test_saved_work_and_opportunity_search_are_not_reclassified(question):
    assert not live_tools.is_public_government_research_request(question)


def test_domain_extraction_does_not_admit_lookalike_hosts():
    assert live_tools.government_research_domains(QUESTION) == ["sam.gov", "sba.gov", "acquisition.gov"]
    assert live_tools.government_research_domains("Use SAM.gov. Also use https://www.sba.gov/path.") == ["sam.gov", "www.sba.gov"]
    assert live_tools.government_research_domains("sam.gov.attacker.com sba.gov-evil.com") == []


def test_exact_reported_question_bypasses_saved_license_and_all_account_reads(monkeypatch):
    calls = []
    def forbidden(*args, **kw):
        pytest.fail("public research must not read or write saved account/government data")
    for name in ("government_list_items", "government_ask", "_today_government_grounded_answer",
                 "_answer_saved_work_opportunity", "read_user_profile", "update_user_profile", "dashboard"):
        monkeypatch.setattr(service, name, forbidden)
    monkeypatch.setattr(hosted_search, "enabled", lambda: True)
    monkeypatch.setattr(hosted_search, "search_public_web", lambda q: calls.append(q) or evidence())
    out = service.ask_today(None, NovaTodayBrainRequest(question=QUESTION), organization_id="fixture-org", user=SimpleNamespace(user_id="fixture-user"))
    assert calls == [QUESTION]
    assert out.fact_label == "LIVE WEB SOURCES"
    assert out.sources[0].url == "https://sam.gov/fixture"
    assert out.referenced_source_ref_id is None and out.next_actions == []
    assert "license and permits" not in out.answer


@pytest.mark.parametrize("enabled", [False, True])
def test_unavailable_live_research_never_substitutes_a_saved_record(monkeypatch, enabled):
    monkeypatch.setattr(hosted_search, "enabled", lambda: enabled)
    def fail(q):
        raise hosted_search.HostedSearchUnavailable("fixture_provider_failure")
    monkeypatch.setattr(hosted_search, "search_public_web", fail)
    monkeypatch.setattr(service, "fetch_web_search", lambda *a, **kw: pytest.fail("no unverified fallback"))
    out = service._grounded_web_research_answer(None, question=QUESTION, query=QUESTION, organization_id="fixture")
    assert out.verification_status == "unavailable" and out.sources == []
    assert out.source_href is None and out.referenced_source_ref_id is None
    assert out.fact_label == "LIVE INFORMATION NOT VERIFIED"


def test_saved_government_matching_requires_an_explicit_record_reference(monkeypatch):
    monkeypatch.setattr(service, "government_list_items", lambda *a, **kw: pytest.fail("no generic keyword matching"))
    for question in [QUESTION, "Explain federal government business license requirements"]:
        assert service._today_government_grounded_answer(None, question=question, organization_id="fixture", user=SimpleNamespace()) is None


def test_government_research_requires_citations_even_if_a_feed_was_returned(monkeypatch):
    hosted_search._CACHE.clear()
    monkeypatch.setenv("NOVA_HOSTED_WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-real-key")
    response = {"status": "completed", "output": [
        {"type": "web_search_call", "status": "completed"},
        {"type": "message", "content": [{"type": "output_text", "text": "Uncited government fixture", "annotations": []}]},
    ]}
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: SimpleNamespace(model_dump=lambda: response)))
    client.with_options = lambda **kw: client
    monkeypatch.setattr("app.ai.get_client", lambda: client)
    monkeypatch.setattr(hosted_search, "_parse_response", lambda payload: {
        "answer": "Uncited government fixture", "answer_parts": [], "sources": [], "source_feed": "oai-sports",
    })
    with pytest.raises(hosted_search.HostedSearchUnavailable, match="government_sources_missing"):
        hosted_search.search_public_web(QUESTION)


@pytest.mark.parametrize("url,allowed", [
    ("https://www.sba.gov/certifications/", True),
    ("https://sam.gov/fixture", True),
    ("https://www.acquisition.gov/far/32.905", True),
    ("https://mn.gov/deed/business/starting-business/legal-regulatory/", False),
    ("https://sam.gov.attacker.com/", False),
    ("https://commercial-registration.example/", False),
])
def test_hosted_search_honors_requested_domains_and_rejects_other_sources(monkeypatch, url, allowed):
    hosted_search._CACHE.clear()
    monkeypatch.setenv("NOVA_HOSTED_WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-real-key")
    calls = []
    result = {"status": "completed", "output": [
        {"type": "web_search_call", "status": "completed"},
        {"type": "message", "content": [{"type": "output_text", "text": "Fixture answer [1]", "annotations": [
            {"type": "url_citation", "start_index": 15, "end_index": 18, "url": url, "title": "Fixture"}
        ]}]},
    ]}
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(model_dump=lambda: result)
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    client.with_options = lambda **kwargs: client
    monkeypatch.setattr("app.ai.get_client", lambda: client)
    if allowed:
        from app.core.nova.today import government_review
        monkeypatch.setattr(government_review, "review_government_answer", lambda q, draft, **kw: draft)
        assert hosted_search.search_public_web(QUESTION)["sources"][0]["url"] == url
    else:
        with pytest.raises(hosted_search.HostedSearchUnavailable, match="government_sources_missing"):
            hosted_search.search_public_web(QUESTION)
    request = calls[0]
    assert request["tools"][0]["filters"] == {"allowed_domains": ["sam.gov", "sba.gov", "acquisition.gov"]}
    assert request["max_tool_calls"] == 1 and request["max_output_tokens"] == 1600
    assert "every numbered question" in request["instructions"]
    assert "date checked" in request["instructions"]


def test_source_excerpt_label_does_not_claim_verified_requirements(monkeypatch):
    fixture = {**evidence(), "government_evidence_checked": True}
    monkeypatch.setattr(hosted_search, "enabled", lambda: True)
    monkeypatch.setattr(hosted_search, "search_public_web", lambda q: fixture)
    out = service._grounded_web_research_answer(None, question=QUESTION, query=QUESTION, organization_id="fixture")
    assert out.fact_label == "OFFICIAL SOURCE EXCERPTS — APPLICABILITY NOT DETERMINED"
    assert out.verification_status == "unknown"


@pytest.mark.parametrize("code,detail", [
    ("government_sources_missing", "did not supply usable official pages"),
    ("government_source_text_unavailable", "contents could not be read"),
    ("government_evidence_budget_exhausted", "time limit"),
    ("invalid_evidence_selection", "supporting passages could not be assembled"),
])
def test_failure_explains_stage_without_private_payload_or_irrelevant_saved_record(monkeypatch, caplog, code, detail):
    monkeypatch.setattr(hosted_search, "enabled", lambda: True)
    def fail(question): raise hosted_search.HostedSearchUnavailable(code)
    monkeypatch.setattr(hosted_search, "search_public_web", fail)
    with caplog.at_level("WARNING"):
        out = service._grounded_web_research_answer(None, question=QUESTION, query=QUESTION, organization_id="fixture")
    assert detail in out.answer
    assert "saved licensing" not in out.answer and "Please retry" not in out.answer
    assert "code=" + code in caplog.text
    assert QUESTION not in caplog.text
    assert out.sources == [] and out.verification_status == "unavailable"
