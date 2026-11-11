"""Dedicated, default-off Operations recovery worker for isolated staging.

Launch only after separate staging approval and configuration:
  python -m app.core.nova.work_revenue.operations_recovery_worker --once

For a supervised dedicated staging worker service:
  python -m app.core.nova.work_revenue.operations_recovery_worker --loop

No public endpoint, client delivery, billing, production DB, or credential
fallback. The worker resolves an active AMICOR owner from staging PostgreSQL
before each pass and rechecks authorization through saved engagements.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.auth import UserContext
from app.db.models import User
from . import operations_recoverable_csv as recovery
from .operations_customer_csv_jobs import CustomerCSVBlocked
from .operations_owner_csv_api import _check_saved_csv_assignment
from .owner_auth import _work_revenue_owner_emails

LOG = logging.getLogger("nova.operations.recovery.worker")
STAGING_URL_ENV = "NOVA_OPERATIONS_STAGING_DATABASE_URL"
STAGING_APPROVAL_ENV = "NOVA_OPERATIONS_STAGING_DB_APPROVED"
WORKER_ENABLED_ENV = "NOVA_OPERATIONS_RECOVERY_WORKER_ENABLED"
OWNER_EMAIL_ENV = "NOVA_OPERATIONS_RECOVERY_OWNER_EMAIL"


def _stage_only_config() -> tuple[str, str]:
    """Never fall back to application's DATABASE_URL or a demo owner."""
    envs = {os.getenv(name, "").strip().lower() for name in (
        "AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV",
    ) if os.getenv(name)}
    if envs != {"staging"}:
        raise CustomerCSVBlocked("Recovery worker is staging-only", 503)
    if os.getenv(WORKER_ENABLED_ENV, "").strip().lower() != "true":
        raise CustomerCSVBlocked("Recovery worker disabled by default", 503)
    if os.getenv(STAGING_APPROVAL_ENV, "").strip() != "isolated-reviewed":
        raise CustomerCSVBlocked("Dedicated staging database not approved", 503)
    database_url = os.getenv(STAGING_URL_ENV, "").strip()
    if not database_url:
        raise CustomerCSVBlocked("Dedicated staging database URL required", 503)
    try:
        parsed = sa.engine.make_url(database_url)
    except Exception as exc:
        raise CustomerCSVBlocked("Invalid staging database URL", 503) from exc
    if not parsed.drivername.startswith("postgresql"):
        raise CustomerCSVBlocked("Recovery staging requires PostgreSQL", 503)
    # Prevent accidental use of the application's configured main database.
    main_url = os.getenv("DATABASE_URL", "").strip()
    if main_url:
        try:
            main_parsed = sa.engine.make_url(main_url)
            # Compare server and database independently of credentials: two
            # usernames may still target the same production database.
            if (
                parsed.host == main_parsed.host
                and (parsed.port or 5432) == (main_parsed.port or 5432)
                and parsed.database == main_parsed.database
            ):
                raise CustomerCSVBlocked("Worker database must be isolated", 503)
        except sa.exc.ArgumentError:
            raise CustomerCSVBlocked("Unsafe application database URL", 503)
    name = (parsed.database or "").lower()
    if (not name or "stag" not in name or not any(
        term in name for term in ("nova", "operations")
    ) or any(term in name for term in ("prod", "casting"))):
        raise CustomerCSVBlocked("Dedicated Operations staging database required", 503)
    email = os.getenv(OWNER_EMAIL_ENV, "").strip().lower()
    if not email or email not in _work_revenue_owner_emails():
        raise CustomerCSVBlocked("Verified Work and Revenue owner required", 403)
    return database_url, email


def _staging_owner(db: Session, email: str) -> UserContext:
    record = db.execute(sa.select(User).where(sa.func.lower(User.email) == email)).scalar_one_or_none()
    if (record is None or record.is_active is not True
            or not record.organization_id
            or str(record.organization_id).strip().lower() == "global"):
        raise CustomerCSVBlocked("Active scoped staging owner missing", 403)
    return UserContext(
        user_id=str(record.id), email=record.email, role=record.role,
        organization_id=str(record.organization_id),
        organization_name=record.organization_name,
    )


def run_once(session_factory, *, owner_email: str, limit: int = 5) -> dict:
    """One scoped pass, with a fresh authenticated staging owner lookup."""
    with session_factory() as db:
        recovery.require_runtime(db)
        owner = _staging_owner(db, owner_email)
        def check_assignment(engagement_id, task_id):
            _check_saved_csv_assignment(
                db, owner=owner, engagement_id=engagement_id,
                task_id=task_id,
            )
        result = recovery.run_due_jobs(
            db, org=str(owner.organization_id), owner=str(owner.user_id),
            authorization_check=check_assignment, limit=limit,
        )
        reconciliation = recovery.reconcile_stale_jobs(
            db, org=str(owner.organization_id), owner=str(owner.user_id),
        )
        cleanup = recovery.cleanup_debt_summary(
            db, org=str(owner.organization_id), owner=str(owner.user_id),
        )
        return {**result, "reconciled": reconciliation, "cleanup_debt": cleanup}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Staging-only Nova recovery worker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Run exactly one bounded pass")
    mode.add_argument("--loop", action="store_true", help="Run bounded passes repeatedly")
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    if not 10 <= args.poll_seconds <= 3600:
        parser.error("--poll-seconds must be between 10 and 3600")
    logging.basicConfig(level=logging.INFO)
    engine = None
    try:
        url, owner_email = _stage_only_config()
        engine = sa.create_engine(url, pool_pre_ping=True)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        while True:
            # A worker disabled between passes must stop before new work.
            active_url, active_owner = _stage_only_config()
            if active_url != url or active_owner != owner_email:
                raise CustomerCSVBlocked("Recovery worker configuration changed; restart required", 503)
            outcome = run_once(sessions, owner_email=owner_email)
            LOG.info(
                "Recovery staging pass: attempted=%s reviewed=%s failed=%s skipped=%s cleanup_debt=%s",
                outcome["attempted"], len(outcome["awaiting_review"]),
                len(outcome["failed_attempts"]), len(outcome["skipped_claims"]),
                outcome["cleanup_debt"]["unresolved_cleanup_failures"],
            )
            if args.once:
                return 0
            time.sleep(args.poll_seconds)
    except CustomerCSVBlocked as exc:
        LOG.error("Staging recovery worker blocked: %s", exc)
        return 2
    except Exception:
        LOG.exception("Staging worker failed closed")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
