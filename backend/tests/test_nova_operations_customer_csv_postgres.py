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


def test_queued_csv_full_owner_review_flow(postgres, monkeypatch):
    """One complete synthetic intake -> private worker -> owner review path."""
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_queued_csv_pipeline import (
        submit_queued_csv, process_one_queued_csv, review_processed_csv,
        QueuedCSVBlocked,
    )
    engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    factory = lambda: Session(engine)
    approve = lambda org, owner, eng, task: (
        org, owner, eng, task
    ) == ("synthetic-org", "synthetic-owner", "synthetic-eng", "synthetic-csv-task")
    try:
        prepared = dict(
            organization_id="synthetic-org", owner_user_id="synthetic-owner",
            engagement_id="synthetic-eng", task_id="synthetic-csv-task",
            request_key="pipeline-accept", raw=b"Name\nAda\nAda\n",
            store=store, authorize=approve,
        )
        created = submit_queued_csv(factory, **prepared)
        assert created["status"] == "QUEUED" and not created["delivered"]
        replay = submit_queued_csv(factory, **prepared)
        assert replay["replayed"] and replay["job_id"] == created["job_id"]
        assert store.put_count == 1
        finished = process_one_queued_csv(factory, store=store, authorize=approve)
        assert finished == {"state": "completed", "job_id": created["job_id"]}
        assert process_one_queued_csv(factory, store=store, authorize=approve)["state"] == "idle"
        with factory() as db:
            assert csvjobs.job_status(
                db, org="synthetic-org", owner="synthetic-owner",
                job_id=created["job_id"])["status"] == "AWAITING_REVIEW"
            assert csvjobs.download_review(
                db, org="synthetic-org", owner="synthetic-owner",
                job_id=created["job_id"]) == b"Name\nAda\n"
        with pytest.raises(QueuedCSVBlocked):
            review_processed_csv(
                factory, organization_id="synthetic-org", owner_user_id="someone-else",
                job_id=created["job_id"], approve=True, authorize=approve, store=store)
        reviewed = review_processed_csv(
            factory, organization_id="synthetic-org",
            owner_user_id="synthetic-owner", job_id=created["job_id"],
            approve=True, authorize=approve, store=store)
        assert reviewed["status"] == "APPROVED_FOR_DOWNLOAD"
        assert reviewed["delivered"] is False
        assert store.put_count == 2
    finally:
        leases.lease_metadata.drop_all(engine)


def test_queued_csv_revoked_before_upload_fails_closed(postgres, monkeypatch):
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_queued_csv_pipeline import (
        submit_queued_csv, QueuedCSVBlocked,
    )
    engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    approvals = iter([True, False])
    try:
        with pytest.raises(QueuedCSVBlocked, match="not authorized"):
            submit_queued_csv(
                lambda: Session(engine), organization_id="synthetic-org",
                owner_user_id="synthetic-owner", engagement_id="synthetic-eng",
                task_id="synthetic-csv-task", request_key="pipeline-revoked",
                raw=b"Name\nAda\n", store=store,
                authorize=lambda *_: next(approvals))
        assert store.put_count == 0
        with Session(engine) as db:
            row = db.execute(sa.select(csvjobs.jobs.c.status)).scalar_one()
            assert row == "PROCESSING"
            assert db.execute(sa.select(sa.func.count()).select_from(
                leases.lease_jobs)).scalar_one() == 0
    finally:
        leases.lease_metadata.drop_all(engine)


def test_queued_csv_corruption_blocks_worker_output(postgres, monkeypatch):
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_queued_csv_pipeline import (
        submit_queued_csv, process_one_queued_csv,
    )
    engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    factory = lambda: Session(engine)
    try:
        created = submit_queued_csv(
            factory, organization_id="synthetic-org",
            owner_user_id="synthetic-owner", engagement_id="synthetic-eng",
            task_id="synthetic-csv-task", request_key="pipeline-corrupt",
            raw=b"Name\nAda\n", store=store, authorize=lambda *_: True)
        with factory() as db:
            row = db.execute(sa.select(leases.lease_jobs).where(
                leases.lease_jobs.c.job_id == created["job_id"])).mappings().one()
            store.items[row["input_ref"]] = b"Name\nTampered\n"
        result = process_one_queued_csv(factory, store=store, authorize=lambda *_: True)
        assert result["state"] == "queued"
        with factory() as db:
            assert csvjobs.job_status(
                db, org="synthetic-org", owner="synthetic-owner",
                job_id=created["job_id"])["status"] == "PROCESSING"
        assert store.put_count == 1
    finally:
        leases.lease_metadata.drop_all(engine)


