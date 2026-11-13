"""PostgreSQL-specific customer CSV integration checks (CI ephemeral DB only).

Requires NOVA_CSV_CI_DATABASE_URL explicitly targeting an ephemeral PostgreSQL
instance. This suite never reads an app/production DATABASE_URL and never uses
real object storage or customer data.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import os

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_customer_csv_jobs as csvjobs


class FakePrivateStore:
    def __init__(self):
        self.items = {}
        self.put_count = 0

    def store(self, *, organization_id, application_id, category, filename,
              content_type, stream):
        self.put_count += 1
        key = f"{organization_id}/{application_id}/{category}/{filename}"
        value = stream.read()
        self.items[key] = value
        return "private-test", key, len(value)

    def retrieve(self, *, storage_ref):
        return self.items[storage_ref], "text/csv"

    def delete(self, *, storage_ref):
        self.items.pop(storage_ref, None)


@pytest.fixture
def postgres(monkeypatch):
    url = os.getenv("NOVA_CSV_CI_DATABASE_URL", "")
    if not url or "127.0.0.1" not in url or "postgresql" not in url:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail("CI must provide an isolated loopback PostgreSQL service")
        pytest.skip("explicit loopback ephemeral PostgreSQL required")
    engine = sa.create_engine(url, pool_size=5, max_overflow=5)
    assert engine.dialect.name == "postgresql"
    migration_file = (
        Path(__file__).resolve().parents[1] / "migrations" / "versions"
        / "20261109_nova_operations_csv_jobs.py"
    )
    spec = spec_from_file_location("nova_csv_pg_migration_ci", migration_file)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("NOVA_OPERATIONS_CSV_SCHEMA_APPROVED", "staging-only")
    # Run the ACTUAL Alembic revision against disposable PostgreSQL.
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        monkeypatch.setattr(migration, "op", Operations(context))
        migration.upgrade()
    inspector = sa.inspect(engine)
    assert csvjobs.jobs.name in inspector.get_table_names()
    assert "uq_nova_customer_csv_request" in {
        c["name"] for c in inspector.get_unique_constraints(csvjobs.jobs.name)
    }
    assert "ix_nova_customer_csv_owned" in {
        ix["name"] for ix in inspector.get_indexes(csvjobs.jobs.name)
    }
    monkeypatch.setenv("NOVA_OPERATIONS_DURABLE_CSV_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    store = FakePrivateStore()
    monkeypatch.setattr(csvjobs, "_store", lambda: store)
    yield engine, store
    csvjobs.metadata.drop_all(engine)
    engine.dispose()


def _submit(engine, request_key, raw=b"Name\nAda\nAda\n"):
    with Session(engine) as db:
        return csvjobs.submit_review_job(
            db, org="synthetic-org", owner="synthetic-owner",
            engagement_id="synthetic-eng", task_id="synthetic-csv-task",
            request_key=request_key, raw=raw,
        )


def test_postgres_real_runtime_and_private_review_round_trip(postgres):
    engine, store = postgres
    created = _submit(engine, "pg-create")
    assert created["status"] == "AWAITING_REVIEW"
    with Session(engine) as db:
        assert csvjobs.job_status(
            db, org="synthetic-org", owner="synthetic-owner",
            job_id=created["job_id"],
        )["status"] == "AWAITING_REVIEW"
        assert csvjobs.download_review(
            db, org="synthetic-org", owner="synthetic-owner",
            job_id=created["job_id"],
        ) == b"Name\nAda\n"
        with pytest.raises(csvjobs.CustomerCSVBlocked) as denied:
            csvjobs.download_review(
                db, org="synthetic-org", owner="another-owner",
                job_id=created["job_id"],
            )
        assert denied.value.code == 404
        reviewed = csvjobs.review_job(
            db, org="synthetic-org", owner="synthetic-owner",
            job_id=created["job_id"], approve=True,
        )
        assert reviewed["status"] == "APPROVED_FOR_DOWNLOAD"
    assert len(store.items) == 1


def test_postgres_two_connection_idempotency_and_scope(postgres):
    engine, store = postgres
    first = _submit(engine, "pg-duplicate")
    replay = _submit(engine, "pg-duplicate")
    assert replay["job_id"] == first["job_id"]
    assert replay["replayed"] is True
    assert store.put_count == 1
    with pytest.raises(csvjobs.CustomerCSVBlocked, match="different work"):
        _submit(engine, "pg-duplicate", b"Name\nDifferent\n")
    with Session(engine) as db:
        count = db.execute(sa.select(sa.func.count()).select_from(csvjobs.jobs)).scalar_one()
        assert count == 1


def test_postgres_concurrent_duplicate_key_creates_one_artifact(postgres):
    engine, store = postgres
    gate = Barrier(2)
    def send():
        gate.wait(timeout=10)
        return _submit(engine, "pg-race")
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(send)
        b = pool.submit(send)
        results = [a.result(timeout=20), b.result(timeout=20)]
    assert results[0]["job_id"] == results[1]["job_id"]
    assert sorted(v["replayed"] for v in results) == [False, True]
    assert store.put_count == 1
    with Session(engine) as db:
        count = db.execute(sa.select(sa.func.count()).select_from(csvjobs.jobs)).scalar_one()
        assert count == 1


def test_postgres_stale_recovery_preview_and_exact_owner_apply(postgres):
    """Real PostgreSQL: bounded recovery never changes another owner's jobs."""
    from datetime import timedelta

    engine, store = postgres
    old = csvjobs._utc() - timedelta(minutes=35)
    with Session(engine) as db:
        for job_id, organization, owner, status in (
            ("pg-stale-owner", "synthetic-org", "synthetic-owner", "PROCESSING"),
            ("pg-stale-neighbor", "synthetic-org", "another-owner", "PROCESSING"),
            ("pg-stale-other-org", "other-org", "synthetic-owner", "PROCESSING"),
            ("pg-reviewed", "synthetic-org", "synthetic-owner", "AWAITING_REVIEW"),
        ):
            db.execute(sa.insert(csvjobs.jobs).values(
                id=job_id, organization_id=organization, owner_user_id=owner,
                engagement_id="synthetic-eng", task_id="synthetic-csv-task",
                request_key=job_id, input_sha256="a" * 64,
                status=status, created_at=old, updated_at=old,
            ))
        db.commit()

    # Separate sessions model a browser preview followed by a later action.
    with Session(engine) as db:
        preview = csvjobs.recover_owned_stale_jobs(
            db, org="synthetic-org", owner="synthetic-owner", dry_run=True,
        )
        assert preview["candidate_job_ids"] == ["pg-stale-owner"]
        assert preview["recovered_count"] == 0
        assert preview["delivered"] is False
    with Session(engine) as db:
        with pytest.raises(csvjobs.CustomerCSVBlocked, match="preview changed"):
            csvjobs.recover_owned_stale_jobs(
                db, org="synthetic-org", owner="synthetic-owner",
                dry_run=False, expected_job_ids=["different-job"],
            )
        applied = csvjobs.recover_owned_stale_jobs(
            db, org="synthetic-org", owner="synthetic-owner",
            dry_run=False, expected_job_ids=preview["candidate_job_ids"],
        )
        assert applied["recovered_job_ids"] == ["pg-stale-owner"]
        assert applied["delivered"] is False
        assert applied["requires_reupload"] is True
    with Session(engine) as db:
        rows = dict(db.execute(sa.select(csvjobs.jobs.c.id, csvjobs.jobs.c.status)).all())
        assert rows["pg-stale-owner"] == "FAILED"
        assert rows["pg-stale-neighbor"] == "PROCESSING"
        assert rows["pg-stale-other-org"] == "PROCESSING"
        assert rows["pg-reviewed"] == "AWAITING_REVIEW"
    assert store.put_count == 0


