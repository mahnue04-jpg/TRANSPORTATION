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


def test_held_lease_reads_real_scoped_csv_private_artifact(postgres, monkeypatch):
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_csv_reconciliation_bridge import (
        inspect_held_csv_artifact,
    )
    engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    try:
        created = _submit(engine, "pg-held-bridge")
        assert created["status"] == "AWAITING_REVIEW"
        with Session(engine) as db:
            row = db.execute(sa.select(csvjobs.jobs).where(
                csvjobs.jobs.c.id == created["job_id"]
            )).mappings().one()
            leases.enqueue(db, job_id=created["job_id"],
                           organization_id=row["organization_id"],
                           owner_user_id=row["owner_user_id"],
                           input_sha256=row["input_sha256"])
            claimed = leases.claim(db)
            assert claimed and claimed.job_id == created["job_id"]
            assert leases.hold_for_reconciliation(
                db, claimed=claimed,
                expected_output_sha256=row["output_sha256"])
            first = inspect_held_csv_artifact(
                db, job_id=created["job_id"], organization_id="synthetic-org",
                owner_user_id="synthetic-owner")
            assert first == {
                "job_id": created["job_id"], "result": "digest_matches",
                "may_release": False,
            }
            with pytest.raises(leases.LeaseBlocked, match="authorized scope"):
                inspect_held_csv_artifact(
                    db, job_id=created["job_id"], organization_id="synthetic-org",
                    owner_user_id="another-owner")
            assert db.execute(sa.select(leases.lease_jobs.c.state).where(
                leases.lease_jobs.c.job_id == created["job_id"]
            )).scalar_one() == "NEEDS_RECONCILIATION"
            # Private artifact tampering fails closed; no owner approval.
            store.items[row["output_ref"]] = b"not the expected cleaned CSV"
            mismatch = inspect_held_csv_artifact(
                db, job_id=created["job_id"], organization_id="synthetic-org",
                owner_user_id="synthetic-owner")
            assert mismatch["result"] == "digest_mismatch"
            assert mismatch["may_release"] is False
    finally:
        leases.lease_metadata.drop_all(engine)


def test_bridge_rejects_linked_input_fingerprint_mismatch(postgres, monkeypatch):
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_csv_reconciliation_bridge import (
        inspect_held_csv_artifact,
    )
    engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    try:
        created = _submit(engine, "pg-held-input-mismatch")
        with Session(engine) as db:
            row = db.execute(sa.select(csvjobs.jobs).where(
                csvjobs.jobs.c.id == created["job_id"]
            )).mappings().one()
            leases.enqueue(db, job_id=created["job_id"],
                           organization_id=row["organization_id"],
                           owner_user_id=row["owner_user_id"],
                           input_sha256="0" * 64)
            claimed = leases.claim(db)
            assert claimed
            assert leases.hold_for_reconciliation(
                db, claimed=claimed,
                expected_output_sha256=row["output_sha256"])
            before = store.put_count
            outcome = inspect_held_csv_artifact(
                db, job_id=created["job_id"], organization_id="synthetic-org",
                owner_user_id="synthetic-owner")
            assert outcome["result"] == "metadata_digest_mismatch"
            assert outcome["may_release"] is False
            assert store.put_count == before
    finally:
        leases.lease_metadata.drop_all(engine)


def test_reconciliation_match_never_implicitly_approves_csv_owner_review(postgres, monkeypatch):
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_csv_reconciliation_bridge import (
        inspect_held_csv_artifact,
    )
    engine, _store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    try:
        created = _submit(engine, "pg-read-only-owner-review")
        with Session(engine) as db:
            row = db.execute(sa.select(csvjobs.jobs).where(
                csvjobs.jobs.c.id == created["job_id"]
            )).mappings().one()
            leases.enqueue(db, job_id=created["job_id"],
                           organization_id="synthetic-org",
                           owner_user_id="synthetic-owner",
                           input_sha256=row["input_sha256"])
            active = leases.claim(db)
            assert active is not None
            assert leases.hold_for_reconciliation(
                db, claimed=active, expected_output_sha256=row["output_sha256"])
            result = inspect_held_csv_artifact(
                db, job_id=created["job_id"], organization_id="synthetic-org",
                owner_user_id="synthetic-owner")
            assert result["result"] == "digest_matches"
            assert result["may_release"] is False
            assert csvjobs.job_status(
                db, org="synthetic-org", owner="synthetic-owner",
                job_id=created["job_id"])["status"] == "AWAITING_REVIEW"
            # A separate explicit owner review is still necessary.
            approved = csvjobs.review_job(
                db, org="synthetic-org", owner="synthetic-owner",
                job_id=created["job_id"], approve=True)
            assert approved["status"] == "APPROVED_FOR_DOWNLOAD"
            assert approved["delivered"] is False
            assert db.execute(sa.select(leases.lease_jobs.c.state).where(
                leases.lease_jobs.c.job_id == created["job_id"]
            )).scalar_one() == "NEEDS_RECONCILIATION"
    finally:
        leases.lease_metadata.drop_all(engine)


