from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

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
    assert calls[0]["tool_choice"] == "required"
    assert calls[0]["max_tool_calls"] == 1
    assert calls[0]["max_output_tokens"] == 900
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
    assert calls == list(hosted_search.PROBE_QUESTIONS)
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
