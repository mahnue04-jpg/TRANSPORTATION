"""Synthetic private bookkeeping job lifecycle; not customer staging evidence."""
import hashlib

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import bookkeeping_durable_jobs as finance
from app.core.nova.work_revenue import operations_customer_csv_jobs as jobs
from app.core.nova.work_revenue.bookkeeping_assignment import BookkeepingAssignment


class PrivateStore:
    def __init__(self):
        self.objects = {}
    def store(self, *, organization_id, application_id, category,
              filename, content_type, stream):
        assert category == "nova-bookkeeping-review"
        assert content_type == "text/csv"
        name = f"{organization_id}/{application_id}/{category}/{filename}"
        contents = stream.read()
        self.objects[name] = contents
        return "test", name, len(contents)
    def retrieve(self, *, storage_ref):
        return self.objects[storage_ref], "text/csv"
    def delete(self, *, storage_ref):
        del self.objects[storage_ref]


@pytest.fixture
def state(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    jobs.metadata.create_all(engine)
    storage = PrivateStore()
    monkeypatch.setattr(jobs, "require_runtime", lambda session: None)
    monkeypatch.setattr(jobs, "_store", lambda: storage)
    monkeypatch.setenv("NOVA_BOOKKEEPING_DURABLE_ENABLED", "true")
    with Session(engine) as db:
        yield db, storage
    engine.dispose()


def assignment(**overrides):
    values = dict(
        organization_id="org-a", owner_user_id="owner-a",
        engagement_id="eng-a", task_id="task-a",
        work_type="receivables_aging", ai_assistance_permitted=True,
        data_processing_authorized=True, human_review_required=True,
        contracted_work_types=frozenset({"receivables_aging"}),
    )
    values.update(overrides)
    return BookkeepingAssignment(**values)


CSV = b"invoice_id,customer,invoice_date,due_date,amount,paid\nA1,Client A,2026-11-01,2026-11-10,100.00,20.00\n"


def submit(db, **kwargs):
    options = dict(assignment=assignment(), request_id="req-1", primary=CSV,
                   as_of="2026-11-11")
    options.update(kwargs)
    return finance.submit_bookkeeping_review(db, **options)


def test_review_lifecycle_without_delivery(state):
    db, store = state
    created = submit(db)
    assert created["status"] == "AWAITING_REVIEW"
    assert created["delivered"] is False
    job_id = created["job_id"]
    content = finance.download_bookkeeping(
        db, org="org-a", owner="owner-a", job_id=job_id)
    assert b"80.00" in content
    assert hashlib.sha256(content).hexdigest() == created["output_sha256"]
    assert len(store.objects) == 1
    assert finance.bookkeeping_status(
        db, org="org-a", owner="owner-a", job_id=job_id)["status"] == "AWAITING_REVIEW"
    approved = finance.review_bookkeeping(
        db, org="org-a", owner="owner-a", job_id=job_id, approve=True)
    assert approved["status"] == "APPROVED_FOR_DOWNLOAD"
    assert approved["delivered"] is False


def test_idempotent_request_and_scope_collision(state):
    db, store = state
    first = submit(db)
    replay = submit(db)
    assert replay["replayed"] is True
    assert replay["job_id"] == first["job_id"]
    assert len(store.objects) == 1
    with pytest.raises(finance.BookkeepingJobBlocked, match="different work"):
        submit(db, assignment=assignment(task_id="task-b"))
    with pytest.raises(finance.BookkeepingJobBlocked, match="different work"):
        submit(db, primary=CSV.replace(b"100.00", b"200.00"))


def test_other_owner_cannot_read_review_or_download(state):
    db, _ = state
    job_id = submit(db)["job_id"]
    for call in (
        lambda: finance.bookkeeping_status(db, org="org-a", owner="owner-b", job_id=job_id),
        lambda: finance.review_bookkeeping(db, org="org-b", owner="owner-a", job_id=job_id, approve=True),
        lambda: finance.download_bookkeeping(db, org="org-a", owner="owner-b", job_id=job_id),
    ):
        with pytest.raises(jobs.CustomerCSVBlocked):
            call()


def test_csv_endpoints_cannot_read_or_review_accounting_jobs(state):
    db, _ = state
    jid = submit(db)["job_id"]
    for call in (
        lambda: jobs.job_status(db, org="org-a", owner="owner-a", job_id=jid),
        lambda: jobs.review_job(db, org="org-a", owner="owner-a", job_id=jid, approve=True),
        lambda: jobs.download_review(db, org="org-a", owner="owner-a", job_id=jid),
        lambda: jobs.recover_stale_job(db, org="org-a", owner="owner-a", job_id=jid),
    ):
        with pytest.raises(jobs.CustomerCSVBlocked):
            call()


def test_non_bookkeeping_job_is_unavailable(state):
    db, _ = state
    legacy = jobs.submit_review_job(
        db, org="org-a", owner="owner-a", engagement_id="eng-a",
        task_id="task-a", request_key="legacy-1", raw=b"Name\nAda\n")
    with pytest.raises(finance.BookkeepingJobBlocked) as err:
        finance.download_bookkeeping(db, org="org-a", owner="owner-a", job_id=legacy["job_id"])
    assert err.value.code == 404


def test_rejects_unapproved_ai_and_invalid_csv_before_db_write(state):
    db, store = state
    with pytest.raises(finance.BookkeepingJobBlocked):
        submit(db, assignment=assignment(ai_assistance_permitted=False))
    with pytest.raises(finance.BookkeepingJobBlocked):
        submit(db, primary=b"malformed")
    assert len(store.objects) == 0
    assert db.execute(select(jobs.sa.func.count()).select_from(jobs.jobs)).scalar_one() == 0


def test_rejected_job_and_tampering(state):
    db, store = state
    jid = submit(db)["job_id"]
    key = next(iter(store.objects))
    store.objects[key] = b"tampered"
    with pytest.raises(finance.BookkeepingJobBlocked, match="integrity"):
        finance.download_bookkeeping(db, org="org-a", owner="owner-a", job_id=jid)
    finance.review_bookkeeping(db, org="org-a", owner="owner-a", job_id=jid, approve=False)
    with pytest.raises(finance.BookkeepingJobBlocked):
        finance.download_bookkeeping(db, org="org-a", owner="owner-a", job_id=jid)


def test_storage_failure_does_not_claim_completion(state, monkeypatch):
    db, _ = state
    class BrokenStore:
        def store(self, **kwargs):
            raise RuntimeError("synthetic failure")
    monkeypatch.setattr(jobs, "_store", lambda: BrokenStore())
    with pytest.raises(RuntimeError):
        submit(db)
    assert db.execute(select(jobs.jobs.c.status)).scalar_one() == "FAILED"


def test_runtime_default_off(state, monkeypatch):
    db, _ = state
    monkeypatch.delenv("NOVA_BOOKKEEPING_DURABLE_ENABLED")
    with pytest.raises(finance.BookkeepingJobBlocked, match="disabled"):
        submit(db)
    assert db.execute(select(jobs.sa.func.count()).select_from(jobs.jobs)).scalar_one() == 0
