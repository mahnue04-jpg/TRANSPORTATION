"""Isolated PostgreSQL acceptance checks for Nova bookkeeping authorization.

Runs ONLY against a disposable 127.0.0.1 CI Postgres service. Applies the
actual two staging-gated Alembic migration scripts, inserts entirely fictional
consent evidence, and exercises real database persistence plus fake private S3.
This is not a Render staging/real customer test or authorization provisioning.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import bookkeeping_durable_jobs as finance
from app.core.nova.work_revenue import bookkeeping_scope as scope
from app.core.nova.work_revenue import operations_customer_csv_jobs as csvjobs
from app.core.nova.work_revenue import service

ROOT = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SOURCE = (
    b"invoice_id,customer,invoice_date,due_date,amount,paid\n"
    b"FAKE-001,Invented Customer,2026-10-01,2026-10-31,100.00,25.00\n"
)


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.writes = 0

    def store(self, *, organization_id, application_id, category,
              filename, content_type, stream):
        assert category == "nova-bookkeeping-review"
        assert content_type == "text/csv"
        key = f"{organization_id}/{application_id}/{category}/{filename}"
        content = stream.read()
        self.objects[key] = content
        self.writes += 1
        return "test-private", key, len(content)

    def retrieve(self, *, storage_ref):
        return self.objects[storage_ref], "text/csv"

    def delete(self, *, storage_ref):
        del self.objects[storage_ref]


def load_migration(filename):
    spec = spec_from_file_location("nova_pg_ci_" + filename.replace(".", "_"), ROOT / filename)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pg(monkeypatch):
    url = os.getenv("NOVA_BOOKKEEPING_CI_POSTGRES_URL", "")
    if not url.startswith("postgresql+psycopg2://") or "@127.0.0.1:" not in url:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail("Dedicated loopback PostgreSQL service required in CI")
        pytest.skip("Explicit disposable localhost PostgreSQL service required")
    engine = sa.create_engine(url, pool_size=5, max_overflow=5)
    assert engine.dialect.name == "postgresql"
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("NOVA_OPERATIONS_CSV_SCHEMA_APPROVED", "staging-only")
    monkeypatch.setenv("NOVA_BOOKKEEPING_CONSENT_SCHEMA_APPROVED", "staging-only")

    # Both genuine Alembic upgrades, on an isolated temporary CI database.
    for filename in (
        "20261109_nova_operations_csv_jobs.py",
        "20261111_nova_bookkeeping_consent.py",
    ):
        migration = load_migration(filename)
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            monkeypatch.setattr(migration, "op", Operations(context))
            migration.upgrade()
    inspector = sa.inspect(engine)
    assert csvjobs.jobs.name in inspector.get_table_names()
    assert scope.consents.name in inspector.get_table_names()
    assert "uq_nova_bookkeeping_consent_scope" in {
        item["name"] for item in inspector.get_unique_constraints(scope.consents.name)
    }
    assert "ix_nova_bookkeeping_consent_owned" in {
        item["name"] for item in inspector.get_indexes(scope.consents.name)
    }

    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_CSV_ENABLED", "true")
    monkeypatch.setenv("NOVA_BOOKKEEPING_DURABLE_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    store = FakeStorage()
    monkeypatch.setattr(csvjobs, "_store", lambda: store)
    owner = SimpleNamespace(organization_id="synthetic-org", user_id="synthetic-owner")
    now = datetime.now(timezone.utc)
    digest = hashlib.sha256(b"clearly fictional consent document").hexdigest()
    with Session(engine) as db:
        db.execute(sa.insert(scope.consents).values(
            authorization_id="synthetic-consent-1",
            organization_id=owner.organization_id,
            owner_user_id=owner.user_id,
            engagement_id="synthetic-engagement",
            task_id="synthetic-task",
            work_type="receivables_aging",
            status="APPROVED",
            contract_ref_sha256=digest,
            client_ai_consent_ref_sha256=digest,
            data_processing_ref_sha256=digest,
            verified_by_user_id="synthetic-reviewer",
            verified_at=now - timedelta(hours=1),
            valid_until=now + timedelta(days=1),
            revoked_at=None,
        ))
        db.commit()

    # Mock only Work & Revenue's existing engagement read. The actual consent
    # resolver queries the REAL PostgreSQL authorization table each time.
    engagement = {
        "engagement_id": "synthetic-engagement",
        "organization_id": owner.organization_id,
        "owner_user_id": owner.user_id,
        "status": "ACTIVE",
        "blockers": "",
        "tasks": [{
            "task_id": "synthetic-task",
            "bookkeeping_work_type": "receivables_aging",
            "classification": "NOVA",
            "responsible_party": "NOVA",
            "review_required": True,
            "status": "READY",
            "blocked_reason": "",
            "required_owner_input": "",
        }],
    }
    monkeypatch.setattr(service, "get_engagement", lambda db, engagement_id, **kw: engagement)
    yield engine, store, owner
    with engine.begin() as connection:
        connection.execute(sa.text("DROP TABLE IF EXISTS nova_bookkeeping_contract_authorizations"))
        connection.execute(sa.text("DROP TABLE IF EXISTS nova_operations_customer_csv_jobs"))
    engine.dispose()


def test_real_postgres_signed_scope_then_revoke(pg):
    engine, store, owner = pg
    with Session(engine) as db:
        assignment = scope.resolve_bookkeeping_assignment(
            db, owner=owner, engagement_id="synthetic-engagement",
            task_id="synthetic-task", work_type="receivables_aging",
        )
        created = finance.submit_bookkeeping_review(
            db, assignment=assignment, request_id="pg-test-1",
            primary=SOURCE, as_of="2026-11-11",
        )
        assert created["status"] == "AWAITING_REVIEW"
        assert created["delivered"] is False
        job_id = created["job_id"]
        assert store.writes == 1
        replay = finance.submit_bookkeeping_review(
            db, assignment=assignment, request_id="pg-test-1",
            primary=SOURCE, as_of="2026-11-11",
        )
        assert replay["replayed"] and replay["job_id"] == job_id
        assert store.writes == 1
        with pytest.raises(csvjobs.CustomerCSVBlocked) as denied:
            finance.download_bookkeeping(
                db, org="synthetic-org", owner="wrong-owner", job_id=job_id,
            )
        assert denied.value.code == 404
    # Reopening a real database session should keep job metadata intact.
    with Session(engine) as db:
        info = finance.bookkeeping_status(
            db, org="synthetic-org", owner="synthetic-owner", job_id=job_id,
        )
        assert info["status"] == "AWAITING_REVIEW"
        data = finance.download_bookkeeping(
            db, org="synthetic-org", owner="synthetic-owner", job_id=job_id,
        )
        assert b"75.00" in data
        assert hashlib.sha256(data).hexdigest() == created["output_sha256"]
        db.execute(sa.update(scope.consents).where(
            scope.consents.c.authorization_id == "synthetic-consent-1",
        ).values(status="REVOKED", revoked_at=datetime.now(timezone.utc)))
        db.commit()
        with pytest.raises(scope.ConsentNotVerified):
            scope.resolve_bookkeeping_assignment(
                db, owner=owner, engagement_id="synthetic-engagement",
                task_id="synthetic-task", work_type="receivables_aging",
            )


def test_postgres_expired_authorization_blocks_work(pg):
    engine, _, owner = pg
    with Session(engine) as db:
        db.execute(sa.update(scope.consents).where(
            scope.consents.c.authorization_id == "synthetic-consent-1",
        ).values(valid_until=datetime.now(timezone.utc) - timedelta(minutes=1)))
        db.commit()
        with pytest.raises(scope.ConsentNotVerified, match="expired"):
            scope.resolve_bookkeeping_assignment(
                db, owner=owner, engagement_id="synthetic-engagement",
                task_id="synthetic-task", work_type="receivables_aging",
            )


def test_postgres_other_owner_and_wrong_work_type_blocked(pg):
    engine, _, owner = pg
    with Session(engine) as db:
        for visitor, kind in (
            (SimpleNamespace(organization_id="synthetic-org", user_id="someone-else"), "receivables_aging"),
            (owner, "payables_aging"),
        ):
            with pytest.raises(scope.ConsentNotVerified):
                scope.resolve_bookkeeping_assignment(
                    db, owner=visitor, engagement_id="synthetic-engagement",
                    task_id="synthetic-task", work_type=kind,
                )


def test_postgres_http_lifecycle_uses_real_consent_db(pg):
    """Real FastAPI route + real consent queries + disposable PostgreSQL.

    The authenticated user is synthetic, the saved Work engagement is mocked
    by pg fixture, and private storage is fake: never real client readiness.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.nova.router import require_nova_access
    from app.core.nova.work_revenue.owner_auth import require_work_revenue_owner
    from app.core.nova.work_revenue import operations_owner_csv_api as api
    from app.db.session import get_db

    engine, store, owner = pg
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[require_nova_access] = lambda: owner
    app.dependency_overrides[require_work_revenue_owner] = lambda: owner

    def postgres_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = postgres_db
    prefix = "/operations/durable/bookkeeping"
    route = prefix + "/engagements/synthetic-engagement/tasks/synthetic-task/receivables_aging/jobs"
    headers = {
        "Idempotency-Key": "pg-http-1", "X-Nova-File-Name": "synthetic.csv",
        "X-Nova-As-Of": "2026-11-11", "Content-Type": "text/csv",
    }
    with TestClient(app) as client:
        created = client.post(route, content=SOURCE, headers=headers)
        assert created.status_code == 202, created.text
        job_id = created.json()["job_id"]
        assert created.json()["status"] == "AWAITING_REVIEW"
        assert created.json()["delivered"] is False
        assert store.writes == 1

        repeated = client.post(route, content=SOURCE, headers=headers)
        assert repeated.status_code == 202
        assert repeated.json()["replayed"] is True
        assert repeated.json()["job_id"] == job_id
        assert store.writes == 1

        status = client.get(f"{prefix}/jobs/{job_id}")
        assert status.status_code == 200, status.text
        original = client.get(f"{prefix}/jobs/{job_id}/download")
        assert original.status_code == 200, original.text
        assert b"75.00" in original.content
        assert original.headers["cache-control"] == "private, no-store"
        approval = client.post(f"{prefix}/jobs/{job_id}/review", json={"approve": True})
        assert approval.status_code == 200, approval.text
        assert approval.json()["delivered"] is False

        # Change the same PostgreSQL consent row independently of the route.
        with Session(engine) as db:
            db.execute(sa.update(scope.consents).where(
                scope.consents.c.authorization_id == "synthetic-consent-1",
            ).values(status="REVOKED", revoked_at=datetime.now(timezone.utc)))
            db.commit()
        for method, suffix, kwargs in (
            ("get", f"/jobs/{job_id}", {}),
            ("get", f"/jobs/{job_id}/download", {}),
            ("post", f"/jobs/{job_id}/review", {"json": {"approve": True}}),
            ("post", f"/jobs/{job_id}/recover", {}),
        ):
            response = getattr(client, method)(prefix + suffix, **kwargs)
            assert response.status_code == 403, (method, suffix, response.text)
        denied_new = client.post(
            route, content=SOURCE,
            headers={**headers, "Idempotency-Key": "pg-http-2"},
        )
        assert denied_new.status_code == 403, denied_new.text
        assert store.writes == 1


