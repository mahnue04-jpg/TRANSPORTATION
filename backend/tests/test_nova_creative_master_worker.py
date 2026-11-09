"""Dedicated master worker isolation tests; no media, provider or network calls."""
from types import SimpleNamespace

from app.core.nova.creative_studio import master_worker


class _Query:
    def __init__(self, claims):
        self.claims = claims

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def limit(self, _limit):
        return self

    def all(self):
        return self.claims


class _Session:
    def __init__(self, claims):
        self.claims = claims

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def query(self, *_args):
        return _Query(self.claims)


def test_dedicated_worker_continues_after_independent_job_exception(monkeypatch):
    jobs = [
        SimpleNamespace(owner_id="a", project_id="one", entry_id="entry",
                        job_id="job-1"),
        SimpleNamespace(owner_id="b", project_id="two", entry_id="entry",
                        job_id="job-2"),
    ]
    monkeypatch.setattr(master_worker, "_stop", False)
    monkeypatch.setattr(master_worker, "SessionLocal", lambda: _Session(jobs))
    seen = []

    def runner(owner_id, project_id, entry_id, job_id):
        seen.append(job_id)
        if job_id == "job-1":
            raise RuntimeError("simulated recoverable worker exception")

    monkeypatch.setattr(master_worker, "_run_chapter_master_job", runner)
    assert master_worker.run_one_queued() is True
    assert seen == ["job-1", "job-2"]


def test_dedicated_worker_does_not_process_when_stopping(monkeypatch):
    jobs = [SimpleNamespace(owner_id="a", project_id="one",
                            entry_id="entry", job_id="job-1")]
    monkeypatch.setattr(master_worker, "_stop", True)
    monkeypatch.setattr(master_worker, "SessionLocal", lambda: _Session(jobs))
    seen = []
    monkeypatch.setattr(master_worker, "_run_chapter_master_job",
                        lambda *args: seen.append(args))
    assert master_worker.run_one_queued() is False
    assert seen == []


def test_dedicated_worker_does_not_claim_when_no_jobs(monkeypatch):
    monkeypatch.setattr(master_worker, "_stop", False)
    monkeypatch.setattr(master_worker, "SessionLocal", lambda: _Session([]))
    assert master_worker.run_one_queued() is False
