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
    assert client.get(base + "/download").content == b"Name\\nAda\\n"
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
