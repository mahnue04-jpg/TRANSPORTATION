"""Staging-only scheduled Work & Revenue discovery entrypoint.

Performs one bounded cycle for a VERIFIED saved owner in an independently
approved isolated staging database. Never runs against production, SQLite,
casting, or a default/seed owner. Does not submit, contact, charge or accept.
Deployment and scheduler configuration require separate owner approval.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.v3.autopilot_cycle import run_autopilot_cycle
from app.db.models import User
from app.core.nova.work_revenue.models import NovaWorkSchedulerJob
from app.helpers import now, uuid4

from app.core.nova.v3.autopilot_staging_guard import inspect_configuration, FORBIDDEN_DATABASES
LOCK_NAMESPACE = "amicor:nova:work-revenue:scheduled-discovery"


class AutopilotGuardError(RuntimeError):
    """Configuration or authorization is insufficient for a scheduled run."""


def run_staging_cycle(
    engine: Engine,
    *,
    config: Mapping[str, str],
    at: datetime | None = None,
    cycle: Callable = run_autopilot_cycle,
) -> dict:
    """Run once with a PostgreSQL advisory lock held on a dedicated connection.

    An external daily trigger may invoke twice at 10/11 UTC for DST but the
    5AM Central gate selects exactly one invocation. A crash may cause a
    later retry; saved opportunity idempotency still applies.
    """
    plan = inspect_configuration(config, at=at)
    if plan["status"] != "READY_TO_ATTEMPT_STAGING_CYCLE":
        return plan
    if engine.dialect.name != "postgresql":
        raise AutopilotGuardError("Dedicated PostgreSQL is required")
    expected_db = str(config["NOVA_WORK_AUTOPILOT_APPROVED_DATABASE"]).strip()
    org = str(config["NOVA_WORK_AUTOPILOT_OWNER_ORG_ID"]).strip()
    owner_id = str(config["NOVA_WORK_AUTOPILOT_OWNER_USER_ID"]).strip()
    with engine.connect() as guard:
        actual_db = guard.execute(text("SELECT current_database()")).scalar_one()
        if actual_db != expected_db or actual_db.lower() in FORBIDDEN_DATABASES:
            raise AutopilotGuardError("Database identity did not match approved isolated staging")
        key = f"{LOCK_NAMESPACE}:{org}:{owner_id}:{plan['local_period']}"
        locked = bool(guard.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": key},
        ).scalar_one())
        if not locked:
            return {**plan, "status": "ALREADY_RUNNING", "external_submission": False}
        try:
            with Session(engine) as db:
                saved = db.query(User).filter(
                    User.id == owner_id,
                    User.organization_id == org,
                    User.is_active.is_(True),
                    User.is_verified.is_(True),
                ).one_or_none()
                if saved is None:
                    raise AutopilotGuardError("No matching active verified owner in approved staging")
                user = UserContext(
                    user_id=saved.id,
                    email=saved.email,
                    role=saved.role,
                    organization_id=org,
                    organization_name=saved.organization_name,
                )
                # Persist an exact owner/day marker BEFORE network discovery.
                # The existing database-enforced unique period index prevents
                # another invocation from running after a worker restart.
                # An interrupted run remains RUNNING for manual investigation
                # instead of silently rerunning possibly committed work.
                period_key = "AUTO_DISCOVERY:" + plan["local_period"]
                existing = db.query(NovaWorkSchedulerJob).filter(
                    NovaWorkSchedulerJob.organization_id == org,
                    NovaWorkSchedulerJob.owner_user_id == owner_id,
                    NovaWorkSchedulerJob.job_kind == "AUTO_DISCOVERY",
                    NovaWorkSchedulerJob.period_key == period_key,
                ).one_or_none()
                if existing is not None:
                    return {
                        "status": "ALREADY_RECORDED",
                        "period": plan["local_period"],
                        "previous_status": existing.status,
                        "external_submission": False,
                        "production_release_authorized": False,
                    }
                marker = NovaWorkSchedulerJob(
                    id=uuid4(), job_id="NWJ-" + uuid4().replace("-", "")[:20],
                    organization_id=org, owner_user_id=owner_id,
                    job_kind="AUTO_DISCOVERY", period_key=period_key,
                    status="RUNNING", timezone="America/Chicago",
                    title="Staging Work & Revenue discovery — owner review only",
                    notes="No external send, client contact, contract or financial action",
                )
                db.add(marker)
                db.commit()
                try:
                    result = cycle(
                        db, organization_id=org, user=user,
                        query_limit=3, per_query_limit=5, save_limit=8,
                        prepare_limit=3, min_relevance_score=85,
                    )
                    if (
                        result.get("external_action_taken")
                        or result.get("external_submission")
                        or result.get("financial_execution")
                        or result.get("contract_acceptance")
                        or result.get("agency_contact")
                    ):
                        raise AutopilotGuardError("Cycle returned forbidden external action")
                    source_status = str(result.get("live_search_status") or "unavailable")
                    marker.status = "SKIPPED" if source_status == "unavailable" else "PREPARED"
                    marker.notes = (
                        "Sources unavailable; operator review before retry."
                        if marker.status == "SKIPPED" else
                        "Discovery checked; owner review required. No external action."
                    )
                    marker.updated_at = now()
                    db.commit()
                except Exception:
                    db.rollback()
                    marker = db.query(NovaWorkSchedulerJob).filter(
                        NovaWorkSchedulerJob.id == marker.id
                    ).one()
                    marker.status = "FAILED"
                    marker.notes = "Discovery failed; operator review before any retry."
                    marker.updated_at = now()
                    db.commit()
                    raise
                return {
                    "status": (
                        "SOURCE_UNAVAILABLE" if result.get("live_search_status") == "unavailable"
                        else "STAGING_CYCLE_COMPLETED"
                    ),
                    "period": plan["local_period"],
                    "selected_count": int(result.get("selected_count") or 0),
                    "ready_for_owner_review_count": int(result.get("ready_for_owner_review_count") or 0),
                    "live_search_status": str(result.get("live_search_status") or "unavailable"),
                    "source_unavailable": result.get("live_search_status") == "unavailable",
                    "external_submission": False,
                    "production_release_authorized": False,
                    "continuous_worker": False,
                }
        finally:
            guard.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": key})