def test_postgres_recovery_does_not_rewrite_recent_or_completed_job(postgres):
    """Real PostgreSQL: current lease and saved deliverable remain untouched."""
    from datetime import timedelta

    engine, store = postgres
    old = csvjobs._utc() - timedelta(minutes=40)
    recent = csvjobs._utc() - timedelta(minutes=2)
    with Session(engine) as db:
        for job_id, status, stamp in (
            ("pg-current", "PROCESSING", recent),
            ("pg-approved", "APPROVED_FOR_DOWNLOAD", old),
        ):
            db.execute(sa.insert(csvjobs.jobs).values(
                id=job_id, organization_id="synthetic-org",
                owner_user_id="synthetic-owner",
                engagement_id="synthetic-eng", task_id="synthetic-csv-task",
                request_key=job_id, input_sha256="b" * 64,
                status=status, created_at=stamp, updated_at=stamp,
            ))
        db.commit()
    with Session(engine) as db:
        preview = csvjobs.recover_owned_stale_jobs(
            db, org="synthetic-org", owner="synthetic-owner", dry_run=True,
        )
        assert preview["candidate_job_ids"] == []
        with pytest.raises(csvjobs.CustomerCSVBlocked, match="Exact previewed"):
            csvjobs.recover_owned_stale_jobs(
                db, org="synthetic-org", owner="synthetic-owner",
                dry_run=False, expected_job_ids=[],
            )
        assert csvjobs.job_status(
            db, org="synthetic-org", owner="synthetic-owner", job_id="pg-current",
        )["status"] == "PROCESSING"
        assert csvjobs.job_status(
            db, org="synthetic-org", owner="synthetic-owner", job_id="pg-approved",
        )["status"] == "APPROVED_FOR_DOWNLOAD"
    assert store.put_count == 0


def test_postgres_saved_private_artifact_readback_failure_is_not_reviewable(postgres, monkeypatch):
    """Real PostgreSQL metadata must remain FAILED if private storage readback corrupts."""
    engine, store = postgres
    real_retrieve = store.retrieve

    def corrupt_readback(*, storage_ref):
        content, mime = real_retrieve(storage_ref=storage_ref)
        return content + b"corruption", mime

    monkeypatch.setattr(store, "retrieve", corrupt_readback)
    with pytest.raises(csvjobs.CustomerCSVBlocked, match="integrity mismatch"):
        _submit(engine, "pg-readback-corrupt")
    with Session(engine) as db:
        rows = db.execute(
            sa.select(csvjobs.jobs.c.status, csvjobs.jobs.c.output_ref)
        ).all()
        assert rows == [("FAILED", None)]
    assert store.items == {}
