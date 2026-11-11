"""End-to-end HTTP simulation of Nova's supervised accounting task.

Synthetic owner authentication and contract authorization are injected ONLY in
this test. SQLite and fake object storage are used; no real client permissions,
PostgreSQL/S3, external communications or production settings are involved.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.nova.router import require_nova_access
from app.core.nova.work_revenue.owner_auth import require_work_revenue_owner
from app.core.nova.work_revenue import operations_owner_csv_api as api
from app.core.nova.work_revenue import operations_customer_csv_jobs as durable
from app.core.nova.work_revenue.bookkeeping_assignment import BookkeepingAssignment
from app.core.nova.work_revenue.bookkeeping_scope import ConsentNotVerified
from app.db.session import get_db


class FakePrivateStorage:
    def __init__(self):
        self.objects = {}

    def store(self, *, organization_id, application_id, category,
              filename, content_type, stream):
        assert category == "nova-bookkeeping-review"
        key = f"{organization_id}/{application_id}/{category}/{filename}"
        data = stream.read()
        self.objects[key] = data
        return "synthetic-only", key, len(data)

    def retrieve(self, *, storage_ref):
        return self.objects[storage_ref], "text/csv"

    def delete(self, *, storage_ref):
        del self.objects[storage_ref]


@pytest.fixture
def demo(monkeypatch):
    db_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    durable.metadata.create_all(db_engine)
    store = FakePrivateStorage()
    access = {"active": True}
    user = SimpleNamespace(organization_id="test-org", user_id="test-owner")

    def current_owner():
        return user

    def test_db():
        with Session(db_engine) as db:
            yield db

    def verified_assignment(db, *, owner, engagement_id, task_id, work_type, lock_consent=False):
        if (
            not access["active"]
            or owner.organization_id != "test-org"
            or owner.user_id != "test-owner"
            or engagement_id != "test-engagement"
            or task_id != "test-task"
            or work_type != "receivables_aging"
        ):
            raise ConsentNotVerified("Synthetic authorization absent or revoked")
        return BookkeepingAssignment(
            organization_id="test-org", owner_user_id="test-owner",
            engagement_id="test-engagement", task_id="test-task",
            work_type="receivables_aging", ai_assistance_permitted=True,
            data_processing_authorized=True, human_review_required=True,
            contracted_work_types=frozenset({"receivables_aging"}),
        )

    monkeypatch.setenv("NOVA_BOOKKEEPING_DURABLE_ENABLED", "true")
    monkeypatch.setattr(durable, "require_runtime", lambda db: None)
    monkeypatch.setattr(durable, "_store", lambda: store)
    monkeypatch.setattr(api, "resolve_bookkeeping_assignment", verified_assignment)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[require_nova_access] = current_owner
    app.dependency_overrides[require_work_revenue_owner] = current_owner
    app.dependency_overrides[get_db] = test_db

    with TestClient(app) as client:
        yield client, access, user, store
    db_engine.dispose()


BASE = "/operations/durable/bookkeeping"
SUBMIT = BASE + "/engagements/test-engagement/tasks/test-task/receivables_aging/jobs"
CSV = (
    b"invoice_id,customer,invoice_date,due_date,amount,paid\n"
    b"INV-001,Invented Client,2026-10-01,2026-10-31,100.00,25.00\n"
)
HEADERS = {
    "Idempotency-Key": "synthetic-http-1",
    "X-Nova-File-Name": "invented.csv",
    "X-Nova-As-Of": "2026-11-11",
    "Content-Type": "text/csv",
}


def test_full_synthetic_http_workflow(demo):
    client, access, user, store = demo
    created = client.post(SUBMIT, content=CSV, headers=HEADERS)
    assert created.status_code == 202, created.text
    data = created.json()
    assert data["status"] == "AWAITING_REVIEW"
    assert data["delivery_allowed"] is False
    assert not data["delivered"]
    job_id = data["job_id"]

    # Same request must reuse the existing stored task and not process twice.
    again = client.post(SUBMIT, content=CSV, headers=HEADERS)
    assert again.status_code == 202
    assert again.json()["job_id"] == job_id
    assert again.json()["replayed"] is True
    assert len(store.objects) == 1

    status = client.get(f"{BASE}/jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["work_type"] == "receivables_aging"

    # Simulate a different signed-in owner, not a changed HTTP header.
    user.user_id = "different-owner"
    for method, path, kwargs in (
        ("get", f"{BASE}/jobs/{job_id}", {}),
        ("post", f"{BASE}/jobs/{job_id}/review", {"json": {"approve": True}}),
        ("get", f"{BASE}/jobs/{job_id}/download", {}),
        ("post", f"{BASE}/jobs/{job_id}/recover", {}),
    ):
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code in (403, 404), (method, path, response.text)
    user.user_id = "test-owner"

    # Synthetic consent revocation must block even the owner from accessing
    # an artifact previously prepared under active authorization.
    access["active"] = False
    for method, path, kwargs in (
        ("get", f"{BASE}/jobs/{job_id}", {}),
        ("post", f"{BASE}/jobs/{job_id}/review", {"json": {"approve": True}}),
        ("get", f"{BASE}/jobs/{job_id}/download", {}),
        ("post", f"{BASE}/jobs/{job_id}/recover", {}),
    ):
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 403, (method, response.text)
    denied_new_job = client.post(
        SUBMIT, content=CSV, headers={**HEADERS, "Idempotency-Key": "new-request"},
    )
    assert denied_new_job.status_code == 403
    access["active"] = True

    review_file = client.get(f"{BASE}/jobs/{job_id}/download")
    assert review_file.status_code == 200
    assert b"75.00" in review_file.content
    assert "no-store" in review_file.headers["cache-control"]
    assert review_file.headers["x-nova-delivery-status"] == "not-delivered"

    approved = client.post(f"{BASE}/jobs/{job_id}/review", json={"approve": True})
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED_FOR_DOWNLOAD"
    assert approved.json()["delivered"] is False
    assert client.get(f"{BASE}/jobs/{job_id}/download").content == review_file.content


def test_consent_revoked_during_upload_is_denied_before_job_creation(demo, monkeypatch):
    client, access, user, store = demo
    original = api.resolve_bookkeeping_assignment
    calls = {"count": 0}

    def permission_flips_after_first_check(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            access["active"] = False
        return original(*args, **kwargs)

    monkeypatch.setattr(api, "resolve_bookkeeping_assignment", permission_flips_after_first_check)
    denied = client.post(SUBMIT, content=CSV, headers=HEADERS)
    assert denied.status_code == 403
    assert calls["count"] == 2
    assert store.objects == {}


def test_consent_revoked_during_private_write_never_publishes_review_job(demo, monkeypatch):
    client, access, user, store = demo
    normal_store = store.store

    def revoke_when_artifact_is_written(**kwargs):
        result = normal_store(**kwargs)
        access["active"] = False
        return result

    monkeypatch.setattr(store, "store", revoke_when_artifact_is_written)
    response = client.post(
        SUBMIT, content=CSV,
        headers={**HEADERS, "Idempotency-Key": "revoked-during-storage"},
    )
    assert response.status_code == 403, response.text
    # A rejected finalization must not expose a reviewable file.
    assert store.objects == {}
    access["active"] = True
    # No successful result may be replayed under the rejected request key.
    retry = client.post(
        SUBMIT, content=CSV,
        headers={**HEADERS, "Idempotency-Key": "revoked-during-storage"},
    )
    assert retry.status_code == 202
    assert retry.json()["status"] == "FAILED"
    assert retry.json()["delivered"] is False
