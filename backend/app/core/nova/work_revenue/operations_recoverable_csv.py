"""Recoverable owner-scoped CSV jobs. Default-off staging foundation.

A job is QUEUED only after its input is persisted privately. Each processing
attempt receives a lease token, and only the live token may commit its output.
The caller must recheck current engagement/task authorization before enqueue
and before invoking process_job. This module never sends files to customers.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from io import BytesIO

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .operations_csv_cleanup import clean_csv_text
from .operations_customer_csv_jobs import CustomerCSVBlocked, _store

metadata = sa.MetaData()
recovery_jobs = sa.Table(
    "nova_operations_csv_recovery_jobs", metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("organization_id", sa.String(36), nullable=False),
    sa.Column("owner_user_id", sa.String(36), nullable=False),
    sa.Column("engagement_id", sa.String(32), nullable=False),
    sa.Column("task_id", sa.String(32), nullable=False),
    sa.Column("request_key", sa.String(120), nullable=False),
    sa.Column("input_ref", sa.String(512)),
    sa.Column("input_sha256", sa.String(64), nullable=False),
    sa.Column("output_ref", sa.String(512)),
    sa.Column("output_sha256", sa.String(64)),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
    sa.Column("lease_token", sa.String(64)),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_error_code", sa.String(64)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("organization_id", "owner_user_id", "request_key",
                        name="uq_nova_csv_recovery_request"),
)
cleanup_events = sa.Table(
    "nova_operations_csv_cleanup_events", metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("organization_id", sa.String(36), nullable=False),
    sa.Column("owner_user_id", sa.String(36), nullable=False),
    sa.Column("job_id", sa.String(36), nullable=False),
    sa.Column("storage_ref", sa.String(512), nullable=False),
    sa.Column("failure_code", sa.String(40), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("resolved_at", sa.DateTime(timezone=True)),
)

_ALLOWED_STATUSES = {
    "UPLOADING", "QUEUED", "RUNNING", "AWAITING_REVIEW",
    "APPROVED_FOR_DOWNLOAD", "REJECTED", "FAILED",
}


def _now():
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    """Treat UTC database timestamps consistently across DB drivers and fixtures."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def require_runtime(db: Session) -> None:
    if os.getenv("NOVA_OPERATIONS_RECOVERABLE_CSV_ENABLED", "").lower() != "true":
        raise CustomerCSVBlocked("Recoverable CSV jobs are disabled", 503)
    environments = {os.getenv(name, "").strip().lower() for name in
                    ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV") if os.getenv(name)}
    if environments != {"staging"}:
        raise CustomerCSVBlocked("Recoverable CSV preview is staging-only", 503)
    if db.get_bind().dialect.name != "postgresql":
        raise CustomerCSVBlocked("Isolated PostgreSQL required", 503)
    inspector = sa.inspect(db.get_bind())
    if not inspector.has_table(recovery_jobs.name) or not inspector.has_table(cleanup_events.name):
        raise CustomerCSVBlocked("Recoverable CSV and cleanup audit schema unavailable", 503)
    if os.getenv("PLATFORM_OPS_DOCUMENT_STORAGE", "").lower() != "s3_private":
        raise CustomerCSVBlocked("Private object storage required", 503)


def record_cleanup_failure(
    db: Session, *, org: str, owner: str, job_id: str,
    storage_ref: str, failure_code: str,
) -> None:
    """Durably record cleanup debt without disclosing private object paths."""
    if failure_code not in {"INPUT_DELETE_FAILED", "OUTPUT_DELETE_FAILED"}:
        raise CustomerCSVBlocked("Invalid storage cleanup event", 400)
    db.execute(sa.insert(cleanup_events).values(
        id=secrets.token_hex(16), organization_id=org, owner_user_id=owner,
        job_id=job_id, storage_ref=storage_ref, failure_code=failure_code,
        created_at=_now(),
    ))
    db.commit()


def cleanup_debt_summary(db: Session, *, org: str, owner: str) -> dict:
    """Return only tenant-scoped counts, never the private object references."""
    require_runtime(db)
    count = db.execute(sa.select(sa.func.count()).select_from(cleanup_events).where(
        cleanup_events.c.organization_id == org,
        cleanup_events.c.owner_user_id == owner,
        cleanup_events.c.resolved_at.is_(None),
    )).scalar_one()
    return {"unresolved_cleanup_failures": count, "delivered": False}


def _owned(db: Session, *, org: str, owner: str, job_id: str):
    row = db.execute(sa.select(recovery_jobs).where(
        recovery_jobs.c.id == job_id,
        recovery_jobs.c.organization_id == org,
        recovery_jobs.c.owner_user_id == owner,
    )).mappings().first()
    if row is None:
        raise CustomerCSVBlocked("Recoverable CSV job not found", 404)
    return row


def summary(row):
    return {
        "job_id": row["id"], "status": row["status"],
        "engagement_id": row["engagement_id"],
        "task_id": row["task_id"],
        "attempts": row["attempts"],
        "updated_at": row["updated_at"].isoformat(),
        "delivered": False,
    }


def enqueue(db: Session, *, org: str, owner: str, engagement_id: str,
            task_id: str, request_key: str, raw: bytes) -> dict:
    require_runtime(db)
    if (not request_key or len(request_key) > 120 or not request_key.isascii()
            or any(ord(c) < 33 or ord(c) > 126 for c in request_key)):
        raise CustomerCSVBlocked("Valid Idempotency-Key required", 400)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 1_000_000:
        raise CustomerCSVBlocked("CSV must be 1 to 1000000 bytes", 413)
    # Reject structurally invalid content before reserving/storing input.
    text = raw.decode("utf-8-sig", errors="strict")
    clean_csv_text(text, max_bytes=1_000_000, max_rows=10_000)
    fingerprint = hashlib.sha256(raw).hexdigest()
    stamp, job_id = _now(), secrets.token_hex(16)
    try:
        db.execute(sa.insert(recovery_jobs).values(
            id=job_id, organization_id=org, owner_user_id=owner,
            engagement_id=engagement_id, task_id=task_id,
            request_key=request_key, input_sha256=fingerprint,
            status="UPLOADING", attempts=0, max_attempts=3,
            available_at=stamp, created_at=stamp, updated_at=stamp,
        ))
        db.commit()
    except sa.exc.IntegrityError:
        db.rollback()
        row = db.execute(sa.select(recovery_jobs).where(
            recovery_jobs.c.organization_id == org,
            recovery_jobs.c.owner_user_id == owner,
            recovery_jobs.c.request_key == request_key,
        )).mappings().first()
        if row is None:
            raise CustomerCSVBlocked("Request collision", 409)
        if (row["input_sha256"], row["engagement_id"], row["task_id"]) != (
                fingerprint, engagement_id, task_id):
            raise CustomerCSVBlocked("Idempotency-Key reused for different work", 409)
        return {**summary(row), "replayed": True}
    storage_ref = None
    try:
        storage = _store()
        _, storage_ref, length = storage.store(
            organization_id=org, application_id=job_id,
            category="nova-csv-input", filename="source.bin",
            content_type="application/octet-stream", stream=BytesIO(raw),
        )
        if length != len(raw):
            raise CustomerCSVBlocked("Private input size mismatch", 503)
        updated = db.execute(sa.update(recovery_jobs).where(
            recovery_jobs.c.id == job_id,
            recovery_jobs.c.organization_id == org,
            recovery_jobs.c.owner_user_id == owner,
            recovery_jobs.c.status == "UPLOADING",
        ).values(input_ref=storage_ref, status="QUEUED", updated_at=_now()))
        if updated.rowcount != 1:
            raise CustomerCSVBlocked("Input reservation state changed", 409)
        db.commit()
        return {"job_id": job_id, "status": "QUEUED", "replayed": False,
                "delivered": False}
    except Exception:
        db.rollback()
        # Do not let an unpublished input become executable.
        try:
            db.execute(sa.update(recovery_jobs).where(
                recovery_jobs.c.id == job_id,
                recovery_jobs.c.status == "UPLOADING",
            ).values(status="FAILED", last_error_code="INPUT_UPLOAD_FAILED",
                     updated_at=_now()))
            db.commit()
        except Exception:
            db.rollback()
        # Object cleanup failure must be observable by storage audit/reconciler.
        if storage_ref:
            try:
                _store().delete(storage_ref=storage_ref)
            except Exception:
                db.rollback()
                record_cleanup_failure(
                    db, org=org, owner=owner, job_id=job_id,
                    storage_ref=storage_ref, failure_code="INPUT_DELETE_FAILED",
                )
        raise


def claim(db: Session, *, org: str, owner: str, job_id: str,
          now: datetime | None = None, lease_seconds: int = 300):
    require_runtime(db)
    if not 30 <= lease_seconds <= 3600:
        raise CustomerCSVBlocked("Invalid worker lease duration", 400)
    stamp = now or _now()
    row = db.execute(
        sa.select(recovery_jobs).where(
            recovery_jobs.c.id == job_id,
            recovery_jobs.c.organization_id == org,
            recovery_jobs.c.owner_user_id == owner,
        ).with_for_update(skip_locked=True)
    ).mappings().first()
    if row is None:
        db.rollback()
        raise CustomerCSVBlocked("Job not found or locked", 409)
    ready = (
        (row["status"] == "QUEUED" and _aware(row["available_at"]) <= stamp)
        or (row["status"] == "RUNNING" and row["lease_until"] is not None
            and _aware(row["lease_until"]) <= stamp)
    )
    if not ready or row["attempts"] >= row["max_attempts"] or not row["input_ref"]:
        db.rollback()
        raise CustomerCSVBlocked("Job not eligible for claim", 409)
    token = secrets.token_hex(24)
    db.execute(sa.update(recovery_jobs).where(recovery_jobs.c.id == job_id).values(
        status="RUNNING", lease_token=token,
        lease_until=stamp + timedelta(seconds=lease_seconds),
        attempts=row["attempts"] + 1, last_error_code=None, updated_at=stamp,
    ))
    db.commit()
    return {"job_id": job_id, "token": token, "input_ref": row["input_ref"],
            "input_sha256": row["input_sha256"], "attempts": row["attempts"] + 1}



def renew_lease(
    db: Session, *, org: str, owner: str, job_id: str, token: str,
    lease_seconds: int = 300, now: datetime | None = None,
) -> datetime:
    """Extend only a currently live, matching worker lease.

    An expired or superseded worker cannot revive its claim. In a live
    worker, renewal should occur before slow external storage operations;
    long-running tasks will eventually need a dedicated heartbeat thread.
    """
    require_runtime(db)
    if type(lease_seconds) is not int or not 30 <= lease_seconds <= 3600:
        raise CustomerCSVBlocked("Invalid worker lease duration", 400)
    if not token:
        raise CustomerCSVBlocked("Worker lease token required", 403)
    stamp = now or _now()
    new_expiry = stamp + timedelta(seconds=lease_seconds)
    updated = db.execute(sa.update(recovery_jobs).where(
        recovery_jobs.c.id == job_id,
        recovery_jobs.c.organization_id == org,
        recovery_jobs.c.owner_user_id == owner,
        recovery_jobs.c.status == "RUNNING",
        recovery_jobs.c.lease_token == token,
        recovery_jobs.c.lease_until > stamp,
    ).values(lease_until=new_expiry, updated_at=stamp))
    if updated.rowcount != 1:
        db.rollback()
        raise CustomerCSVBlocked("Cannot renew expired or superseded lease", 409)
    db.commit()
    return new_expiry



def complete(db: Session, *, org: str, owner: str, job_id: str,
             token: str, output_ref: str, output_sha256: str,
             now: datetime | None = None) -> None:
    """Only the current unexpired worker lease can publish its output."""
    stamp = now or _now()
    updated = db.execute(sa.update(recovery_jobs).where(
        recovery_jobs.c.id == job_id,
        recovery_jobs.c.organization_id == org,
        recovery_jobs.c.owner_user_id == owner,
        recovery_jobs.c.status == "RUNNING",
        recovery_jobs.c.lease_token == token,
        recovery_jobs.c.lease_until > stamp,
    ).values(status="AWAITING_REVIEW", output_ref=output_ref,
             output_sha256=output_sha256, lease_token=None,
             lease_until=None, updated_at=stamp))
    if updated.rowcount != 1:
        db.rollback()
        raise CustomerCSVBlocked("Stale worker cannot publish output", 409)
    db.commit()


def fail_claim(db: Session, *, org: str, owner: str, job_id: str,
               token: str, error_code: str, now: datetime | None = None) -> None:
    stamp = now or _now()
    row = _owned(db, org=org, owner=owner, job_id=job_id)
    if row["status"] != "RUNNING" or row["lease_token"] != token or (
            row["lease_until"] is None or _aware(row["lease_until"]) <= stamp):
        db.rollback()
        return
    terminal = row["attempts"] >= row["max_attempts"]
    db.execute(sa.update(recovery_jobs).where(
        recovery_jobs.c.id == job_id, recovery_jobs.c.status == "RUNNING",
        recovery_jobs.c.lease_token == token,
    ).values(status="FAILED" if terminal else "QUEUED",
             available_at=stamp + timedelta(seconds=30),
             lease_token=None, lease_until=None, updated_at=stamp,
             last_error_code=error_code[:64]))
    db.commit()


def process_job(db: Session, *, org: str, owner: str, job_id: str,
                authorization_check, now: datetime | None = None) -> dict:
    """Process one claimed job. Callers MUST pass a fresh scope verifier.

    Safe for synchronous staging exercises. A separately authorized worker
    service may call this function later; none is provisioned here.
    """
    if not callable(authorization_check):
        raise CustomerCSVBlocked("Fresh assignment authorization required", 403)
    row = _owned(db, org=org, owner=owner, job_id=job_id)
    authorization_check(row["engagement_id"], row["task_id"])
    work = claim(db, org=org, owner=owner, job_id=job_id, now=now)
    output_ref = None
    try:
        contents, _ = _store().retrieve(storage_ref=work["input_ref"])
        if len(contents) > 1_000_000 or hashlib.sha256(contents).hexdigest() != work["input_sha256"]:
            raise CustomerCSVBlocked("Private input integrity check failed", 503)
        cleaned = clean_csv_text(contents.decode("utf-8-sig", errors="strict"),
                                 max_bytes=1_000_000, max_rows=10_000)
        output = cleaned.cleaned_csv.encode("utf-8")
        # Renew before writing the output, so slow input retrieval or
        # transformation does not allow an expired worker to publish.
        renew_lease(
            db, org=org, owner=owner, job_id=job_id,
            token=work["token"], now=now,
        )
        _, output_ref, size = _store().store(
            organization_id=org, application_id=job_id,
            category="nova-csv-review", filename="cleaned.bin",
            content_type="text/csv", stream=BytesIO(output),
        )
        if size != len(output):
            raise CustomerCSVBlocked("Output size mismatch", 503)
        # Recheck scope and claim after upload: another worker could have
        # reclaimed the job while private storage was writing.
        authorization_check(row["engagement_id"], row["task_id"])
        renew_lease(
            db, org=org, owner=owner, job_id=job_id,
            token=work["token"], now=now,
        )
        complete(db, org=org, owner=owner, job_id=job_id,
                 token=work["token"], output_ref=output_ref,
                 output_sha256=hashlib.sha256(output).hexdigest(), now=now)
        return {"job_id": job_id, "status": "AWAITING_REVIEW", "delivered": False}
    except Exception:
        db.rollback()
        fail_claim(db, org=org, owner=owner, job_id=job_id,
                   token=work["token"], error_code="WORKER_ATTEMPT_FAILED", now=now)
        if output_ref:
            try:
                # Only delete this attempt's unique output, not another worker's.
                _store().delete(storage_ref=output_ref)
            except Exception:
                db.rollback()
                record_cleanup_failure(
                    db, org=org, owner=owner, job_id=job_id,
                    storage_ref=output_ref, failure_code="OUTPUT_DELETE_FAILED",
                )
        raise



def reconcile_stale_jobs(db: Session, *, org: str, owner: str,
                         now: datetime | None = None) -> dict:
    """Fail abandoned uploads and exhausted leases; never delete artifacts.

    Records remain available for authorized owner inspection and later
    audited cleanup. Requires an authorized scheduler/owner call.
    """
    require_runtime(db)
    stamp = now or _now()
    upload_cutoff = stamp - timedelta(minutes=15)
    abandoned = db.execute(sa.update(recovery_jobs).where(
        recovery_jobs.c.organization_id == org,
        recovery_jobs.c.owner_user_id == owner,
        recovery_jobs.c.status == "UPLOADING",
        recovery_jobs.c.created_at < upload_cutoff,
    ).values(status="FAILED", last_error_code="ABANDONED_UPLOAD",
             updated_at=stamp))
    expired = db.execute(sa.update(recovery_jobs).where(
        recovery_jobs.c.organization_id == org,
        recovery_jobs.c.owner_user_id == owner,
        recovery_jobs.c.status == "RUNNING",
        recovery_jobs.c.lease_until <= stamp,
        recovery_jobs.c.attempts >= recovery_jobs.c.max_attempts,
    ).values(status="FAILED", lease_token=None, lease_until=None,
             last_error_code="MAX_ATTEMPTS_EXHAUSTED", updated_at=stamp))
    db.commit()
    return {"abandoned_uploads": abandoned.rowcount,
            "exhausted_jobs": expired.rowcount, "delivered": False}



def due_job_ids(
    db: Session, *, org: str, owner: str, now: datetime | None = None,
    limit: int = 10,
) -> list[str]:
    """Bounded worker-discovery query; never returns input or output objects.

    Scans only a single preauthorized owner and organization, and never
    claims work itself. The eventual worker must recheck saved-task authority
    before calling process_job (which checks it again).
    """
    require_runtime(db)
    if not org or not owner or org.lower() == "global":
        raise CustomerCSVBlocked("Specific worker owner scope required", 403)
    if type(limit) is not int or not 1 <= limit <= 25:
        raise CustomerCSVBlocked("Worker batch limit must be 1 to 25", 400)
    stamp = now or _now()
    rows = db.execute(sa.select(recovery_jobs.c.id).where(
        recovery_jobs.c.organization_id == org,
        recovery_jobs.c.owner_user_id == owner,
        recovery_jobs.c.input_ref.is_not(None),
        recovery_jobs.c.attempts < recovery_jobs.c.max_attempts,
        sa.or_(
            sa.and_(
                recovery_jobs.c.status == "QUEUED",
                recovery_jobs.c.available_at <= stamp,
            ),
            sa.and_(
                recovery_jobs.c.status == "RUNNING",
                recovery_jobs.c.lease_until.is_not(None),
                recovery_jobs.c.lease_until <= stamp,
            ),
        ),
    ).order_by(
        recovery_jobs.c.available_at.asc(),
        recovery_jobs.c.created_at.asc(),
        recovery_jobs.c.id.asc(),
    ).limit(limit)).scalars().all()
    return list(rows)


def run_due_jobs(
    db: Session, *, org: str, owner: str, authorization_check,
    now: datetime | None = None, limit: int = 10,
) -> dict:
    """One bounded staging worker pass; no delivery or billing.

    Each job has a fresh scope check inside process_job. A lost lease is
    skipped by this pass and can be picked up in a later pass; no queued
    work is silently represented as completed.
    """
    if not callable(authorization_check):
        raise CustomerCSVBlocked("Fresh job authorization required", 403)
    pending = due_job_ids(db, org=org, owner=owner, now=now, limit=limit)
    completed = []
    failed = []
    skipped = []
    for job_id in pending:
        try:
            result = process_job(
                db, org=org, owner=owner, job_id=job_id,
                authorization_check=authorization_check, now=now,
            )
            completed.append(result["job_id"])
        except CustomerCSVBlocked as exc:
            db.rollback()
            if exc.code == 409 and "eligible for claim" in str(exc):
                skipped.append(job_id)
            else:
                failed.append(job_id)
        except Exception:
            db.rollback()
            failed.append(job_id)
    return {
        "attempted": len(pending), "awaiting_review": completed,
        "failed_attempts": failed, "skipped_claims": skipped,
        "delivered": False,
    }


def status(db: Session, *, org: str, owner: str, job_id: str) -> dict:
    require_runtime(db)
    return summary(_owned(db, org=org, owner=owner, job_id=job_id))



def decide_review(db: Session, *, org: str, owner: str, job_id: str,
                  approve: bool) -> dict:
    """Explicit owner decision, never an external delivery action."""
    require_runtime(db)
    if type(approve) is not bool:
        raise CustomerCSVBlocked("Boolean review decision required", 400)
    desired = "APPROVED_FOR_DOWNLOAD" if approve else "REJECTED"
    updated = db.execute(sa.update(recovery_jobs).where(
        recovery_jobs.c.id == job_id,
        recovery_jobs.c.organization_id == org,
        recovery_jobs.c.owner_user_id == owner,
        recovery_jobs.c.status == "AWAITING_REVIEW",
        recovery_jobs.c.output_ref.is_not(None),
        recovery_jobs.c.output_sha256.is_not(None),
    ).values(status=desired, updated_at=_now()))
    if updated.rowcount != 1:
        db.rollback()
        raise CustomerCSVBlocked("Job is not awaiting review", 409)
    db.commit()
    return {"job_id": job_id, "status": desired, "delivered": False}




def list_owned(db: Session, *, org: str, owner: str, limit: int = 50) -> list[dict]:
    """Summaries only; private input/output object keys never leave storage."""
    require_runtime(db)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise CustomerCSVBlocked("Job history limit must be 1 to 50", 400)
    rows = db.execute(sa.select(recovery_jobs).where(
        recovery_jobs.c.organization_id == org,
        recovery_jobs.c.owner_user_id == owner,
    ).order_by(recovery_jobs.c.created_at.desc(),
               recovery_jobs.c.id.desc()).limit(limit)).mappings().all()
    return [summary(row) for row in rows]



def review_download(db: Session, *, org: str, owner: str, job_id: str) -> bytes:
    require_runtime(db)
    row = _owned(db, org=org, owner=owner, job_id=job_id)
    if row["status"] not in {"AWAITING_REVIEW", "APPROVED_FOR_DOWNLOAD"}:
        raise CustomerCSVBlocked("Output unavailable for review", 409)
    if not row["output_ref"] or not row["output_sha256"]:
        raise CustomerCSVBlocked("Missing approved review artifact", 503)
    content, _ = _store().retrieve(storage_ref=row["output_ref"])
    if len(content) > 1_000_000 or hashlib.sha256(content).hexdigest() != row["output_sha256"]:
        raise CustomerCSVBlocked("Review output checksum mismatch", 503)
    return content
