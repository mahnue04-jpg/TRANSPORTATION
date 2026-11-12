"""Persist and recover a synthetic Nova job after closing its database session.

This deliberately uses a temporary SQLite database and a filesystem-backed
fake private store, NEVER a customer file or a live Render connection.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import bookkeeping_durable_jobs as finance
from app.core.nova.work_revenue import operations_customer_csv_jobs as legacy
from app.core.nova.work_revenue.bookkeeping_assignment import BookkeepingAssignment


class SyntheticRestartStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def store(self, *, organization_id, application_id, category,
              filename, content_type, stream):
        assert organization_id == "synthetic-org"
        assert category == "nova-bookkeeping-review"
        assert filename == "bookkeeping-review.csv"
        assert content_type == "text/csv"
        key = f"{organization_id}/{application_id}/{category}/{filename}"
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        body = stream.read()
        dest.write_bytes(body)
        return "synthetic", key, len(body)

    def retrieve(self, *, storage_ref):
        root = self.root.resolve()
        dest = (self.root / storage_ref).resolve()
        if not dest.is_relative_to(root):
            raise ValueError("Invalid simulated storage path")
        return dest.read_bytes(), "text/csv"

    def delete(self, *, storage_ref):
        (self.root / storage_ref).unlink()


def test_synthetic_bookkeeping_job_survives_database_reopen(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'mock_jobs.sqlite'}")
    legacy.metadata.create_all(engine)
    storage = SyntheticRestartStore(tmp_path / "private")
    monkeypatch.setattr(legacy, "require_runtime", lambda session: None)
    monkeypatch.setattr(legacy, "_store", lambda: storage)
    monkeypatch.setenv("NOVA_BOOKKEEPING_DURABLE_ENABLED", "true")
    assignment = BookkeepingAssignment(
        organization_id="synthetic-org",
        owner_user_id="synthetic-owner",
        engagement_id="synthetic-engagement",
        task_id="synthetic-task",
        work_type="payables_aging",
        ai_assistance_permitted=True,
        data_processing_authorized=True,
        human_review_required=True,
        contracted_work_types=frozenset({"payables_aging"}),
    )
    csv_source = (
        b"bill_id,vendor,bill_date,due_date,amount,paid\n"
        b"B1,Test Vendor,2026-11-01,2026-11-10,100.00,25.00\n"
    )
    with Session(engine) as db:
        result = finance.submit_bookkeeping_review(
            db, assignment=assignment, request_id="restart-check-1",
            primary=csv_source, as_of="2026-11-11",
        )
        job_id = result["job_id"]
        digest = result["output_sha256"]
        assert result["status"] == "AWAITING_REVIEW"
    engine.dispose()

    # A fresh database engine and session simulate process restart. The job
    # and private workpaper remain readable through the same owner scope.
    reopened = create_engine(f"sqlite:///{tmp_path / 'mock_jobs.sqlite'}")
    with Session(reopened) as db:
        state = finance.bookkeeping_status(
            db, org="synthetic-org", owner="synthetic-owner", job_id=job_id,
        )
        assert state["status"] == "AWAITING_REVIEW"
        assert state["work_type"] == "payables_aging"
        try:
            finance.download_bookkeeping(
                db, org="synthetic-org", owner="other-owner", job_id=job_id,
            )
        except legacy.CustomerCSVBlocked as exc:
            assert exc.code == 404
        else:
            raise AssertionError("Cross-owner read unexpectedly succeeded")
        contents = finance.download_bookkeeping(
            db, org="synthetic-org", owner="synthetic-owner", job_id=job_id,
        )
        assert b"75.00" in contents
        assert hashlib.sha256(contents).hexdigest() == digest
        approved = finance.review_bookkeeping(
            db, org="synthetic-org", owner="synthetic-owner",
            job_id=job_id, approve=True,
        )
        assert approved["status"] == "APPROVED_FOR_DOWNLOAD"
        assert not approved["delivered"]
    reopened.dispose()

    # Confirm a second restart retains the approval state but NEVER marks
    # a simulated job as delivered to a customer.
    third = create_engine(f"sqlite:///{tmp_path / 'mock_jobs.sqlite'}")
    with Session(third) as db:
        again = finance.bookkeeping_status(
            db, org="synthetic-org", owner="synthetic-owner", job_id=job_id,
        )
        assert again["status"] == "APPROVED_FOR_DOWNLOAD"
        assert again["delivered"] is False
    third.dispose()
