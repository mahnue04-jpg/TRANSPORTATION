"""Durable CSV job metadata and private artifact adapter.

Production-oriented implementation, DISABLED until schema, private S3 and
end-to-end staging verification. No local disk, no SQLite CSV blob storage.
Migration must create the table explicitly; this module never creates it.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from io import BytesIO

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.modules.platform_ops.secure_storage import (
    S3PrivateDocumentStorage, SecureStorageNotConfigured,
)
from .operations_csv_cleanup import clean_csv_text

metadata = sa.MetaData()
jobs = sa.Table(
    "nova_operations_customer_csv_jobs", metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("organization_id", sa.String(36), nullable=False),
    sa.Column("owner_user_id", sa.String(36), nullable=False),
    sa.Column("engagement_id", sa.String(32), nullable=False),
    sa.Column("task_id", sa.String(32), nullable=False),
    sa.Column("request_key", sa.String(120), nullable=False),
    sa.Column("input_sha256", sa.String(64), nullable=False),
    sa.Column("output_sha256", sa.String(64)),
    sa.Column("output_ref", sa.String(512)),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("reviewer_user_id", sa.String(36)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("organization_id", "owner_user_id", "request_key",
                        name="uq_nova_customer_csv_request"),
)
SCOPE = ("organization_id", "owner_user_id")


class CustomerCSVBlocked(ValueError):
    def __init__(self, detail: str, code: int = 409):
        self.code = code
        super().__init__(detail)


def require_runtime(db: Session) -> None:
    if os.getenv("NOVA_OPERATIONS_DURABLE_CSV_ENABLED", "").lower() != "true":
        raise CustomerCSVBlocked("Durable CSV processing disabled", 503)
    # Explicit, isolated Postgres migration required. Never create customer
    # records in transient SQLite or a developer filesystem.
    if db.get_bind().dialect.name != "postgresql":
        raise CustomerCSVBlocked("Production PostgreSQL required", 503)
    if not sa.inspect(db.get_bind()).has_table(jobs.name):
        raise CustomerCSVBlocked("CSV database migration required", 503)
    if os.getenv("PLATFORM_OPS_DOCUMENT_STORAGE", "").lower() != "s3_private":
        raise CustomerCSVBlocked("Private S3 storage configuration required", 503)


def _store() -> S3PrivateDocumentStorage:
    try:
        return S3PrivateDocumentStorage()
    except SecureStorageNotConfigured as exc:
        raise CustomerCSVBlocked("Private artifact storage unavailable", 503) from exc


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def _owned(db: Session, job_id: str, org: str, owner: str, *, lock: bool = False):
    stmt = sa.select(jobs).where(
        jobs.c.id == job_id,
        jobs.c.organization_id == org,
        jobs.c.owner_user_id == owner,
    )
    if lock:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).mappings().first()
    if row is None:
        raise CustomerCSVBlocked("CSV job not found", 404)
    return row


def submit_review_job(
    db: Session, *, org: str, owner: str, engagement_id: str, task_id: str,
    request_key: str, raw: bytes,
) -> dict:
    """Synchronous bounded processing, durable metadata, review-only private output.

    The HTTP layer must check the authenticated owner and saved-task scope
    before calling this function. A request key is bound to input and scope.
    Concurrent identical requests cannot process twice.
    """
    require_runtime(db)
    if not request_key or len(request_key) > 120 or not request_key.isascii() or any(
        ord(c) < 33 or ord(c) > 126 for c in request_key
    ):
        raise CustomerCSVBlocked("Valid Idempotency-Key required", 400)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 1_000_000:
        raise CustomerCSVBlocked("CSV must be between 1 byte and 1 MB", 413)
    fingerprint = hashlib.sha256(raw).hexdigest()
    now = _utc()
    job_id = secrets.token_hex(16)
    # Reserve with DB uniqueness before paid work or object storage.
    # A failed reservation is inspected for scope/content consistency.
    try:
        db.execute(sa.insert(jobs).values(
            id=job_id, organization_id=org, owner_user_id=owner,
            engagement_id=engagement_id, task_id=task_id,
            request_key=request_key, input_sha256=fingerprint,
            status="PROCESSING", created_at=now, updated_at=now,
        ))
        db.commit()
    except sa.exc.IntegrityError:
        db.rollback()
        row = db.execute(sa.select(jobs).where(
            jobs.c.organization_id == org,
            jobs.c.owner_user_id == owner,
            jobs.c.request_key == request_key,
        )).mappings().first()
        if row is None:
            raise CustomerCSVBlocked("CSV request collision", 409)
        if (row["input_sha256"], row["engagement_id"], row["task_id"]) != (
            fingerprint, engagement_id, task_id
        ):
            raise CustomerCSVBlocked("Idempotency-Key used for different work", 409)
        return {"job_id": row["id"], "status": row["status"], "replayed": True}

    # A crashed PROCESSING job remains visible, never claims completion. A
    # recovery worker must be designed before allowing unattended acceptance.
    storage_ref = None
    try:
        text = raw.decode("utf-8-sig", errors="strict")
        result = clean_csv_text(text, max_bytes=1_000_000, max_rows=10_000)
        saved = _store().store(
            organization_id=org, application_id=job_id,
            category="nova-csv-review", filename="cleaned.csv",
            content_type="text/csv",
            stream=BytesIO(result.cleaned_csv.encode("utf-8")),
        )
        storage_ref = saved[1]
        if saved[2] != len(result.cleaned_csv.encode("utf-8")):
            raise CustomerCSVBlocked("Artifact size mismatch", 503)
        db.execute(sa.update(jobs).where(
            jobs.c.id == job_id, jobs.c.status == "PROCESSING",
        ).values(
            status="AWAITING_REVIEW", output_ref=storage_ref,
            output_sha256=result.output_sha256, updated_at=_utc(),
        ))
        db.commit()
        return {"job_id": job_id, "status": "AWAITING_REVIEW",
                "output_sha256": result.output_sha256, "replayed": False}
    except Exception:
        db.rollback()
        try:
            db.execute(sa.update(jobs).where(
                jobs.c.id == job_id, jobs.c.status == "PROCESSING",
            ).values(status="FAILED", updated_at=_utc()))
            db.commit()
        except Exception:
            db.rollback()
        # If S3 succeeded but DB failed, the unreferenced object must not
        # persist. Never delete a successfully committed referenced artifact.
        if storage_ref:
            try:
                _store().delete(storage_ref=storage_ref)
            except Exception:
                pass  # audited orphan cleanup is required before release
        raise


def job_status(db: Session, *, org: str, owner: str, job_id: str) -> dict:
    require_runtime(db)
    row = _owned(db, job_id, org, owner)
    return {"job_id": job_id, "status": row["status"],
            "engagement_id": row["engagement_id"],
            "task_id": row["task_id"],
            "output_sha256": row["output_sha256"]}


def review_job(
    db: Session, *, org: str, owner: str, job_id: str, approve: bool,
) -> dict:
    require_runtime(db)
    if type(approve) is not bool:
        raise CustomerCSVBlocked("Boolean review decision required", 400)
    row = _owned(db, job_id, org, owner, lock=True)
    if row["status"] != "AWAITING_REVIEW":
        raise CustomerCSVBlocked("Job is not awaiting owner review")
    status = "APPROVED_FOR_DOWNLOAD" if approve else "REJECTED"
    db.execute(sa.update(jobs).where(
        jobs.c.id == job_id, jobs.c.organization_id == org,
        jobs.c.owner_user_id == owner, jobs.c.status == "AWAITING_REVIEW",
    ).values(status=status, reviewer_user_id=owner, updated_at=_utc()))
    db.commit()
    return {"job_id": job_id, "status": status, "delivered": False}


def download_review(db: Session, *, org: str, owner: str, job_id: str) -> bytes:
    require_runtime(db)
    row = _owned(db, job_id, org, owner)
    if row["status"] not in {"AWAITING_REVIEW", "APPROVED_FOR_DOWNLOAD"}:
        raise CustomerCSVBlocked("Job is not available for review download")
    if not row["output_ref"] or not row["output_sha256"]:
        raise CustomerCSVBlocked("Artifact reference missing", 503)
    try:
        content, _ = _store().retrieve(storage_ref=row["output_ref"])
    except Exception as exc:
        raise CustomerCSVBlocked("Private artifact unavailable", 503) from exc
    if len(content) > 1_000_000 or hashlib.sha256(content).hexdigest() != row["output_sha256"]:
        raise CustomerCSVBlocked("Artifact integrity check failed", 503)
    return content
