"""Atomic master claim fencing tests using a real SQLite SQLAlchemy table.

No provider requests, video generation, external services, or production writes.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.nova.creative_studio.calendar import (
    _master_claim_key,
    _swap_terminal_master_claim,
)

CLAIM_KEY = _master_claim_key("owner-a", "project-a", "entry-a")
from app.core.nova.creative_studio.db_models import NovaCreativeRenderClaim


def _claim_db(tmp_path, *, state="GENERATED"):
    engine = create_engine(f"sqlite:///{tmp_path / 'master-claims.db'}")
    NovaCreativeRenderClaim.__table__.create(engine, checkfirst=True)
    with Session(engine) as db:
        db.add(NovaCreativeRenderClaim(
            claim_key=CLAIM_KEY, owner_id="owner-a", project_id="project-a",
            entry_id="entry-a", job_id="old-job", state=state,
            checkpoint_json='{"stage":"SAVED_MASTER"}',
            updated_at="2026-11-09T00:00:00+00:00",
        ))
        db.commit()
    return engine


def _swap(db, **kwargs):
    return _swap_terminal_master_claim(
        db, claim_key=CLAIM_KEY,
        owner_id=kwargs.get("owner_id", "owner-a"),
        project_id=kwargs.get("project_id", "project-a"),
        entry_id=kwargs.get("entry_id", "entry-a"),
        expected_job_id=kwargs.get("expected_job_id", "old-job"),
        expected_state=kwargs.get("expected_state", "GENERATED"),
        next_job_id=kwargs.get("next_job_id", "new-job"),
        checkpoint_json='{"stage":"QUEUED"}',
        updated_at="2026-11-09T00:01:00+00:00",
    )


def test_terminal_claim_is_atomically_queued_once(tmp_path):
    engine = _claim_db(tmp_path)
    try:
        with Session(engine) as first:
            assert _swap(first) is True
            first.commit()
        with Session(engine) as competing:
            # This process saw the old terminal claim. Its stale compare-and-swap
            # must never overwrite the newly queued job.
            assert _swap(competing, next_job_id="competing-job") is False
            competing.rollback()
        with Session(engine) as check:
            row = check.get(NovaCreativeRenderClaim, CLAIM_KEY)
            assert row.job_id == "new-job"
            assert row.state == "QUEUED"
            assert row.checkpoint_json == '{"stage":"QUEUED"}'
    finally:
        engine.dispose()


def test_terminal_claim_swap_requires_correct_tenant_and_job(tmp_path):
    engine = _claim_db(tmp_path)
    try:
        with Session(engine) as db:
            assert not _swap(db, owner_id="other-owner")
            assert not _swap(db, project_id="other-project")
            assert not _swap(db, entry_id="other-entry")
            assert not _swap(db, expected_job_id="old-job-from-another-process")
            db.rollback()
        with Session(engine) as check:
            row = check.get(NovaCreativeRenderClaim, CLAIM_KEY)
            assert row.job_id == "old-job"
            assert row.state == "GENERATED"
    finally:
        engine.dispose()


def test_terminal_claim_swap_refuses_running_or_wrong_state(tmp_path):
    engine = _claim_db(tmp_path, state="RUNNING")
    try:
        with Session(engine) as db:
            assert not _swap(db)
            assert not _swap(db, expected_state="RUNNING")
            assert not _swap(db, expected_state="ERROR")
            db.rollback()
        with Session(engine) as check:
            row = check.get(NovaCreativeRenderClaim, CLAIM_KEY)
            assert row.job_id == "old-job"
            assert row.state == "RUNNING"
    finally:
        engine.dispose()


def test_failed_claim_can_be_explicitly_requeued(tmp_path):
    engine = _claim_db(tmp_path, state="ERROR")
    try:
        with Session(engine) as db:
            assert _swap(db, expected_state="ERROR") is True
            db.commit()
        with Session(engine) as check:
            row = check.get(NovaCreativeRenderClaim, CLAIM_KEY)
            assert row.job_id == "new-job"
            assert row.state == "QUEUED"
    finally:
        engine.dispose()


def test_only_matching_running_claim_can_be_completed(tmp_path):
    from app.core.nova.creative_studio.calendar import _finish_master_claim
    engine = _claim_db(tmp_path, state="RUNNING")
    try:
        with Session(engine) as db:
            assert _finish_master_claim(
                db, "owner-a", "project-a", "entry-a", "wrong-job", "GENERATED"
            ) is False
            assert _finish_master_claim(
                db, "other-owner", "project-a", "entry-a", "old-job", "GENERATED"
            ) is False
            assert _finish_master_claim(
                db, "owner-a", "project-a", "entry-a", "old-job", "GENERATED"
            ) is True
            assert _finish_master_claim(
                db, "owner-a", "project-a", "entry-a", "old-job", "ERROR"
            ) is False
        with Session(engine) as db:
            row = db.get(NovaCreativeRenderClaim, CLAIM_KEY)
            assert row.job_id == "old-job"
            assert row.state == "GENERATED"
    finally:
        engine.dispose()


def test_terminal_claim_status_rejects_unrecognized_state(tmp_path):
    import pytest
    from app.core.nova.creative_studio.calendar import _finish_master_claim
    engine = _claim_db(tmp_path, state="RUNNING")
    try:
        with Session(engine) as db:
            with pytest.raises(ValueError, match="Invalid terminal"):
                _finish_master_claim(
                    db, "owner-a", "project-a", "entry-a", "old-job", "QUEUED"
                )
    finally:
        engine.dispose()
