"""Default-off PostgreSQL job lease primitives for Nova Operations.

This is a development-only queue substrate. It does not start a worker, accept
customer files, read private storage, authorize contract scope, or deploy schema.
A separately approved additive migration and worker integration are required.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

lease_metadata = sa.MetaData()
lease_jobs = sa.Table(
    "nova_operations_processing_leases", lease_metadata,
    sa.Column("job_id", sa.String(36), primary_key=True),
    sa.Column("organization_id", sa.String(36), nullable=False),
    sa.Column("owner_user_id", sa.String(36), nullable=False),
    sa.Column("input_sha256", sa.String(64), nullable=False),
    sa.Column("state", sa.String(20), nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
    sa.Column("lease_token", sa.String(64)),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("output_sha256", sa.String(64)),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("state IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
                       name="ck_nova_operations_lease_state"),
    sa.CheckConstraint("attempts >= 0 AND max_attempts BETWEEN 1 AND 10",
                       name="ck_nova_operations_lease_attempts"),
)
sa.Index("ix_nova_operations_lease_ready", lease_jobs.c.state,
         lease_jobs.c.available_at, lease_jobs.c.lease_until)


class LeaseBlocked(ValueError):
    pass


@dataclass(frozen=True)
class LeaseClaim:
    job_id: str
    organization_id: str
    owner_user_id: str
    input_sha256: str
    token: str
    attempts: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )


def _guard(db: Session) -> None:
    if os.getenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "").lower() != "true":
        raise LeaseBlocked("Operations lease worker disabled")
    if db.get_bind().dialect.name != "postgresql":
        raise LeaseBlocked("Isolated PostgreSQL required")
    if not sa.inspect(db.get_bind()).has_table(lease_jobs.name):
        raise LeaseBlocked("Reviewed lease migration required")


def enqueue(db: Session, *, job_id: str, organization_id: str,
            owner_user_id: str, input_sha256: str, now: datetime | None = None) -> None:
    """Queue exactly one authorized job identity; caller verifies engagement/scope."""
    _guard(db)
    if not all(isinstance(v, str) and v.strip() and len(v) <= 36
               for v in (job_id, organization_id, owner_user_id)) or not _sha(input_sha256):
        raise LeaseBlocked("Invalid job identity or fingerprint")
    now = now or _now()
    try:
        row = db.execute(sa.select(lease_jobs).where(
            lease_jobs.c.job_id == job_id).with_for_update()).mappings().first()
        if row:
            if (row["organization_id"], row["owner_user_id"], row["input_sha256"]) != (
                organization_id, owner_user_id, input_sha256
            ):
                raise LeaseBlocked("Job identity reused with different scope or input")
            db.rollback()
            return
        db.execute(sa.insert(lease_jobs).values(
            job_id=job_id, organization_id=organization_id,
            owner_user_id=owner_user_id, input_sha256=input_sha256,
            state="QUEUED", attempts=0, max_attempts=3,
            available_at=now, updated_at=now))
        db.commit()
    except Exception:
        db.rollback()
        raise


def claim(db: Session, *, now: datetime | None = None,
          lease_seconds: int = 60) -> LeaseClaim | None:
    """Claim at most one ready job with PostgreSQL row locking and fencing."""
    _guard(db)
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
        raise LeaseBlocked("Invalid lease duration")
    now = now or _now()
    ready = sa.or_(
        sa.and_(lease_jobs.c.state == "QUEUED", lease_jobs.c.available_at <= now),
        sa.and_(lease_jobs.c.state == "RUNNING", lease_jobs.c.lease_until <= now),
    )
    try:
        row = db.execute(sa.select(lease_jobs).where(
            ready, lease_jobs.c.attempts < lease_jobs.c.max_attempts
        ).order_by(lease_jobs.c.available_at, lease_jobs.c.job_id)
         .with_for_update(skip_locked=True).limit(1)).mappings().first()
        if row is None:
            db.rollback()
            return None
        token = secrets.token_hex(24)
        changed = db.execute(sa.update(lease_jobs).where(
            lease_jobs.c.job_id == row["job_id"], ready,
            lease_jobs.c.attempts < lease_jobs.c.max_attempts
        ).values(state="RUNNING", attempts=row["attempts"] + 1,
                 lease_token=token, lease_until=now + timedelta(seconds=lease_seconds),
                 updated_at=now))
        if changed.rowcount != 1:
            raise LeaseBlocked("Claim changed during transaction")
        db.commit()
        return LeaseClaim(row["job_id"], row["organization_id"],
                          row["owner_user_id"], row["input_sha256"],
                          token, row["attempts"] + 1)
    except Exception:
        db.rollback()
        raise


def complete(db: Session, *, claimed: LeaseClaim, output_sha256: str,
             now: datetime | None = None) -> None:
    """Reject expired or superseded worker completions."""
    _guard(db)
    if not _sha(output_sha256):
        raise LeaseBlocked("Invalid output fingerprint")
    now = now or _now()
    try:
        changed = db.execute(sa.update(lease_jobs).where(
            lease_jobs.c.job_id == claimed.job_id,
            lease_jobs.c.organization_id == claimed.organization_id,
            lease_jobs.c.owner_user_id == claimed.owner_user_id,
            lease_jobs.c.state == "RUNNING",
            lease_jobs.c.lease_token == claimed.token,
            lease_jobs.c.lease_until > now,
        ).values(state="COMPLETED", output_sha256=output_sha256,
                 lease_token=None, lease_until=None, updated_at=now))
        if changed.rowcount != 1:
            raise LeaseBlocked("Stale or expired completion")
        db.commit()
    except Exception:
        db.rollback()
        raise


def fail_or_retry(db: Session, *, claimed: LeaseClaim, now: datetime | None = None,
                  retry_delay_seconds: int = 30) -> str:
    """Retry bounded failures; stale workers cannot requeue a newer claim."""
    _guard(db)
    if type(retry_delay_seconds) is not int or not 0 <= retry_delay_seconds <= 3600:
        raise LeaseBlocked("Invalid retry delay")
    now = now or _now()
    try:
        row = db.execute(sa.select(lease_jobs).where(
            lease_jobs.c.job_id == claimed.job_id,
            lease_jobs.c.organization_id == claimed.organization_id,
            lease_jobs.c.owner_user_id == claimed.owner_user_id,
        ).with_for_update()).mappings().first()
        if not row or row["state"] != "RUNNING" or row["lease_token"] != claimed.token:
            raise LeaseBlocked("Stale worker failure")
        state = "FAILED" if row["attempts"] >= row["max_attempts"] else "QUEUED"
        db.execute(sa.update(lease_jobs).where(
            lease_jobs.c.job_id == claimed.job_id,
            lease_jobs.c.lease_token == claimed.token,
        ).values(state=state, lease_token=None, lease_until=None,
                 available_at=now + timedelta(seconds=retry_delay_seconds),
                 updated_at=now))
        db.commit()
        return state
    except Exception:
        db.rollback()
        raise


def renew(db: Session, *, claimed: LeaseClaim, now: datetime | None = None,
          lease_seconds: int = 60) -> None:
    """Extend only the active, unexpired lease held by this exact worker."""
    _guard(db)
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
        raise LeaseBlocked("Invalid lease duration")
    now = now or _now()
    try:
        changed = db.execute(sa.update(lease_jobs).where(
            lease_jobs.c.job_id == claimed.job_id,
            lease_jobs.c.organization_id == claimed.organization_id,
            lease_jobs.c.owner_user_id == claimed.owner_user_id,
            lease_jobs.c.state == "RUNNING",
            lease_jobs.c.lease_token == claimed.token,
            lease_jobs.c.lease_until > now,
        ).values(lease_until=now + timedelta(seconds=lease_seconds),
                 updated_at=now))
        if changed.rowcount != 1:
            raise LeaseBlocked("Stale or expired lease renewal")
        db.commit()
    except Exception:
        db.rollback()
        raise


def exhaust_expired(db: Session, *, now: datetime | None = None) -> int:
    """Terminally fail expired workers that have no attempts remaining.

    Does not touch incomplete input/output objects; eventual artifact cleanup
    and audit reconciliation remain separate required release work.
    """
    _guard(db)
    now = now or _now()
    try:
        changed = db.execute(sa.update(lease_jobs).where(
            lease_jobs.c.state == "RUNNING",
            lease_jobs.c.lease_until <= now,
            lease_jobs.c.attempts >= lease_jobs.c.max_attempts,
        ).values(state="FAILED", lease_token=None, lease_until=None,
                 updated_at=now))
        db.commit()
        return changed.rowcount
    except Exception:
        db.rollback()
        raise
