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