def test_uncertain_queued_output_is_held_not_retried(postgres, monkeypatch):
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_queued_csv_pipeline import (
        submit_queued_csv, process_one_queued_csv,
    )
    engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    factory = lambda: Session(engine)
    original_store = store.store
    try:
        created = submit_queued_csv(
            factory, organization_id="synthetic-org",
            owner_user_id="synthetic-owner", engagement_id="synthetic-eng",
            task_id="synthetic-csv-task", request_key="pipeline-uncertain",
            raw=b"Name\nAda\n", store=store, authorize=lambda *_: True)
        def ambiguous_store(**kwargs):
            receipt = original_store(**kwargs)
            if kwargs["category"] == "nova-csv-review":
                raise IOError("synthetic timeout after private write")
            return receipt
        monkeypatch.setattr(store, "store", ambiguous_store)
        response = process_one_queued_csv(factory, store=store, authorize=lambda *_: True)
        assert response == {"state": "needs_reconciliation",
                            "job_id": created["job_id"]}
        assert process_one_queued_csv(factory, store=store,
                                      authorize=lambda *_: True)["state"] == "idle"
        with factory() as db:
            row = db.execute(sa.select(leases.lease_jobs).where(
                leases.lease_jobs.c.job_id == created["job_id"])).mappings().one()
            assert row["state"] == "NEEDS_RECONCILIATION"
            assert row["attempts"] == 1
            assert csvjobs.job_status(
                db, org="synthetic-org", owner="synthetic-owner",
                job_id=created["job_id"])["status"] == "PROCESSING"
    finally:
        leases.lease_metadata.drop_all(engine)


def test_queued_csv_cancelled_job_is_never_processed(postgres, monkeypatch):
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_queued_csv_pipeline import (
        submit_queued_csv, process_one_queued_csv,
    )
    engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    factory = lambda: Session(engine)
    try:
        created = submit_queued_csv(
            factory, organization_id="synthetic-org",
            owner_user_id="synthetic-owner", engagement_id="synthetic-eng",
            task_id="synthetic-csv-task", request_key="pipeline-cancel",
            raw=b"Name\nAda\n", store=store, authorize=lambda *_: True)
        with factory() as db:
            assert leases.cancel(db, job_id=created["job_id"],
                                 organization_id="synthetic-org",
                                 owner_user_id="synthetic-owner")
        assert process_one_queued_csv(
            factory, store=store, authorize=lambda *_: True)["state"] == "idle"
        assert store.put_count == 1
    finally:
        leases.lease_metadata.drop_all(engine)


def test_queued_csv_rejects_changed_idempotency_payload(postgres, monkeypatch):
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_queued_csv_pipeline import (
        submit_queued_csv, QueuedCSVBlocked,
    )
    engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    factory = lambda: Session(engine)
    params = dict(
        organization_id="synthetic-org", owner_user_id="synthetic-owner",
        engagement_id="synthetic-eng", task_id="synthetic-csv-task",
        request_key="pipeline-idempotency", store=store, authorize=lambda *_: True,
    )
    try:
        submit_queued_csv(factory, raw=b"Name\nAda\n", **params)
        with pytest.raises(QueuedCSVBlocked, match="different work"):
            submit_queued_csv(factory, raw=b"Name\nMallory\n", **params)
        assert store.put_count == 1
    finally:
        leases.lease_metadata.drop_all(engine)


def test_queued_csv_owner_review_denies_tampered_private_output(postgres, monkeypatch):
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_queued_csv_pipeline import (
        submit_queued_csv, process_one_queued_csv, review_processed_csv,
        QueuedCSVBlocked,
    )
    engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    factory = lambda: Session(engine)
    try:
        created = submit_queued_csv(
            factory, organization_id="synthetic-org", owner_user_id="synthetic-owner",
            engagement_id="synthetic-eng", task_id="synthetic-csv-task",
            request_key="pipeline-tamper-output", raw=b"Name\nAda\n",
            store=store, authorize=lambda *_: True)
        assert process_one_queued_csv(factory, store=store,
                                      authorize=lambda *_: True)["state"] == "completed"
        with factory() as db:
            row = db.execute(sa.select(csvjobs.jobs).where(
                csvjobs.jobs.c.id == created["job_id"])).mappings().one()
            store.items[row["output_ref"]] = b"Name\nAltered\n"
        with pytest.raises(QueuedCSVBlocked, match="integrity failed"):
            review_processed_csv(
                factory, organization_id="synthetic-org",
                owner_user_id="synthetic-owner", job_id=created["job_id"],
                approve=True, authorize=lambda *_: True, store=store)
        with factory() as db:
            assert csvjobs.job_status(
                db, org="synthetic-org", owner="synthetic-owner",
                job_id=created["job_id"])["status"] == "AWAITING_REVIEW"
    finally:
        leases.lease_metadata.drop_all(engine)