def test_postgres_consent_evidence_and_task_disagreement_fail_closed(pg, monkeypatch):
    engine, _, owner = pg
    with Session(engine) as db:
        db.execute(sa.update(scope.consents).where(
            scope.consents.c.authorization_id == "synthetic-consent-1",
        ).values(client_ai_consent_ref_sha256="0" * 64))
        db.commit()
        with pytest.raises(scope.ConsentNotVerified, match="evidence"):
            scope.resolve_bookkeeping_assignment(
                db, owner=owner, engagement_id="synthetic-engagement",
                task_id="synthetic-task", work_type="receivables_aging",
            )
    # Even fully formed consent evidence cannot authorize a task that
    # explicitly declares a contradictory bookkeeping work type.
    monkeypatch.setattr(service, "get_engagement", lambda db, engagement_id, **kw: {
        "engagement_id": "synthetic-engagement",
        "organization_id": owner.organization_id,
        "owner_user_id": owner.user_id,
        "status": "ACTIVE",
        "blockers": "",
        "tasks": [{
            "task_id": "synthetic-task", "bookkeeping_work_type": "payables_aging",
            "classification": "NOVA", "responsible_party": "NOVA",
            "review_required": True, "status": "READY",
        }],
    })
    with Session(engine) as db:
        db.execute(sa.update(scope.consents).where(
            scope.consents.c.authorization_id == "synthetic-consent-1",
        ).values(client_ai_consent_ref_sha256="a" * 64))
        db.commit()
        with pytest.raises(scope.ConsentNotVerified, match="eligible"):
            scope.resolve_bookkeeping_assignment(
                db, owner=owner, engagement_id="synthetic-engagement",
                task_id="synthetic-task", work_type="receivables_aging",
            )


