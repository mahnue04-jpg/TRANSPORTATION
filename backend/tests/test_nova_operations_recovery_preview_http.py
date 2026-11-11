"""Owner-controlled staging-preview HTTP rehearsal; entirely synthetic."""
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.nova.router import require_nova_access
from app.core.nova.work_revenue import operations_owner_csv_api as api
from app.core.nova.work_revenue import operations_recoverable_csv as recovery
from app.core.nova.work_revenue.owner_auth import require_work_revenue_owner
from app.db.session import get_db


class MemoryStore:
    def __init__(self):
        self.objects = {}
        self.counter = 0

    def store(self, *, organization_id, application_id, category, filename,
              content_type, stream):
        self.counter += 1
        key = f"{organization_id}/{application_id}/{category}/{self.counter}"
        data = stream.read()
        self.objects[key] = data
        return "test-private", key, len(data)

    def retrieve(self, *, storage_ref):
        return self.objects[storage_ref], "text/csv"

    def delete(self, *, storage_ref):
        self.objects.pop(storage_ref, None)


@pytest.fixture
def preview(monkeypatch):
    engine = sa.create_engine("sqlite://",
                              connect_args={"check_same_thread": False},
                              poolclass=sa.pool.StaticPool)
    recovery.metadata.create_all(engine)
    store = MemoryStore()
    monkeypatch.setattr(recovery, "require_runtime", lambda db: None)
    monkeypatch.setattr(recovery, "_store", lambda: store)
    engagement = {
        "engagement_id": "eng-a", "organization_id": "org-a",
        "owner_user_id": "owner-a", "status": "ACTIVE", "blockers": None,
        "tasks": [{
            "task_id": "task-a", "title": "CSV cleanup",
            "status": "READY", "classification": "NOVA",
            "responsible_party": "NOVA", "review_required": True,
            "required_owner_input": None, "blocked_reason": None,
            "depends_on_task_id": None,
        }],
    }
    monkeypatch.setattr(api.service, "get_engagement", lambda *a, **kw: engagement)
    monkeypatch.setattr(api.service, "list_engagements", lambda *a, **kw: [engagement])
    owner = SimpleNamespace(organization_id="org-a", user_id="owner-a")
    app = FastAPI()
    app.include_router(api.router, prefix="/api/nova/work")
    app.dependency_overrides[require_nova_access] = lambda: owner
    app.dependency_overrides[require_work_revenue_owner] = lambda: owner

    def test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as client:
        yield client, engagement, store
    engine.dispose()


def create(client, *, key="recovery-job"):
    return client.post(
        "/api/nova/work/operations/recovery-preview/engagements/eng-a/tasks/task-a/jobs",
        headers={
            "Content-Type": "text/csv",
            "X-Nova-File-Name": "example.csv",
            "X-Nova-Scope-Confirmed": "owner-confirmed-client-authorization",
            "Idempotency-Key": key,
        },
        content=b"Name\nAda\nAda\n",
    )


def test_recovery_preview_owner_roundtrip(preview):
    client, _, store = preview
    created = create(client)
    assert created.status_code == 202, created.text
    job = created.json()
    assert job["status"] == "QUEUED"
    assert create(client).json()["job_id"] == job["job_id"]
    base = f"/api/nova/work/operations/recovery-preview/jobs/{job['job_id']}"
    assert client.get(base).json()["status"] == "QUEUED"
    assert client.post(base + "/process").json()["status"] == "AWAITING_REVIEW"
    download = client.get(base + "/download")
    assert download.status_code == 200
    assert download.content == b"Name\nAda\n"
    assert download.headers["X-Nova-Delivery-Status"] == "not-delivered"
    decision = client.post(base + "/review", json={"approve": True})
    assert decision.status_code == 200
    assert decision.json()["status"] == "APPROVED_FOR_DOWNLOAD"
    assert decision.json()["delivered"] is False
    assert client.post(base + "/review", json={"approve": False}).status_code == 409
    assert client.get(base + "/download").content == b"Name\nAda\n"
    assert len(store.objects) == 2