def test_queued_csv_revocation_during_processing_never_approves(postgres, monkeypatch):
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_queued_csv_pipeline import (
        submit_queued_csv, process_one_queued_csv,
    )
    engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    factory = lambda: Session(engine)
    try:
        created = submit_queued_csv(
            factory, organization_id="synthetic-org", owner_user_id="synthetic-owner",
            engagement_id="synthetic-eng", task_id="synthetic-csv-task",
            request_key="pipeline-revoke-processing", raw=b"Name\nAda\n",
            store=store, authorize=lambda *_: True)
        decisions = iter([True, False])
        result = process_one_queued_csv(
            factory, store=store, authorize=lambda *_: next(decisions))
        assert result["state"] == "needs_reconciliation"
        with factory() as db:
            assert csvjobs.job_status(
                db, org="synthetic-org", owner="synthetic-owner",
                job_id=created["job_id"])["status"] == "PROCESSING"
            state = db.execute(sa.select(leases.lease_jobs.c.state).where(
                leases.lease_jobs.c.job_id == created["job_id"])).scalar_one()
            assert state == "NEEDS_RECONCILIATION"
    finally:
        leases.lease_metadata.drop_all(engine)


def test_queued_csv_write_readback_corruption_requires_reconciliation(postgres, monkeypatch):
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.core.nova.work_revenue.operations_queued_csv_pipeline import (
        submit_queued_csv, process_one_queued_csv,
    )
    engine, store = postgres
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    leases.lease_metadata.create_all(engine)
    factory = lambda: Session(engine)
    original_retrieve = store.retrieve
    try:
        created = submit_queued_csv(
            factory, organization_id="synthetic-org",
            owner_user_id="synthetic-owner", engagement_id="synthetic-eng",
            task_id="synthetic-csv-task", request_key="pipeline-readback",
            raw=b"Name\nAda\n", store=store, authorize=lambda *_: True)
        def corrupted_readback(*, storage_ref):
            if "nova-csv-review" in storage_ref:
                return b"Name\nBad\n", "text/csv"
            return original_retrieve(storage_ref=storage_ref)
        monkeypatch.setattr(store, "retrieve", corrupted_readback)
        response = process_one_queued_csv(factory, store=store,
                                          authorize=lambda *_: True)
        assert response == {"state": "needs_reconciliation",
                            "job_id": created["job_id"]}
        with factory() as db:
            status = csvjobs.job_status(
                db, org="synthetic-org", owner="synthetic-owner",
                job_id=created["job_id"])["status"]
            assert status == "PROCESSING"
            held = db.execute(sa.select(leases.lease_jobs.c.state).where(
                leases.lease_jobs.c.job_id == created["job_id"])).scalar_one()
            assert held == "NEEDS_RECONCILIATION"
    finally:
        leases.lease_metadata.drop_all(engine)


