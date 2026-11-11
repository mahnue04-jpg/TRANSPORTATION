"""Default-off bookkeeping review job persistence on PR #477's private job substrate.

No HTTP route is registered here. Only a server-side authenticated owner
adapter may call these methods after verifying the saved engagement, active
task, client AI-use permission and the exact structured contract scope.
This is not a worker, financial ledger, reconciliation or external delivery.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from io import BytesIO

import sqlalchemy as sa
from sqlalchemy.orm import Session

from . import operations_customer_csv_jobs as base
from .bookkeeping_assignment import (
    AssignmentNotAuthorized, BookkeepingAssignment, prepare_assignment_draft,
)

JOB_PREFIX = "bookkeeping:"
BOOKKEEPING_TYPES = frozenset({"transaction_workpaper", "receivables_aging", "payables_aging"})


class BookkeepingJobBlocked(base.CustomerCSVBlocked):
    pass


def require_bookkeeping_runtime(db: Session) -> None:
    if os.getenv("NOVA_BOOKKEEPING_DURABLE_ENABLED", "").lower() != "true":
        raise BookkeepingJobBlocked("Bookkeeping job feature disabled", 503)
    base.require_runtime(db)


def _row(db: Session, *, org: str, owner: str, job_id: str, lock: bool = False):
    row = base._owned(db, job_id, org, owner, lock=lock)
    # Never permit accounting endpoints to operate on legacy CSV-cleanup jobs.
    if not str(row["request_key"]).startswith(JOB_PREFIX):
        raise BookkeepingJobBlocked("Bookkeeping job not found", 404)
    return row


def _fingerprint(assignment: BookkeepingAssignment, raw: bytes,
                 secondary: bytes | None, as_of: str | None) -> str:
    manifest = {
        "organization_id": assignment.organization_id,
        "owner_user_id": assignment.owner_user_id,
        "engagement_id": assignment.engagement_id,
        "task_id": assignment.task_id,
        "work_type": assignment.work_type,
        "as_of": as_of,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "secondary_sha256": (hashlib.sha256(secondary).hexdigest()
                             if secondary is not None else None),
    }
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def submit_bookkeeping_review(
    db: Session, *, assignment: BookkeepingAssignment,
    request_id: str, primary: bytes, secondary: bytes | None = None,
    as_of: str | None = None,
) -> dict:
    """Persist private review CSV under an idempotent, tenant/assignment-bound job.

    Server must load assignment from trusted authenticated contract records,
    never directly from user JSON or caller-provided permission booleans.
    Input bytes are not persisted here; interrupted requests cannot auto-retry.
    """
    require_bookkeeping_runtime(db)
    # The exact version of this gate is intentionally independent of task labels.
    if not isinstance(assignment, BookkeepingAssignment):
        raise BookkeepingJobBlocked("Trusted structured assignment required", 403)
    if assignment.work_type not in BOOKKEEPING_TYPES:
        raise BookkeepingJobBlocked("Unsupported bookkeeping type", 400)
    if not request_id or len(request_id) > 70 or not request_id.isascii() or any(
        ord(c) < 33 or ord(c) > 126 or c == ":" for c in request_id
    ):
        raise BookkeepingJobBlocked("Valid request ID required", 400)
    if (not isinstance(primary, bytes) or not 0 < len(primary) <= 1_000_000
        or (secondary is not None and (not isinstance(secondary, bytes)
                                        or not 0 < len(secondary) <= 1_000_000))):
        raise BookkeepingJobBlocked("Valid bounded CSV bytes required", 413)
    try:
        # Validate source and contract *before* any database write.
        draft = prepare_assignment_draft(
            assignment, primary_csv=primary.decode("utf-8-sig", "strict"),
            secondary_csv=secondary.decode("utf-8-sig", "strict")
            if secondary is not None else None, as_of=as_of,
        )
    except (AssignmentNotAuthorized, ValueError, UnicodeError) as exc:
        raise BookkeepingJobBlocked("Bookkeeping request failed authorization or validation", 400) from exc
    output = draft["draft"]["workpaper_csv"].encode("utf-8")
    if len(output) > 1_000_000:
        raise BookkeepingJobBlocked("Bookkeeping review artifact exceeds 1 MB", 413)
    fingerprint = _fingerprint(assignment, primary, secondary, as_of)
    key = JOB_PREFIX + request_id
    now = base._utc()
    job_id = secrets.token_hex(16)
    try:
        db.execute(sa.insert(base.jobs).values(
            id=job_id, organization_id=assignment.organization_id,
            owner_user_id=assignment.owner_user_id,
            engagement_id=assignment.engagement_id, task_id=assignment.task_id,
            request_key=key, input_sha256=fingerprint,
            status="PROCESSING", created_at=now, updated_at=now,
        ))
        db.commit()
    except sa.exc.IntegrityError:
        db.rollback()
        old = db.execute(sa.select(base.jobs).where(
            base.jobs.c.organization_id == assignment.organization_id,
            base.jobs.c.owner_user_id == assignment.owner_user_id,
            base.jobs.c.request_key == key,
        )).mappings().first()
        if old is None:
            raise BookkeepingJobBlocked("Request collision", 409)
        if (old["input_sha256"], old["engagement_id"], old["task_id"]) != (
            fingerprint, assignment.engagement_id, assignment.task_id
        ):
            raise BookkeepingJobBlocked("Request ID already belongs to different work", 409)
        return {"job_id": old["id"], "status": old["status"],
                "replayed": True, "delivered": False}

    storage_ref = None
    try:
        saved = base._store().store(
            organization_id=assignment.organization_id,
            application_id=job_id, category="nova-bookkeeping-review",
            filename="bookkeeping-review.csv", content_type="text/csv",
            stream=BytesIO(output),
        )
        storage_ref = saved[1]
        if saved[2] != len(output):
            raise BookkeepingJobBlocked("Private storage size mismatch", 503)
        digest = hashlib.sha256(output).hexdigest()
        changed = db.execute(sa.update(base.jobs).where(
            base.jobs.c.id == job_id,
            base.jobs.c.organization_id == assignment.organization_id,
            base.jobs.c.owner_user_id == assignment.owner_user_id,
            base.jobs.c.status == "PROCESSING",
        ).values(
            status="AWAITING_REVIEW", output_ref=storage_ref,
            output_sha256=digest, updated_at=base._utc(),
        ))
        if changed.rowcount != 1:
            raise BookkeepingJobBlocked("Job changed during storage", 409)
        db.commit()
        return {"job_id": job_id, "status": "AWAITING_REVIEW",
                "output_sha256": digest, "provenance": draft["provenance"],
                "replayed": False, "delivered": False}
    except Exception:
        db.rollback()
        try:
            db.execute(sa.update(base.jobs).where(
                base.jobs.c.id == job_id, base.jobs.c.status == "PROCESSING",
            ).values(status="FAILED", updated_at=base._utc()))
            db.commit()
        except Exception:
            db.rollback()
        if storage_ref is not None:
            try:
                base._store().delete(storage_ref=storage_ref)
            except Exception:
                pass  # Staging orphan reconciler is still required.
        raise


def bookkeeping_status(db: Session, *, org: str, owner: str, job_id: str) -> dict:
    require_bookkeeping_runtime(db)
    found = _row(db, org=org, owner=owner, job_id=job_id)
    return {"job_id": job_id, "status": found["status"], "delivered": False,
            "engagement_id": found["engagement_id"], "task_id": found["task_id"]}


def review_bookkeeping(db: Session, *, org: str, owner: str, job_id: str, approve: bool) -> dict:
    require_bookkeeping_runtime(db)
    if type(approve) is not bool:
        raise BookkeepingJobBlocked("Boolean decision required", 400)
    found = _row(db, org=org, owner=owner, job_id=job_id, lock=True)
    if found["status"] != "AWAITING_REVIEW":
        raise BookkeepingJobBlocked("Job is not awaiting owner review", 409)
    status = "APPROVED_FOR_DOWNLOAD" if approve else "REJECTED"
    db.execute(sa.update(base.jobs).where(
        base.jobs.c.id == job_id, base.jobs.c.organization_id == org,
        base.jobs.c.owner_user_id == owner,
        base.jobs.c.status == "AWAITING_REVIEW",
    ).values(status=status, reviewer_user_id=owner, updated_at=base._utc()))
    db.commit()
    return {"job_id": job_id, "status": status, "delivered": False}


def download_bookkeeping(db: Session, *, org: str, owner: str, job_id: str) -> bytes:
    require_bookkeeping_runtime(db)
    found = _row(db, org=org, owner=owner, job_id=job_id)
    if found["status"] not in {"AWAITING_REVIEW", "APPROVED_FOR_DOWNLOAD"}:
        raise BookkeepingJobBlocked("Artifact not available for review", 409)
    if not found["output_ref"] or not found["output_sha256"]:
        raise BookkeepingJobBlocked("Artifact metadata missing", 503)
    try:
        data, _ = base._store().retrieve(storage_ref=found["output_ref"])
    except Exception as exc:
        raise BookkeepingJobBlocked("Private artifact unavailable", 503) from exc
    if len(data) > 1_000_000 or hashlib.sha256(data).hexdigest() != found["output_sha256"]:
        raise BookkeepingJobBlocked("Artifact integrity failure", 503)
    return data