def test_postgres_concurrent_accounting_idempotency_preserves_one_workpaper(pg):
    """Real concurrent connections must create one owned durable job."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    engine, store, owner = pg
    barrier = Barrier(2)

    def submit_concurrently():
        with Session(engine) as db:
            assignment = scope.resolve_bookkeeping_assignment(
                db, owner=owner, engagement_id="synthetic-engagement",
                task_id="synthetic-task", work_type="receivables_aging",
            )
            barrier.wait(timeout=10)
            return finance.submit_bookkeeping_review(
                db, assignment=assignment,
                request_id="pg-concurrent-accounting-1",
                primary=SOURCE, as_of="2026-11-11",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit_concurrently)
        second = pool.submit(submit_concurrently)
        outcomes = [first.result(timeout=20), second.result(timeout=20)]
    assert len({entry["job_id"] for entry in outcomes}) == 1
    assert sorted(entry["replayed"] for entry in outcomes) == [False, True]
    assert store.writes == 1
    with Session(engine) as db:
        count = db.execute(sa.select(sa.func.count()).select_from(
            csvjobs.jobs
        )).scalar_one()
        assert count == 1
        scoped = finance.bookkeeping_status(
            db, org="synthetic-org", owner="synthetic-owner",
            job_id=outcomes[0]["job_id"],
        )
        assert scoped["status"] == "AWAITING_REVIEW"


def test_postgres_owner_cannot_approve_corrupted_private_artifact(pg):
    engine, store, owner = pg
    with Session(engine) as db:
        assignment = scope.resolve_bookkeeping_assignment(
            db, owner=owner, engagement_id="synthetic-engagement",
            task_id="synthetic-task", work_type="receivables_aging",
        )
        created = finance.submit_bookkeeping_review(
            db, assignment=assignment, request_id="pg-integrity-review-1",
            primary=SOURCE, as_of="2026-11-11",
        )
        job_id = created["job_id"]
        ref = next(iter(store.objects))
        saved_bytes = store.objects[ref]
        store.objects[ref] = b"fake,changed,balance,99999.99"
        with pytest.raises(finance.BookkeepingJobBlocked, match="integrity"):
            finance.review_bookkeeping(
                db, org="synthetic-org", owner="synthetic-owner",
                job_id=job_id, approve=True,
            )
        assert finance.bookkeeping_status(
            db, org="synthetic-org", owner="synthetic-owner",
            job_id=job_id,
        )["status"] == "AWAITING_REVIEW"
        store.objects[ref] = saved_bytes
        approved = finance.review_bookkeeping(
            db, org="synthetic-org", owner="synthetic-owner",
            job_id=job_id, approve=True,
        )
        assert approved["status"] == "APPROVED_FOR_DOWNLOAD"


def test_locked_postgres_consent_serializes_revocation(pg):
    """Revocation cannot commit between locked approval-check and its commit."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    engine, _, owner = pg
    locked = Event()
    release = Event()
    revoked = Event()

    def authorize_with_lock():
        with Session(engine) as db:
            scope.resolve_bookkeeping_assignment(
                db, owner=owner, engagement_id="synthetic-engagement",
                task_id="synthetic-task", work_type="receivables_aging",
                lock_consent=True,
            )
            locked.set()
            assert release.wait(timeout=10)
            db.commit()
        return "checked"

    def revoke():
        assert locked.wait(timeout=10)
        with Session(engine) as db:
            db.execute(sa.update(scope.consents).where(
                scope.consents.c.authorization_id == "synthetic-consent-1",
            ).values(status="REVOKED", revoked_at=datetime.now(timezone.utc)))
            db.commit()
        revoked.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        check = pool.submit(authorize_with_lock)
        mutation = pool.submit(revoke)
        try:
            assert locked.wait(timeout=10)
            # The test intentionally holds a PostgreSQL FOR UPDATE lock while
            # the other session tries to change the same consent row.
            assert not revoked.wait(timeout=0.25)
        finally:
            release.set()
        assert check.result(timeout=15) == "checked"
        mutation.result(timeout=15)
    assert revoked.is_set()
    with Session(engine) as db:
        with pytest.raises(scope.ConsentNotVerified):
            scope.resolve_bookkeeping_assignment(
                db, owner=owner, engagement_id="synthetic-engagement",
                task_id="synthetic-task", work_type="receivables_aging",
            )