def test_supervised_owner_http_queue_process_review_packet(postgres, monkeypatch):
    """One actual FastAPI owner request cycle with disposable PG and fake S3."""
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.nova.router import require_nova_access
    from app.core.nova.work_revenue import operations_owner_csv_api as api
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.db.session import get_db

    engine, store = postgres
    leases.lease_metadata.create_all(engine)
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED", "true")
    owner = SimpleNamespace(user_id="synthetic-owner",
                            organization_id="synthetic-org",
                            email="owner@synthetic.invalid")
    eng = {
        "engagement_id": "synthetic-eng",
        "organization_id": "synthetic-org",
        "owner_user_id": "synthetic-owner",
        "status": "ACTIVE", "blockers": None,
        "tasks": [{
            "task_id": "synthetic-csv-task", "title": "CSV cleanup",
            "status": "READY", "classification": "NOVA",
            "responsible_party": "NOVA", "review_required": True,
            "blocked_reason": None, "required_owner_input": None,
            "depends_on_task_id": None,
        }],
    }
    monkeypatch.setattr(api.service, "get_engagement", lambda *args, **kwargs: eng)

    app = FastAPI()
    app.include_router(api.router, prefix="/api/nova/work")
    app.dependency_overrides[require_nova_access] = lambda: owner
    app.dependency_overrides[api.require_work_revenue_owner] = lambda: owner
    def db_session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = db_session
    prefix = "/api/nova/work/operations/queued"
    create_headers = {
        "Content-Type": "text/csv",
        "X-Nova-File-Name": "sample.csv",
        "Idempotency-Key": "supervised-e2e",
        "X-Nova-Scope-Confirmed": "owner-confirmed-client-authorization",
        "X-Nova-Owner-Action": "queue-csv-for-owner-review",
    }
    try:
        with TestClient(app) as client:
            url = prefix + "/engagements/synthetic-eng/tasks/synthetic-csv-task/jobs"
            created = client.post(url, headers=create_headers, content=b"Name\nAda\nAda\n")
            assert created.status_code == 202, created.text
            job_id = created.json()["job_id"]
            assert created.json()["status"] == "QUEUED"
            status = client.get(prefix + "/jobs/" + job_id)
            assert status.status_code == 200
            assert status.json()["lease_status"] == "QUEUED"
            assert status.json()["delivered"] is False
            assert "input_ref" not in status.json()
            assert client.get(prefix + "/jobs/" + job_id + "/download").status_code == 409
            duplicate = client.post(url, headers=create_headers, content=b"Name\nAda\nAda\n")
            assert duplicate.status_code == 202
            assert duplicate.json()["job_id"] == job_id
            assert duplicate.json()["replayed"] is True
            denied = client.post(prefix + "/jobs/" + job_id + "/process")
            assert denied.status_code == 403
            work = client.post(
                prefix + "/jobs/" + job_id + "/process",
                headers={"X-Nova-Owner-Action": "process-queued-csv-for-owner-review"})
            assert work.status_code == 200, work.text
            assert work.json() == {"state": "completed", "job_id": job_id,
                                   "delivered": False}
            pending = client.post(prefix + "/jobs/" + job_id + "/review",
                                  json={"approve": True})
            assert pending.status_code == 403
            approved = client.post(
                prefix + "/jobs/" + job_id + "/review",
                json={"approve": True},
                headers={"X-Nova-Owner-Action": "review-completed-queued-csv"})
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "APPROVED_FOR_DOWNLOAD"
            assert approved.json()["delivered"] is False
            downloaded = client.get(prefix + "/jobs/" + job_id + "/download")
            assert downloaded.status_code == 200
            assert downloaded.content == b"Name\nAda\n"
            assert downloaded.headers["X-Nova-Delivery-Status"] == "not-delivered"
            assert store.put_count == 2
            # Authorization revocation blocks even an already-completed job.
            eng["status"] = "BLOCKED"
            blocked = client.post(
                prefix + "/jobs/" + job_id + "/review", json={"approve": False},
                headers={"X-Nova-Owner-Action": "review-completed-queued-csv"})
            assert blocked.status_code == 409
            assert client.get(prefix + "/jobs/" + job_id + "/download").status_code == 409
    finally:
        leases.lease_metadata.drop_all(engine)


def test_supervised_http_routes_default_off_and_unknown_job_404(postgres, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.nova.router import require_nova_access
    from app.core.nova.work_revenue import operations_owner_csv_api as api
    from app.core.nova.work_revenue import operations_postgres_leases as leases
    from app.db.session import get_db
    engine, store = postgres
    leases.lease_metadata.create_all(engine)
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    monkeypatch.delenv("NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED", raising=False)
    user = SimpleNamespace(user_id="synthetic-owner",
                           organization_id="synthetic-org")
    app = FastAPI()
    app.include_router(api.router, prefix="/api/nova/work")
    app.dependency_overrides[require_nova_access] = lambda: user
    app.dependency_overrides[api.require_work_revenue_owner] = lambda: user
    def db_session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = db_session
    url = "/api/nova/work/operations/queued/jobs/absent"
    try:
        with TestClient(app) as client:
            assert client.get(url).status_code == 503
            assert client.post(url + "/process",
                headers={"X-Nova-Owner-Action": "process-queued-csv-for-owner-review"}
            ).status_code == 503
            monkeypatch.setenv("NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED", "true")
            assert client.get(url).status_code == 404
            assert client.post(url + "/process",
                headers={"X-Nova-Owner-Action": "process-queued-csv-for-owner-review"}
            ).status_code == 404
            assert client.post(url + "/review",
                json={"approve": True},
                headers={"X-Nova-Owner-Action": "review-completed-queued-csv"}
            ).status_code == 404
    finally:
        leases.lease_metadata.drop_all(engine)