def test_bound_private_input_survives_fresh_database_session(postgres, monkeypatch):
    """Synthetic persisted input reference can be read after session restart."""
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_private_input import (
        persist_private_csv_input, load_private_csv_input,
    )
    engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    raw = b"Name\\nAda\\n"
    try:
        receipt = persist_private_csv_input(
            organization_id="synthetic-org",
            owner_user_id="synthetic-owner",
            job_id="synthetic-restart",
            raw=raw, store=store)
        with Session(engine) as db:
            leases.enqueue(db, job_id="synthetic-restart",
                           organization_id="synthetic-org",
                           owner_user_id="synthetic-owner",
                           input_sha256=receipt.sha256)
            assert leases.bind_private_input(
                db, job_id="synthetic-restart",
                organization_id="synthetic-org",
                owner_user_id="synthetic-owner",
                input_sha256=receipt.sha256,
                storage_ref=receipt.storage_ref, input_size=receipt.size)
        # Fresh PostgreSQL session (not a true process restart).
        with Session(engine) as db:
            claimed = leases.claim(db, lease_seconds=60)
            assert claimed and claimed.job_id == "synthetic-restart"
            ref, size = leases.read_bound_input_metadata(db, claimed=claimed)
            assert size == len(raw)
            assert load_private_csv_input(
                organization_id=claimed.organization_id,
                owner_user_id=claimed.owner_user_id,
                job_id=claimed.job_id, storage_ref=ref,
                expected_sha256=claimed.input_sha256, store=store) == raw
    finally:
        leases.lease_metadata.drop_all(engine)


def test_synthetic_worker_reloads_private_input_after_engine_reconnect(postgres, monkeypatch):
    """Disposable PG + fake private store; engine reconnect is not an OS restart."""
    from io import BytesIO
    import hashlib
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_private_input import (
        persist_private_csv_input, load_private_csv_input,
    )
    from app.core.nova.work_revenue.operations_lease_worker import run_one
    from app.core.nova.work_revenue.operations_csv_cleanup import clean_csv_text

    original_engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(original_engine)
    raw = b"Name\nAda\nAda\n"
    job_id = "synthetic-reconnect"
    try:
        receipt = persist_private_csv_input(
            organization_id="synthetic-org", owner_user_id="synthetic-owner",
            job_id=job_id, raw=raw, store=store)
        with Session(original_engine) as db:
            leases.enqueue(db, job_id=job_id, organization_id="synthetic-org",
                           owner_user_id="synthetic-owner",
                           input_sha256=receipt.sha256)
            assert leases.bind_private_input(
                db, job_id=job_id, organization_id="synthetic-org",
                owner_user_id="synthetic-owner",
                input_sha256=receipt.sha256,
                storage_ref=receipt.storage_ref, input_size=receipt.size)

        # Close all pooled connections and recreate the engine to model a
        # disconnected process using the same durable database and fake bucket.
        original_engine.dispose()
        fresh_engine = sa.create_engine(os.environ["NOVA_CSV_CI_DATABASE_URL"])
        try:
            output_refs = []
            def deterministic_handler(claim):
                with Session(fresh_engine) as db:
                    ref, size = leases.read_bound_input_metadata(db, claimed=claim)
                source = load_private_csv_input(
                    organization_id=claim.organization_id,
                    owner_user_id=claim.owner_user_id,
                    job_id=claim.job_id, storage_ref=ref,
                    expected_sha256=claim.input_sha256, store=store)
                assert len(source) == size
                cleaned = clean_csv_text(source.decode("utf-8-sig"))
                output = cleaned.cleaned_csv.encode("utf-8")
                saved = store.store(
                    organization_id=claim.organization_id,
                    application_id=claim.job_id,
                    category="nova-csv-test-worker-output",
                    filename="cleaned.csv", content_type="text/csv",
                    stream=BytesIO(output))
                assert saved[2] == len(output)
                output_refs.append(saved[1])
                return hashlib.sha256(output).hexdigest()

            result = run_one(lambda: Session(fresh_engine),
                             deterministic_handler)
            assert result == {"state": "completed", "job_id": job_id}
            assert len(output_refs) == 1
            output, _kind = store.retrieve(storage_ref=output_refs[0])
            assert output == b"Name\nAda\n"
            with Session(fresh_engine) as db:
                row = db.execute(sa.select(leases.lease_jobs).where(
                    leases.lease_jobs.c.job_id == job_id)).mappings().one()
                assert row["state"] == "COMPLETED"
                assert row["output_sha256"] == hashlib.sha256(output).hexdigest()
                assert leases.claim(db) is None
        finally:
            fresh_engine.dispose()
    finally:
        leases.lease_metadata.drop_all(original_engine)
