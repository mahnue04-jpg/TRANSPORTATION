"""Fail-closed staging worker tests; no Render services or customer files."""
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_recovery_worker as worker
from app.core.nova.work_revenue import operations_recoverable_csv as recovery
from app.core.nova.work_revenue.operations_customer_csv_jobs import CustomerCSVBlocked


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("NOVA_OPERATIONS_RECOVERY_WORKER_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_STAGING_DB_APPROVED", "isolated-reviewed")
    monkeypatch.setenv("NOVA_OPERATIONS_STAGING_DATABASE_URL",
                       "postgresql://synthetic:synthetic@127.0.0.1/nova_operations_stage")
    monkeypatch.setenv("DATABASE_URL",
                       "postgresql://synthetic:synthetic@127.0.0.1/amicor_prod")
    monkeypatch.setenv("NOVA_OPERATIONS_RECOVERY_OWNER_EMAIL",
                       "owner@example.invalid")
    monkeypatch.setattr(worker, "_work_revenue_owner_emails",
                        lambda: {"owner@example.invalid"})


def test_worker_staging_configuration_approved(config):
    url, email = worker._stage_only_config()
    assert "nova_operations_stage" in url
    assert email == "owner@example.invalid"


@pytest.mark.parametrize("env_name,new_value", [
    ("AMICOR_ENVIRONMENT", "production"),
    ("NOVA_OPERATIONS_RECOVERY_WORKER_ENABLED", "false"),
    ("NOVA_OPERATIONS_STAGING_DB_APPROVED", ""),
    ("NOVA_OPERATIONS_RECOVERY_OWNER_EMAIL", "attacker@example.invalid"),
    ("NOVA_OPERATIONS_STAGING_DATABASE_URL",
     "postgresql://synthetic:synthetic@127.0.0.1/amicor_prod"),
    ("NOVA_OPERATIONS_STAGING_DATABASE_URL",
     "postgresql://synthetic:synthetic@127.0.0.1/casting_stage"),
    ("NOVA_OPERATIONS_STAGING_DATABASE_URL", "sqlite:///local.db"),
])
def test_worker_rejects_incorrect_configuration(config, monkeypatch, env_name, new_value):
    monkeypatch.setenv(env_name, new_value)
    with pytest.raises(CustomerCSVBlocked):
        worker._stage_only_config()


def test_worker_uses_active_owner_and_assignment_checks(config, monkeypatch):
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    recovery.metadata.create_all(engine)
    owner = SimpleNamespace(user_id="owner-a", organization_id="org-a")
    monkeypatch.setattr(worker, "_staging_owner", lambda db, email: owner)
    monkeypatch.setattr(recovery, "require_runtime", lambda db: None)
    calls = []

    def verify(db, *, owner, engagement_id, task_id):
        calls.append((owner.user_id, engagement_id, task_id))

    monkeypatch.setattr(worker, "_check_saved_csv_assignment", verify)
    class FakePrivateStore:
        def __init__(self):
            self.data = {}
        def store(self, *, organization_id, application_id, category,
                  filename, content_type, stream):
            ref = f"{organization_id}/{application_id}/{category}"
            payload = stream.read()
            self.data[ref] = payload
            return "fake-private", ref, len(payload)
        def retrieve(self, *, storage_ref):
            return self.data[storage_ref], "text/csv"
        def delete(self, *, storage_ref):
            self.data.pop(storage_ref, None)

    store = FakePrivateStore()
    monkeypatch.setattr(recovery, "_store", lambda: store)
    with Session(engine) as db:
        job = recovery.enqueue(
            db, org="org-a", owner="owner-a", engagement_id="eng-a",
            task_id="task-a", request_key="worker-job",
            raw=b"Name\nAda\nAda\n",
        )
    factory = lambda: Session(engine)
    outcome = worker.run_once(factory, owner_email="owner@example.invalid")
    assert outcome["awaiting_review"] == [job["job_id"]]
    assert outcome["delivered"] is False
    assert calls == [("owner-a", "eng-a", "task-a")] * 2
    with Session(engine) as db:
        assert recovery.status(db, org="org-a", owner="owner-a",
                               job_id=job["job_id"])["status"] == "AWAITING_REVIEW"
    engine.dispose()


def test_worker_never_uses_demo_owner_if_account_missing(config):
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    from app.db.models import User
    from app.db.session import Base
    Base.metadata.create_all(engine, tables=[User.__table__])
    with Session(engine) as db:
        with pytest.raises(CustomerCSVBlocked, match="owner missing"):
            worker._staging_owner(db, "owner@example.invalid")
    engine.dispose()