def test_revocation_blocks_owner_rehearsal(preview):
    client, engagement, _ = preview
    job_id = create(client, key="revoke").json()["job_id"]
    engagement["status"] = "BLOCKED"
    base = f"/api/nova/work/operations/recovery-preview/jobs/{job_id}"
    assert client.get(base).status_code == 409
    assert client.post(base + "/process").status_code == 409
    assert client.get(base + "/download").status_code == 409


def test_recovery_preview_rejected_output_cannot_be_downloaded(preview):
    client, _, _ = preview
    job_id = create(client, key="rejected").json()["job_id"]
    base = f"/api/nova/work/operations/recovery-preview/jobs/{job_id}"
    assert client.post(base + "/process").status_code == 200
    result = client.post(base + "/review", json={"approve": False})
    assert result.status_code == 200
    assert result.json()["status"] == "REJECTED"
    assert client.get(base + "/download").status_code == 409


def test_recovery_preview_history_is_owner_scoped_and_revocable(preview):
    client, engagement, _ = preview
    first = create(client, key="history-a").json()["job_id"]
    second = create(client, key="history-b").json()["job_id"]
    history_url = "/api/nova/work/operations/recovery-preview/jobs"
    response = client.get(history_url)
    assert response.status_code == 200
    payload = response.json()
    assert payload["owner_only"] is True
    assert {row["job_id"] for row in payload["jobs"]} == {first, second}
    assert all("input_ref" not in row and "output_ref" not in row for row in payload["jobs"])
    assert client.get(history_url + "?limit=0").status_code == 400
    engagement["status"] = "BLOCKED"
    blocked = client.get(history_url)
    assert blocked.status_code == 200
    assert blocked.json()["jobs"] == []


def test_staging_preview_eligibility_has_independent_selector(preview):
    client, engagement, _ = preview
    url = "/api/nova/work/operations/recovery-preview/eligible-csv-tasks"
    result = client.get(url)
    assert result.status_code == 200
    assert result.json()["count"] == 1
    assert result.json()["tasks"][0]["task_id"] == "task-a"
    assert result.json()["execution_authorized"] is False
    engagement["status"] = "BLOCKED"
    assert client.get(url).json()["tasks"] == []


def test_owner_can_process_bounded_due_jobs_in_staging_preview(preview):
    client, _, store = preview
    ids = {
        create(client, key="batch-one").json()["job_id"],
        create(client, key="batch-two").json()["job_id"],
    }
    endpoint = "/api/nova/work/operations/recovery-preview/jobs/process-due"
    response = client.post(endpoint)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["attempted"] == 2
    assert set(payload["awaiting_review"]) == ids
    assert payload["delivered"] is False
    assert len(store.objects) == 4
    assert client.post(endpoint).json()["attempted"] == 0


def test_revoked_assignment_cannot_be_processed_by_batch(preview):
    client, engagement, store = preview
    job_id = create(client, key="batch-revoked").json()["job_id"]
    engagement["status"] = "BLOCKED"
    response = client.post(
        "/api/nova/work/operations/recovery-preview/jobs/process-due"
    )
    assert response.status_code == 200
    assert response.json()["awaiting_review"] == []
    assert response.json()["failed_attempts"] == [job_id]
    assert len(store.objects) == 1


def test_preview_cleanup_debt_exposes_only_owner_count(preview):
    client, _, _ = preview
    response = client.get("/api/nova/work/operations/recovery-preview/cleanup-debt")
    assert response.status_code == 200
    assert response.json() == {"unresolved_cleanup_failures": 0, "delivered": False}
    assert "storage_ref" not in response.text


def test_staging_cleanup_retry_requires_dry_run_and_explicit_approval(preview):
    client, _, store = preview
    endpoint = "/api/nova/work/operations/recovery-preview/cleanup-retry"
    assert client.post(endpoint, json={}).status_code == 400
    assert client.post(endpoint, json={"dry_run": False}).status_code == 403
    assert client.post(endpoint, json={"dry_run": True}).status_code == 200
    body = client.post(
        endpoint,
        json={"dry_run": False, "approval": "owner-approved-staging-cleanup"},
    )
    assert body.status_code == 200
    assert body.json()["deleted"] == 0
    assert body.json()["delivered"] is False
