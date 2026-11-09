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


def test_dedicated_mode_queues_sql_without_web_process_marker(monkeypatch):
    """Queued dedicated work is tracked in SQL, not a permanent web-process set."""
    import json
    from app.core.nova.creative_studio import calendar as studio
    from app.core.nova.creative_studio import private_object_storage as remote

    monkeypatch.setenv("NOVA_STUDIO_MASTER_WORKER_ENABLED", "true")
    monkeypatch.setattr(remote, "enabled", lambda: True)
    monkeypatch.setattr(studio, "_project", lambda *args: None)
    monkeypatch.setattr(studio, "_entry", lambda *args: SimpleNamespace(
        status="approved", duration_seconds=600,
        chapters_json=json.dumps([{}, {}]),
    ))
    monkeypatch.setattr(studio, "_master_export_limit_seconds", lambda: 3600)
    sha = "a" * 64
    monkeypatch.setattr(studio, "_chapter_rebuild_plan", lambda *args: {
        "master_ready": True, "version_sha256": sha,
        "chapters": [
            {"chapter_index": n, "asset_id": "asset-" + str(n),
             "asset_sha256": sha, "quality_review": {"status": "REVIEW_PASSED"}}
            for n in range(2)
        ],
    })

    class Store:
        def list_jobs(self, *_args):
            return []

        def save_job(self, job):
            return job

    monkeypatch.setattr(studio, "DbCreativeStudioStore", lambda db: Store())

    class DB:
        def __init__(self):
            self.saved_claims = []

        def get(self, *_args):
            return None

        def add(self, claim):
            self.saved_claims.append(claim)

        def flush(self):
            pass

    class Background:
        def __init__(self):
            self.tasks = []

        def add_task(self, *args):
            self.tasks.append(args)

    db = DB()
    background = Background()
    key = ("owner", "project", "entry")
    studio._master_export_active.discard(key)
    try:
        result = studio.start_chapter_master_job(
            "project", "entry", background,
            SimpleNamespace(user_id="owner"), db
        )
        assert result["status"] == "QUEUED"
        assert background.tasks == []
        assert key not in studio._master_export_active
        assert len(db.saved_claims) == 1
        assert db.saved_claims[0].state == "QUEUED"
    finally:
        studio._master_export_active.discard(key)


def test_dedicated_worker_backs_off_if_all_jobs_raise(monkeypatch):
    jobs = [SimpleNamespace(owner_id="a", project_id="one",
                            entry_id="entry", job_id="job-1")]
    monkeypatch.setattr(master_worker, "_stop", False)
    monkeypatch.setattr(master_worker, "SessionLocal", lambda: _Session(jobs))

    def always_raise(*args):
        raise RuntimeError("simulated unavailable database resource")

    monkeypatch.setattr(master_worker, "_run_chapter_master_job", always_raise)
    # False tells main() to take its configured poll delay.
    assert master_worker.run_one_queued() is False
