from __future__ import annotations

import pytest

from app.core.nova.v3 import live_discovery
from app.core.nova.v3.errors import V3Error


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {
            "jobs": [
                {
                    "id": 123,
                    "url": "https://remotive.com/remote-jobs/test-job-123",
                    "title": "Remote Operations Assistant",
                    "company_name": "Example Co",
                    "description": "<p>Prepare reports &amp; coordinate tasks.</p>",
                    "candidate_required_location": "USA",
                    "salary": "$50,000",
                    "job_type": "full_time",
                    "publication_date": "2026-09-19T00:00:00",
                }
            ]
        }


class _Client:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, *args, **kwargs):
        return _Response()


def test_live_job_search_requires_explicit_flag(monkeypatch):
    monkeypatch.setattr(live_discovery, "live_flags", lambda: {"LIVE_DISCOVERY_ENABLED": False})
    with pytest.raises(V3Error) as exc:
        live_discovery.search_remote_jobs("operations")
    assert exc.value.code == "LIVE_DISABLED"


def test_live_job_search_normalizes_remotive_results(monkeypatch):
    live_discovery._cache.clear()
    monkeypatch.setattr(live_discovery, "live_flags", lambda: {"LIVE_DISCOVERY_ENABLED": True})
    monkeypatch.setattr(live_discovery.httpx, "Client", _Client)

    jobs = live_discovery.search_remote_jobs("operations", limit=5)

    assert len(jobs) == 1
    assert jobs[0]["provider_id"] == "remotive"
    assert jobs[0]["title"] == "Remote Operations Assistant"
    assert jobs[0]["company_name"] == "Example Co"
    assert jobs[0]["description"] == "Prepare reports & coordinate tasks."
    assert jobs[0]["source_attribution"] == "Remotive"
    assert jobs[0]["source_url"].startswith("https://remotive.com/")


def test_rank_live_jobs_prioritizes_title_match():
    jobs = [
        {
            "title": "Senior Data Scientist",
            "company_name": "A",
            "description": "Remote analytics role",
            "geography": "Worldwide",
            "publication_date": "2026-09-19",
        },
        {
            "title": "Remote Operations Assistant",
            "company_name": "B",
            "description": "Coordinate operations and reports",
            "geography": "USA",
            "publication_date": "2026-09-18",
        },
    ]

    ranked = live_discovery.rank_live_jobs("remote operations assistant", jobs)

    assert ranked[0]["title"] == "Remote Operations Assistant"
    assert ranked[0]["relevance_score"] > ranked[1]["relevance_score"]
    assert ranked[0]["relevance_explanation"]["title_hits"] >= 2


def test_rank_live_jobs_prefers_title_match():
    jobs = [
        {
            "title": "Senior Data Scientist",
            "company_name": "Data Co",
            "description": "Remote operations analytics and reporting.",
            "geography": "Worldwide",
            "publication_date": "2026-09-19T00:00:00",
        },
        {
            "title": "Remote Operations Assistant",
            "company_name": "Office Co",
            "description": "Coordinate schedules and prepare reports.",
            "geography": "Worldwide",
            "publication_date": "2026-09-18T00:00:00",
        },
    ]

    ranked = live_discovery.rank_live_jobs("remote operations assistant", jobs)

    assert ranked[0]["title"] == "Remote Operations Assistant"
    assert ranked[0]["relevance_score"] > ranked[1]["relevance_score"]


def test_live_job_ingest_marks_opportunity_live(monkeypatch):
    from app.core.nova.v3.kernel import NovaV3Kernel

    kernel = NovaV3Kernel()
    monkeypatch.setattr(
        "app.core.nova.v3.kernel.live_flags",
        lambda: {"LIVE_DISCOVERY_ENABLED": True},
    )

    saved = kernel.ingest_live_jobs(
        [
            {
                "provider_id": "remotive",
                "provider_identifier": "123",
                "title": "Remote Operations Assistant",
                "company_name": "Example Co",
                "description": "Prepare reports and coordinate tasks.",
                "source_url": "https://remotive.com/remote-jobs/example-123",
                "geography": "USA",
                "remote_status": "remote",
                "source_attribution": "Remotive",
            }
        ],
        organization_id="org-owner",
        owner_user_id="owner-1",
    )

    assert len(saved["created"]) == 1
    row = saved["created"][0]
    assert row["provider_id"] == "remotive"
    assert row["live_discovery"] is True
    assert row["provenance"]["live"] is True
    assert row["provenance"]["synthetic"] is False
    assert row["status"] == "LEAD"


def test_live_job_ingest_deduplicates(monkeypatch):
    from app.core.nova.v3.kernel import NovaV3Kernel

    kernel = NovaV3Kernel()
    monkeypatch.setattr(
        "app.core.nova.v3.kernel.live_flags",
        lambda: {"LIVE_DISCOVERY_ENABLED": True},
    )
    job = {
        "provider_id": "remotive",
        "provider_identifier": "same-123",
        "title": "Remote Operations Assistant",
        "company_name": "Example Co",
        "description": "Prepare reports and coordinate tasks.",
        "source_url": "https://remotive.com/remote-jobs/example-123",
        "geography": "USA",
        "remote_status": "remote",
        "source_attribution": "Remotive",
    }

    first = kernel.ingest_live_jobs([job], organization_id="org-owner", owner_user_id="owner-1")
    second = kernel.ingest_live_jobs([job], organization_id="org-owner", owner_user_id="owner-1")

    assert len(first["created"]) == 1
    assert second["created"] == []
    assert len(second["duplicates"]) == 1
