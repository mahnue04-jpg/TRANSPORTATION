"""Synthetic service tests for PostgreSQL/S3-shaped durable CSV job logic.

This uses ephemeral SQLite and an in-memory fake object store ONLY in pytest;
production runtime rejects SQLite. This is not staging or real auth evidence.
"""
from io import BytesIO

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_customer_csv_jobs as jobs


class FakePrivateStore:
    def __init__(self):
        self.objects = {}

    def store(self, *, organization_id, application_id, category,
              filename, content_type, stream):
        key = f"{organization_id}/{application_id}/{category}/{filename}"
        raw = stream.read()
        self.objects[key] = raw
        return "test_private", key, len(raw)

    def retrieve(self, *, storage_ref):
        return self.objects[storage_ref], "text/csv"

    def delete(self, *, storage_ref):
        del self.objects[storage_ref]


@pytest.fixture
def state(monkeypatch):
    eng = create_engine("sqlite:///:memory:")
    jobs.metadata.create_all(eng)
    store = FakePrivateStore()
    monkeypatch.setattr(jobs, "require_runtime", lambda db: None)
    monkeypatch.setattr(jobs, "_store", lambda: store)
    with Session(eng) as db:
        yield db, store
    eng.dispose()


def submit(db, request_key="request-a", owner="owner-a", eng="eng-a",
           content=b"Name\nAda\nAda\n"):
    return jobs.submit_review_job(
        db, org="org-a", owner=owner, engagement_id=eng,
        task_id="task-a", request_key=request_key, raw=content,
    )


def test_durable_metadata_and_review_download(state):
    db, store = state
    created = submit(db)
    assert created["status"] == "AWAITING_REVIEW"
    assert created["replayed"] is False
    assert len(store.objects) == 1
    job_id = created["job_id"]
    assert jobs.job_status(db, org="org-a", owner="owner-a", job_id=job_id)["status"] == "AWAITING_REVIEW"
    downloaded = jobs.download_review(db, org="org-a", owner="owner-a", job_id=job_id)
    assert downloaded == b"Name\nAda\n"
    review = jobs.review_job(db, org="org-a", owner="owner-a", job_id=job_id, approve=True)
    assert review["status"] == "APPROVED_FOR_DOWNLOAD"
    assert review["delivered"] is False
    assert jobs.download_review(db, org="org-a", owner="owner-a", job_id=job_id) == downloaded


def test_same_key_returns_same_job_without_reprocessing(state):
    db, store = state
    first = submit(db)
    second = submit(db)
    assert second["replayed"] is True
    assert second["job_id"] == first["job_id"]
    assert len(store.objects) == 1
    with pytest.raises(jobs.CustomerCSVBlocked, match="different work"):
        submit(db, content=b"Name\nDifferent\n")
    with pytest.raises(jobs.CustomerCSVBlocked, match="different work"):
        submit(db, eng="eng-b")
    assert len(store.objects) == 1


def test_cross_owner_reads_and_reviews_are_hidden(state):
    db, _ = state
    job_id = submit(db)["job_id"]
    with pytest.raises(jobs.CustomerCSVBlocked) as exc:
        jobs.job_status(db, org="org-a", owner="owner-b", job_id=job_id)
    assert exc.value.code == 404
    with pytest.raises(jobs.CustomerCSVBlocked):
        jobs.review_job(db, org="org-b", owner="owner-a", job_id=job_id, approve=True)
    with pytest.raises(jobs.CustomerCSVBlocked):
        jobs.download_review(db, org="org-a", owner="owner-b", job_id=job_id)


def test_rejected_artifact_is_not_downloadable(state):
    db, _ = state
    job_id = submit(db)["job_id"]
    assert jobs.review_job(db, org="org-a", owner="owner-a", job_id=job_id, approve=False)["status"] == "REJECTED"
    with pytest.raises(jobs.CustomerCSVBlocked):
        jobs.download_review(db, org="org-a", owner="owner-a", job_id=job_id)


def test_artifact_integrity_mismatch_blocks_download(state):
    db, store = state
    job_id = submit(db)["job_id"]
    key = next(iter(store.objects))
    store.objects[key] = b"tampered"
    with pytest.raises(jobs.CustomerCSVBlocked, match="integrity"):
        jobs.download_review(db, org="org-a", owner="owner-a", job_id=job_id)


def test_storage_error_marks_job_failed_without_fake_success(state, monkeypatch):
    db, _ = state

    class BrokenStore:
        def store(self, **kwargs):
            raise RuntimeError("simulated private-store failure")

    monkeypatch.setattr(jobs, "_store", lambda: BrokenStore())
    with pytest.raises(RuntimeError):
        submit(db)
    row = db.execute(jobs.sa.select(jobs.jobs.c.status)).scalar_one()
    assert row == "FAILED"


def test_disabled_runtime_fails_closed_before_any_job_insert(state, monkeypatch):
    db, _ = state
    monkeypatch.undo()
    with pytest.raises(jobs.CustomerCSVBlocked) as exc:
        submit(db)
    assert exc.value.code == 503
    count = db.execute(jobs.sa.select(jobs.sa.func.count()).select_from(jobs.jobs)).scalar_one()
    assert count == 0
