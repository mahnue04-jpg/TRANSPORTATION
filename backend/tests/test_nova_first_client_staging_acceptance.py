"""Synthetic first-client acceptance, runnable on ephemeral CI PostgreSQL.

Not a hosted Render staging pass: PostgreSQL is disposable and private storage
is a persistent-on-disk *test double*, not live S3. No outbound messages.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import hashlib

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_customer_csv_jobs as customer_csv
from app.core.nova.work_revenue import work_inputs
from app.core.nova.work_revenue.service import NovaWorkError

from tests.test_nova_operations_customer_csv_postgres import postgres


class RestartablePrivateStore:
    """Synthetic private object storage: a fresh adapter reads the same files."""

    def __init__(self, root: Path):
        self.root = root

    def _location(self, storage_ref: str) -> Path:
        # Synthetic object keys must not escape the dedicated test directory.
        parts = Path(storage_ref).parts
        if not parts or any(part in {"..", ".", ""} for part in parts):
            raise ValueError("Invalid synthetic private object key")
        return self.root.joinpath(*parts)

    def store(self, *, organization_id, application_id, category, filename,
              content_type, stream):
        key = f"{organization_id}/{application_id}/{category}/{filename}"
        location = self._location(key)
        location.parent.mkdir(parents=True, exist_ok=True)
        raw = stream.read()
        location.write_bytes(raw)
        return "synthetic-private", key, len(raw)

    def retrieve(self, *, storage_ref):
        return self._location(storage_ref).read_bytes(), "text/csv"

    def delete(self, *, storage_ref):
        self._location(storage_ref).unlink(missing_ok=True)


class SyntheticSession:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)

    def commit(self):
        pass

    def refresh(self, record):
        pass


def test_first_client_authorized_input_to_review_survives_process_restart(
    postgres, tmp_path, monkeypatch,
):
    """Complete *synthetic* customer intake->processing->approval after restart."""
    engine, _memory_store = postgres
    root = tmp_path / "private-persistent-test-store"
    # Staging-like data-handling gates, but NO live S3 credentials or customer.
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "s3_private")
    monkeypatch.setattr(work_inputs, "S3PrivateDocumentStorage",
                        lambda: RestartablePrivateStore(root))
    monkeypatch.setattr(customer_csv, "_store", lambda: RestartablePrivateStore(root))
    monkeypatch.setattr(work_inputs, "get_engagement", lambda *args, **kwargs: {
        "engagement_id": "synthetic-eng",
        "status": "ACTIVE",
        "blockers": None,
        "client_name": "Synthetic Example Customer (not real)",
    })
    monkeypatch.setattr(work_inputs, "_record_audit", lambda *args, **kwargs: None)

    organization = "synthetic-org"
    owner = "synthetic-owner"
    session = SyntheticSession()
    raw = b"Name,Amount\nAda,10\nAda,10\nBen,20\n"

    # 1. Owner-asserted authorization, production-safe client input storage.
    with pytest.raises(NovaWorkError, match="owner confirmation"):
        work_inputs.create_work_input(
            session, "synthetic-eng", organization_id=organization,
            user=SimpleNamespace(user_id=owner),
            filename="synthetic.csv", content_type="text/csv", content=raw,
        )
    assert not session.records
    accepted = work_inputs.create_work_input(
        session, "synthetic-eng", organization_id=organization,
        user=SimpleNamespace(user_id=owner),
        filename="synthetic.csv", content_type="text/csv", content=raw,
        owner_confirmed_contract=True,
    )
    assert accepted["file_size"] == len(raw)
    record = session.records[0]
    assert record.storage_ref.startswith("s3-private:")
    assert work_inputs.read_work_input_bytes(record) == raw

    # 2. Operations receives the same verified input under a synthetic task.
    with Session(engine) as db:
        created = customer_csv.submit_review_job(
            db, org=organization, owner=owner,
            engagement_id="synthetic-eng", task_id="synthetic-csv-task",
            request_key="acceptance-run-20261113",
            raw=work_inputs.read_work_input_bytes(record),
        )
    assert created["status"] == "AWAITING_REVIEW"
    assert created["replayed"] is False
    job_id = created["job_id"]

    # 3. Simulate a restart: dispose DB pool and reconstruct engine + store.
    # SQLAlchemy URL.__str__ redacts passwords; retain the URL object to reconnect.
    db_url = engine.url
    engine.dispose()
    restarted_engine = sa.create_engine(db_url, pool_size=2, max_overflow=0)
    try:
        assert work_inputs.read_work_input_bytes(record) == raw
        with Session(restarted_engine) as db:
            observed = customer_csv.job_status(
                db, org=organization, owner=owner, job_id=job_id,
            )
            assert observed["status"] == "AWAITING_REVIEW"
            # 4. Review and verify exact output; never mark customer delivery.
            result = customer_csv.download_review(
                db, org=organization, owner=owner, job_id=job_id,
            )
            assert result == b"Name,Amount\nAda,10\nBen,20\n"
            assert hashlib.sha256(result).hexdigest() == created["output_sha256"]
            with pytest.raises(customer_csv.CustomerCSVBlocked) as forbidden:
                customer_csv.download_review(
                    db, org=organization, owner="unrelated-owner", job_id=job_id,
                )
            assert forbidden.value.code == 404
            reviewed = customer_csv.review_job(
                db, org=organization, owner=owner, job_id=job_id, approve=True,
            )
            assert reviewed["status"] == "APPROVED_FOR_DOWNLOAD"
            assert reviewed["delivered"] is False
        # 5. A second restart retains approved bytes and no duplicate work.
        restarted_engine.dispose()
        restarted_engine = sa.create_engine(db_url, pool_size=2, max_overflow=0)
        with Session(restarted_engine) as db:
            assert customer_csv.job_status(
                db, org=organization, owner=owner, job_id=job_id,
            )["status"] == "APPROVED_FOR_DOWNLOAD"
            assert customer_csv.download_review(
                db, org=organization, owner=owner, job_id=job_id,
            ) == b"Name,Amount\nAda,10\nBen,20\n"
            replay = customer_csv.submit_review_job(
                db, org=organization, owner=owner,
                engagement_id="synthetic-eng", task_id="synthetic-csv-task",
                request_key="acceptance-run-20261113", raw=raw,
            )
            assert replay["replayed"] is True
            assert replay["job_id"] == job_id
            assert replay["status"] == "APPROVED_FOR_DOWNLOAD"
        assert len(list(root.rglob("cleaned.csv"))) == 1
    finally:
        restarted_engine.dispose()
