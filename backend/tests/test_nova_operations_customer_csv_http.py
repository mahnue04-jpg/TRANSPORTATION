"""Synthetic HTTP coverage of durable owner CSV operations.

No real auth is claimed: auth dependencies are replaced by test identities.
No live S3, customer records, production DB or paid resources are used.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.nova.router import require_nova_access
from app.core.nova.work_revenue import operations_owner_csv_api as api
from app.core.nova.work_revenue import operations_customer_csv_jobs as jobs
from app.core.nova.work_revenue.router import require_work_revenue_owner
from app.db.session import get_db


class MemoryStore:
    def __init__(self):
        self.objects = {}

    def store(self, *, organization_id, application_id, category, filename,
              content_type, stream):
        key = f"{organization_id}/{application_id}/{filename}"
        content = stream.read()
        self.objects[key] = content
        return "synthetic", key, len(content)

    def retrieve(self, *, storage_ref):
        return self.objects[storage_ref], "text/csv"

    def delete(self, *, storage_ref):
        del self.objects[storage_ref]


@pytest.fixture
def harness(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=__import__("sqlalchemy").pool.StaticPool)
    jobs.metadata.create_all(engine)
    store = MemoryStore()
    monkeypatch.setattr(jobs, "require_runtime", lambda db: None)
    monkeypatch.setattr(jobs, "_store", lambda: store)
    eng = {
        "engagement_id": "eng-a", "organization_id": "org-a",
        "owner_user_id": "owner-a", "status": "ACTIVE",
        "blockers": None, "tasks": [{
            "task_id": "task-a", "title": "CSV cleanup",
            "status": "READY", "classification": "NOVA",
            "responsible_party": "NOVA", "review_required": True,
            "required_owner_input": None, "blocked_reason": None,
            "depends_on_task_id": None,
        }],
    }
    monkeypatch.setattr(api.service, "get_engagement", lambda *a, **kw: eng)
    owner = SimpleNamespace(user_id="owner-a", organization_id="org-a")
    app = FastAPI()
    app.include_router(api.router, prefix="/api/nova/work")
    app.dependency_overrides[require_nova_access] = lambda: owner
    app.dependency_overrides[require_work_revenue_owner] = lambda: owner
    def db_session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = db_session
    with TestClient(app) as client:
        yield client, eng, store, owner
    engine.dispose()


def create(client, *, key="req-a", body=b"Name\nAda\nAda\n", headers=None):
    sent = {
        "Content-Type": "text/csv",
        "X-Nova-File-Name": "test.csv",
        "Idempotency-Key": key,
        "X-Nova-Scope-Confirmed": "owner-confirmed-client-authorization",
    }
    if headers:
        sent.update(headers)
    return client.post(
        "/api/nova/work/operations/durable/engagements/eng-a/tasks/task-a/jobs",
        headers=sent, content=body,
    )


def test_create_status_review_download_and_replay(harness):
    client, _, store, _ = harness
    created = create(client)
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    assert created.json()["status"] == "AWAITING_REVIEW"
    repeat = create(client)
    assert repeat.status_code == 202
    assert repeat.json()["job_id"] == job_id
    assert repeat.json()["replayed"] is True
    assert len(store.objects) == 1
    status = client.get(f"/api/nova/work/operations/durable/jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "AWAITING_REVIEW"
    download = client.get(f"/api/nova/work/operations/durable/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.content == b"Name\nAda\n"
    assert download.headers["X-Nova-Delivery-Status"] == "not-delivered"
    approved = client.post(
        f"/api/nova/work/operations/durable/jobs/{job_id}/review",
        json={"approve": True},
    )
    assert approved.status_code == 200
    assert approved.json()["delivered"] is False


def test_owner_revocation_blocks_status_review_and_download(harness):
    client, eng, _, _ = harness
    job_id = create(client).json()["job_id"]
    eng["status"] = "BLOCKED"
    for path, method in [
        (f"/api/nova/work/operations/durable/jobs/{job_id}", "get"),
        (f"/api/nova/work/operations/durable/jobs/{job_id}/download", "get"),
        (f"/api/nova/work/operations/durable/jobs/{job_id}/review", "post"),
    ]:
        result = getattr(client, method)(
            path, **({"json": {"approve": True}} if method == "post" else {})
        )
        assert result.status_code == 409


def test_missing_auth_confirmation_and_wrong_work_type_rejected(harness):
    client, eng, _, _ = harness
    assert create(client, headers={"X-Nova-Scope-Confirmed": "no"}).status_code == 403
    eng["tasks"][0]["title"] = "Research market"
    assert create(client, key="req-new").status_code == 409


def test_invalid_file_and_idempotency_conflict(harness):
    client, _, _, _ = harness
    assert create(client, headers={"Content-Type": "application/json"}).status_code == 415
    assert create(client, headers={"X-Nova-File-Name": "../bad.csv"}).status_code == 400
    assert create(client, body=b"X" * 1000001).status_code == 413
    assert create(client).status_code == 202
    assert create(client, body=b"Name\nOther\n").status_code == 409


def test_saved_history_reopens_authorized_job(harness):
    client, _, _, _ = harness
    first = create(client, key="history-one").json()["job_id"]
    second = create(client, key="history-two").json()["job_id"]
    response = client.get("/api/nova/work/operations/durable/jobs")
    assert response.status_code == 200
    payload = response.json()
    assert payload["owner_only"] is True
    assert payload["count"] == 2
    assert {row["job_id"] for row in payload["jobs"]} == {first, second}
    assert all("output_ref" not in row and "input_sha256" not in row for row in payload["jobs"])
    assert client.get(f"/api/nova/work/operations/durable/jobs/{first}").status_code == 200
    assert client.get("/api/nova/work/operations/durable/jobs?limit=0").status_code == 400


def test_saved_history_is_hidden_after_assignment_revocation(harness):
    client, engagement, _, _ = harness
    job_id = create(client, key="history-revoke").json()["job_id"]
    assert client.get("/api/nova/work/operations/durable/jobs").json()["count"] == 1
    engagement["status"] = "BLOCKED"
    history = client.get("/api/nova/work/operations/durable/jobs")
    assert history.status_code == 200
    assert history.json()["jobs"] == []
    assert client.get(f"/api/nova/work/operations/durable/jobs/{job_id}").status_code == 409


def test_assignment_revoked_during_upload_never_reserves_job(harness, monkeypatch):
    """Recheck task authorization after reading input, before writing storage."""
    client, eng, store, _ = harness
    checks = {"count": 0}

    def changing_engagement(*args, **kwargs):
        checks["count"] += 1
        if checks["count"] >= 2:
            eng["status"] = "BLOCKED"
        return eng

    monkeypatch.setattr(api.service, "get_engagement", changing_engagement)
    response = create(client, key="revoked-during-upload")
    assert response.status_code == 409
    assert checks["count"] >= 2
    assert store.objects == {}
    # The task became blocked before processing, so no job may be created.
    eng["status"] = "ACTIVE"
    response = client.get("/api/nova/work/operations/durable/jobs")
    assert response.status_code == 200
    assert response.json()["jobs"] == []
