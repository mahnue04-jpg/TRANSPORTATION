"""Disposable PostgreSQL acceptance for owner-scoped scheduled Work & Revenue.

No public providers, applications, mail, payments or production connection.
"""
from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.core.nova.v3.autopilot_staging_guard import inspect_configuration
from app.core.nova.v3.scheduled_autopilot import run_staging_cycle, AutopilotGuardError
from app.core.nova.work_revenue.models import NovaWorkSchedulerJob
from app.db.models import User
from app.db.session import Base

WHEN = datetime(2026, 11, 12, 5, 0, tzinfo=ZoneInfo("America/Chicago"))
CONFIG = {
    "APP_ENV": "staging", "AMICOR_ENVIRONMENT": "staging",
    "NOVA_WORK_AUTOPILOT_STAGING_ENABLED": "true",
    "NOVA_WORK_AUTOPILOT_APPROVED_DATABASE": "nova_discovery_ci",
    "NOVA_WORK_AUTOPILOT_OWNER_ORG_ID": "synthetic-org",
    "NOVA_WORK_AUTOPILOT_OWNER_USER_ID": "synthetic-owner",
}


@pytest.fixture
def postgres():
    url = os.environ.get("NOVA_WORK_AUTOPILOT_CI_POSTGRES_URL", "")
    if not (url.startswith("postgresql+psycopg2://")
            and "@127.0.0.1:" in url and url.endswith("/nova_discovery_ci")):
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("Approved disposable localhost CI PostgreSQL is required")
        pytest.skip("Disposable localhost CI PostgreSQL only")
    engine = create_engine(url, pool_size=4, max_overflow=2)
    with engine.begin() as conn:
        User.__table__.create(conn, checkfirst=True)
        NovaWorkSchedulerJob.__table__.create(conn, checkfirst=True)
        conn.execute(User.__table__.insert().values(
            id="synthetic-owner", email="owner@example.invalid",
            hashed_password="synthetic-only-not-valid",
            role="dispatcher", organization_id="synthetic-org",
            organization_name="Synthetic Nova", is_active=True,
            is_verified=True,
        ))
    yield engine
    with engine.begin() as conn:
        NovaWorkSchedulerJob.__table__.drop(conn, checkfirst=True)
        User.__table__.drop(conn, checkfirst=True)
    engine.dispose()


def sample_cycle(calls):
    def cycle(db, *, organization_id, user, **kwargs):
        calls.append((organization_id, user.user_id, kwargs))
        assert organization_id == "synthetic-org"
        assert user.user_id == "synthetic-owner"
        assert kwargs["min_relevance_score"] == 85
        return {
            "selected_count": 2, "ready_for_owner_review_count": 1,
            "live_search_status": "available", "external_action_taken": False,
            "external_submission": False, "financial_execution": False,
            "contract_acceptance": False, "agency_contact": False,
        }
    return cycle


def test_pure_preflight_denies_production_and_wrong_time():
    for change in (
        {"APP_ENV": "production"},
        {"AMICOR_ENVIRONMENT": "production"},
        {"NOVA_WORK_AUTOPILOT_STAGING_ENABLED": "false"},
        {"NOVA_WORK_AUTOPILOT_APPROVED_DATABASE": "amicor-prod"},
        {"NOVA_WORK_AUTOPILOT_OWNER_USER_ID": ""},
    ):
        c = dict(CONFIG, **change)
        assert inspect_configuration(c, at=WHEN)["status"] == "BLOCKED"
    off_time = datetime(2026, 11, 12, 6, tzinfo=ZoneInfo("America/Chicago"))
    assert inspect_configuration(CONFIG, at=off_time)["status"] == "BLOCKED"


def test_staging_postgres_first_run_records_day_and_suppresses_repeat(postgres):
    calls = []
    first = run_staging_cycle(postgres, config=CONFIG, at=WHEN, cycle=sample_cycle(calls))
    assert first["status"] == "STAGING_CYCLE_COMPLETED"
    assert first["selected_count"] == 2
    second = run_staging_cycle(postgres, config=CONFIG, at=WHEN, cycle=sample_cycle(calls))
    assert second["status"] == "ALREADY_RECORDED"
    assert second["previous_status"] == "PREPARED"
    assert len(calls) == 1
    with Session(postgres) as db:
        jobs = db.query(NovaWorkSchedulerJob).all()
        assert len(jobs) == 1
        assert jobs[0].status == "PREPARED"
        assert jobs[0].owner_user_id == "synthetic-owner"
        assert jobs[0].period_key == "AUTO_DISCOVERY:2026-11-12"


def test_staging_runner_fails_if_database_identity_wrong(postgres):
    bad = dict(CONFIG, NOVA_WORK_AUTOPILOT_APPROVED_DATABASE="another_db")
    with pytest.raises(AutopilotGuardError, match="Database identity"):
        run_staging_cycle(postgres, config=bad, at=WHEN, cycle=sample_cycle([]))
    with Session(postgres) as db:
        assert db.query(NovaWorkSchedulerJob).count() == 0


def test_staging_runner_requires_active_verified_owner(postgres):
    with Session(postgres) as db:
        row = db.query(User).filter(User.id == "synthetic-owner").one()
        row.is_verified = False
        db.commit()
    with pytest.raises(AutopilotGuardError, match="verified owner"):
        run_staging_cycle(postgres, config=CONFIG, at=WHEN, cycle=sample_cycle([]))
    with Session(postgres) as db:
        assert db.query(NovaWorkSchedulerJob).count() == 0


def test_failed_cycle_is_recorded_once_and_not_replayed(postgres):
    count = []
    def broken(*args, **kwargs):
        count.append(1)
        raise RuntimeError("synthetic provider timeout")
    with pytest.raises(RuntimeError, match="timeout"):
        run_staging_cycle(postgres, config=CONFIG, at=WHEN, cycle=broken)
    result = run_staging_cycle(postgres, config=CONFIG, at=WHEN, cycle=broken)
    assert result["status"] == "ALREADY_RECORDED"
    assert result["previous_status"] == "FAILED"
    assert len(count) == 1
    with Session(postgres) as db:
        record = db.query(NovaWorkSchedulerJob).one()
        assert record.status == "FAILED"
        assert "provider timeout" not in (record.notes or "")


def test_misbehaving_cycle_cannot_claim_external_submission(postgres):
    def dangerous(*args, **kwargs):
        return {"external_submission": True, "selected_count": 1}
    with pytest.raises(AutopilotGuardError, match="forbidden external"):
        run_staging_cycle(postgres, config=CONFIG, at=WHEN, cycle=dangerous)
    with Session(postgres) as db:
        record = db.query(NovaWorkSchedulerJob).one()
        assert record.status == "FAILED"


def test_unavailable_discovery_sources_do_not_claim_success(postgres):
    def offline_sources(*args, **kwargs):
        return {
            "live_search_status": "unavailable",
            "selected_count": 0, "ready_for_owner_review_count": 0,
            "external_submission": False, "external_action_taken": False,
            "financial_execution": False,
        }
    result = run_staging_cycle(
        postgres, config=CONFIG, at=WHEN, cycle=offline_sources,
    )
    assert result["status"] == "SOURCE_UNAVAILABLE"
    assert result["source_unavailable"] is True
    with Session(postgres) as db:
        row = db.query(NovaWorkSchedulerJob).one()
        assert row.status == "SKIPPED"
        assert "Sources unavailable" in row.notes
