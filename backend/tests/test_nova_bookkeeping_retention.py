"""Synthetic, non-destructive retention review; no customer records."""
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_customer_csv_jobs as jobs
from app.core.nova.work_revenue.bookkeeping_retention import (
    MAX_BATCH, RetentionInspectionBlocked, plan_bookkeeping_retention,
)

NOW = datetime(2026, 11, 11, 18, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    jobs.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed(db, *, key="bookkeeping:receivables_aging:synthetic-1", state="FAILED",
         org="synthetic-org", owner="synthetic-owner", age=40, output_ref=None,
         output_sha256=None, row_id=None):
    db.execute(sa.insert(jobs.jobs).values(
        id=row_id or f"test-id-{key}-{owner}", organization_id=org,
        owner_user_id=owner, engagement_id="synthetic-eng",
        task_id="synthetic-task", request_key=key,
        input_sha256="a"*64, status=state,
        output_ref=output_ref, output_sha256=output_sha256,
        created_at=NOW-timedelta(days=age), updated_at=NOW-timedelta(days=age),
    ))
    db.commit()


def inspect(db, **changes):
    opts = dict(organization_id="synthetic-org", owner_user_id="synthetic-owner",
                older_than_days=30, now=NOW)
    opts.update(changes)
    return plan_bookkeeping_retention(db, **opts)


def test_only_exact_owner_and_accounting_jobs_included(db):
    seed(db, key="bookkeeping:receivables_aging:syn-1", row_id="bk1",
         state="REJECTED", output_ref="private/one", output_sha256="b"*64)
    seed(db, key="bookkeeping:payables_aging:syn-2", row_id="bk2",
         state="AWAITING_REVIEW", output_ref="private/two", output_sha256="c"*64)
    seed(db, key="ordinary-csv", row_id="normal", state="FAILED")
    seed(db, key="bookkeeping:payables_aging:other-org", row_id="other-org", org="org-b")
    seed(db, key="bookkeeping:payables_aging:other-owner", row_id="other-owner", owner="other-owner")
    seed(db, key="bookkeeping:payables_aging:recent", row_id="recent", age=1)
    before = db.execute(sa.select(sa.func.count()).select_from(jobs.jobs)).scalar_one()
    result = inspect(db)
    assert result["examined_count"] == 2
    assert result["counts"]["terminal_review"] == 1
    assert result["counts"]["active_review_hold"] == 1
    assert "active_review_hold" in result["blockers"]
    assert result["objects_deleted"] == 0
    assert result["database_rows_changed"] == 0
    assert result["deletion_authorized"] is False
    assert db.execute(sa.select(sa.func.count()).select_from(jobs.jobs)).scalar_one() == before
    assert "private/one" not in repr(result)


def test_invalid_scope_days_and_dates_are_rejected(db):
    for change in (
        {"organization_id": "global"}, {"organization_id": ""},
        {"owner_user_id": ""}, {"older_than_days": 0},
        {"older_than_days": 3651}, {"older_than_days": True},
        {"now": datetime(2026,11,11)},
    ):
        with pytest.raises(RetentionInspectionBlocked):
            inspect(db, **change)


def test_empty_scoped_inventory_never_authorizes_deletion(db):
    result = inspect(db)
    assert result["mode"] == "DRY_RUN_INSPECTION_ONLY"
    assert result["examined_count"] == 0
    assert result["deletion_authorized"] is False
    assert "independent_retention_and_client_consent_review" in result["blockers"]


def test_inconsistent_metadata_is_manual_blocker(db):
    seed(db, row_id="part-1", output_ref="private/asset",
         output_sha256=None)
    result = inspect(db)
    assert result["counts"]["inconsistent_metadata"] == 1
    assert "inconsistent_metadata" in result["blockers"]


def test_more_than_max_batch_rejected(db):
    for n in range(MAX_BATCH + 1):
        db.execute(sa.insert(jobs.jobs).values(
            id=f"synthetic-{n}", organization_id="synthetic-org",
            owner_user_id="synthetic-owner", engagement_id="eng",
            task_id="task", request_key=f"bookkeeping:payables_aging:{n}",
            input_sha256="a"*64, status="FAILED",
            created_at=NOW-timedelta(days=60),
            updated_at=NOW-timedelta(days=60),
        ))
    db.commit()
    with pytest.raises(RetentionInspectionBlocked, match="500"):
        inspect(db)
