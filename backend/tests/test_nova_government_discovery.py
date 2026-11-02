"""Offline regressions for the live failure: three requested sites yielded SBA only."""
import json
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.core.nova.today import government_discovery as discovery, hosted_search
from test_nova_today_government_research import QUESTION

DOMAINS = ["sam.gov", "sba.gov", "acquisition.gov"]
NOW = datetime(2026, 11, 2, tzinfo=ZoneInfo("America/Chicago"))


def payload(domain):
    return {"status": "completed", "output": [{"type": "web_search_call", "status": "completed", "action": {
        "sources": [{"url": "https://" + domain + "/detail-" + str(i)} for i in range(6)]}}],
        "usage": {"input_tokens": 100, "output_tokens": 20}}


def install(monkeypatch, create):
    options = []
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    def with_options(**kwargs):
        options.append(kwargs)
        return client
    client.with_options = with_options
    monkeypatch.setattr("app.ai.get_client", lambda: client)
    return options


def test_each_requested_site_gets_the_relevant_focus_instead_of_one_broad_query():
    plan = discovery.discovery_plan(QUESTION, DOMAINS)
    assert [row["domains"] for row in plan] == [[d] for d in DOMAINS]
    assert "Unique Entity ID" in plan[0]["focus"] and "minority ownership" not in plan[0]["focus"]
    assert "minority ownership" in plan[1]["focus"] and "payment timing" not in plan[1]["focus"]
    assert "payment timing" in plan[2]["focus"] and "Unique Entity ID" not in plan[2]["focus"]


def test_site_coverage_survives_paste_that_removes_line_breaks_without_spaces():
    compact = QUESTION.replace("\n", "")
    plan = discovery.discovery_plan(compact, DOMAINS)
    assert len(plan) == 3
    assert [row["domains"] for row in plan] == [[d] for d in DOMAINS]
    assert all(row["focus"] for row in plan)


def test_query_count_is_bounded_and_all_requested_domain_filters_are_retained():
    domains = ["site" + str(i) + ".gov" for i in range(8)]
    plan = discovery.discovery_plan(QUESTION, domains)
    assert len(plan) == 3
    assert sorted(domain for entry in plan for domain in entry["domains"]) == sorted(domains)


def test_unnamed_sites_use_separate_question_focuses_but_one_question_stays_one_query():
    plan = discovery.discovery_plan(QUESTION, [])
    assert len(plan) == 3 and all(row["domains"] == [] for row in plan)
    assert discovery.discovery_plan("Research current official government rules.", ["sam.gov"]) == [
        {"domains": ["sam.gov"], "focus": "Research current official government rules."}]


def test_queries_really_run_concurrently_and_reserve_retrieval_slots_for_each_site(monkeypatch):
    barrier = threading.Barrier(3)
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        domain = kwargs["tools"][0]["filters"]["allowed_domains"][0]
        barrier.wait(timeout=3)
        return SimpleNamespace(model_dump=lambda: payload(domain))
    options = install(monkeypatch, create)
    result = discovery.discover_sources(QUESTION, DOMAINS, local_now=NOW, deadline=time.monotonic() + 40)
    assert len(calls) == 3 and result["web_search_calls"] == 3
    assert [row["url"] for row in result["sources"]] == ["https://" + d + "/detail-" + str(i) for i in range(2) for d in DOMAINS]
    assert len(result["sources"]) == 6
    assert result["usage"]["failed_queries"] == 0 and len(result["usage"]["queries"]) == 3
    for call in calls:
        assert call["max_tool_calls"] == 1 and call["max_output_tokens"] == 600 and call["store"] is False
        assert call["include"] == ["web_search_call.action.sources"]
        assert call["tool_choice"] == "required"
        assert QUESTION not in call["instructions"]
        assert json.loads(call["input"])["original_question_context"] == QUESTION
    assert all(0 < option["timeout"] <= 20 and option["max_retries"] == 0 for option in options)


def test_one_failed_website_does_not_discard_other_valid_official_sources(monkeypatch):
    def create(**kwargs):
        domain = kwargs["tools"][0]["filters"]["allowed_domains"][0]
        if domain == "acquisition.gov":
            raise TimeoutError("fixture")
        return SimpleNamespace(model_dump=lambda: payload(domain))
    install(monkeypatch, create)
    result = discovery.discover_sources(QUESTION, DOMAINS, local_now=NOW, deadline=time.monotonic() + 40)
    assert result["usage"]["failed_queries"] == 1
    assert result["web_search_calls"] == 2  # Timeout billing/provenance is unknown, not claimed successful.
    assert {row["url"].split('/')[2] for row in result["sources"]} == {"sam.gov", "sba.gov"}


def test_provider_cannot_smuggle_sba_only_results_past_other_domain_filters(monkeypatch):
    install(monkeypatch, lambda **kwargs: SimpleNamespace(model_dump=lambda: payload("sba.gov")))
    result = discovery.discover_sources(QUESTION, DOMAINS, local_now=NOW, deadline=time.monotonic() + 40)
    assert result["usage"]["failed_queries"] == 2
    assert all(row["url"].startswith("https://sba.gov/") for row in result["sources"])
    assert result["web_search_calls"] == 3


def test_all_provider_failures_return_no_fabricated_sources(monkeypatch):
    def fail(**kwargs): raise TimeoutError("fixture")
    install(monkeypatch, fail)
    with pytest.raises(hosted_search.HostedSearchUnavailable, match="government_discovery_provider_error"):
        discovery.discover_sources(QUESTION, DOMAINS, local_now=NOW, deadline=time.monotonic() + 40)


def test_exhausted_budget_does_not_start_paid_calls(monkeypatch):
    install(monkeypatch, lambda **kwargs: pytest.fail("No calls after discovery budget is exhausted"))
    with pytest.raises(hosted_search.HostedSearchUnavailable, match="government_discovery_budget_exhausted"):
        discovery.discover_sources(QUESTION, DOMAINS, local_now=NOW, deadline=time.monotonic() + 1)
