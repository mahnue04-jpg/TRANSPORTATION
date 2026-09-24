"""Bounded Nova Work autopilot cycle tests."""
from __future__ import annotations

from types import SimpleNamespace

from app.core.nova.v3 import autopilot_cycle
from app.core.nova.v3.live_qualification import (
    OUTCOME_NEEDS_OWNER_REVIEW,
    OUTCOME_NOT_QUALIFIED,
    OUTCOME_QUALIFIED,
)


def _ranked(title: str, status: str, score: int, url: str) -> dict:
    return {
        "title": title,
        "company_name": "Example Co",
        "source_url": url,
        "provider_id": "remotive",
        "relevance_score": score,
        "qualification_status": status,
        "live_qualification": {"qualification_status": status},
    }


def test_autopilot_cycle_is_bounded_deduped_and_never_submits(monkeypatch):
    calls = []

    def fake_search(query: str, limit: int):
        calls.append((query, limit))
        return {
            "jobs": [{"query": query}],
            "providers_queried": ["remotive"],
            "provider_errors": [],
            "provider_result_counts": {"remotive": 1},
        }

    def fake_rank(query: str, jobs: list[dict]):
        return [
            _ranked("Strong admin", OUTCOME_QUALIFIED, 92, "https://example.test/1"),
            _ranked("Strong admin duplicate", OUTCOME_QUALIFIED, 91, "https://example.test/1"),
            _ranked("Needs review", OUTCOME_NEEDS_OWNER_REVIEW, 75, "https://example.test/2"),
            _ranked("Weak", OUTCOME_NOT_QUALIFIED, 20, "https://example.test/3"),
        ]

    captured = {}

    def fake_persist(db, jobs, **kwargs):
        captured["jobs"] = jobs
        captured.update(kwargs)
        return [
            {
                "work_application_id": "NWA-1",
                "ready_for_owner_review": True,
                "package_review_status": "READY",
                "externally_submitted": False,
            },
            {
                "work_application_id": None,
                "ready_for_owner_review": False,
                "package_review_status": "HELD_FOR_OWNER_REVIEW",
                "externally_submitted": False,
            },
        ]

    monkeypatch.setattr(autopilot_cycle, "search_multi_source_jobs", fake_search)
    monkeypatch.setattr(autopilot_cycle, "qualify_and_rank_live_jobs", fake_rank)
    monkeypatch.setattr(autopilot_cycle, "persist_ranked_jobs", fake_persist)

    result = autopilot_cycle.run_autopilot_cycle(
        object(),
        organization_id="org-1",
        user=SimpleNamespace(user_id="owner-1"),
        queries=["remote admin contractor"],
        query_limit=5,
        per_query_limit=50,
        save_limit=10,
        prepare_limit=5,
        min_relevance_score=60,
    )

    assert calls == [("remote admin contractor", 10)]
    assert len(captured["jobs"]) == 2
    assert captured["prepare_applications"] is True
    assert captured["prepare_limit"] == 5
    assert result["application_workspace_count"] == 1
    assert result["prepared_application_count"] == 1
    assert result["ready_for_owner_review_count"] == 1
    assert result["held_for_owner_review_count"] == 1
    assert result["external_action_taken"] is False
    assert result["external_submission"] is False
    assert result["contract_acceptance"] is False
    assert result["financial_execution"] is False
    assert result["approval_required_before_submission"] is True
    assert result["continuous_worker"] is False


def test_default_queries_spread_across_capability_families(monkeypatch):
    monkeypatch.setattr(
        autopilot_cycle,
        "generate_capability_first_queries",
        lambda: [
            {"query": "admin one", "search_family": "admin"},
            {"query": "admin two", "search_family": "admin"},
            {"query": "bookkeeping one", "search_family": "bookkeeping"},
            {"query": "research one", "search_family": "research"},
        ],
    )
    assert autopilot_cycle._default_queries(3) == [
        "admin one",
        "bookkeeping one",
        "research one",
    ]


def test_autopilot_cycle_prepare_limit_can_be_zero(monkeypatch):
    monkeypatch.setattr(
        autopilot_cycle,
        "search_multi_source_jobs",
        lambda query, limit: {
            "jobs": [],
            "providers_queried": [],
            "provider_errors": [],
            "provider_result_counts": {},
        },
    )
    monkeypatch.setattr(autopilot_cycle, "qualify_and_rank_live_jobs", lambda query, jobs: [])

    captured = {}

    def fake_persist(db, jobs, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(autopilot_cycle, "persist_ranked_jobs", fake_persist)
    result = autopilot_cycle.run_autopilot_cycle(
        object(),
        organization_id="org-1",
        user=SimpleNamespace(user_id="owner-1"),
        queries=["remote admin"],
        prepare_limit=0,
    )
    assert captured["prepare_limit"] == 0
    assert result["prepared_application_count"] == 0
    assert result["external_submission"] is False



def test_empty_specific_search_retries_with_broader_query(monkeypatch):
    calls = []

    def fake_search(query, limit):
        calls.append(query)
        if query == "remote administrative support contractor":
            return {
                "jobs": [],
                "providers_queried": ["remotive", "remoteok"],
                "provider_errors": [],
                "provider_result_counts": {"remotive": 0, "remoteok": 0},
            }
        return {
            "jobs": [{"provider_id": "remotive", "source_url": "https://example.test/job", "title": "Administrative Support", "company_name": "Buyer"}],
            "providers_queried": ["remotive", "remoteok"],
            "provider_errors": [],
            "provider_result_counts": {"remotive": 1, "remoteok": 0},
        }

    def fake_rank(query, jobs):
        assert query == "administrative support"
        return [dict(jobs[0], relevance_score=75, qualification_status="NEEDS_OWNER_REVIEW", live_qualification={"qualification_status": "NEEDS_OWNER_REVIEW"})]

    monkeypatch.setattr(autopilot_cycle, "search_multi_source_jobs", fake_search)
    monkeypatch.setattr(autopilot_cycle, "qualify_and_rank_live_jobs", fake_rank)
    monkeypatch.setattr(autopilot_cycle, "persist_ranked_jobs", lambda *args, **kwargs: [])

    result = autopilot_cycle.run_autopilot_cycle(
        object(),
        organization_id="org-1",
        user=object(),
        queries=["remote administrative support contractor"],
        query_limit=1,
        per_query_limit=5,
        min_relevance_score=60,
    )

    assert calls == ["remote administrative support contractor", "administrative support"]
    assert result["selected_count"] == 1
    assert result["per_query"][0]["used_query"] == "administrative support"
