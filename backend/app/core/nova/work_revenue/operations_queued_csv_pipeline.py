"""Development-only end-to-end queued customer CSV coordinator.

Explicit calls only. NOT an HTTP endpoint, scheduler, production runner, or
authorization provider. Only a separately authenticated controller may supply
an approval/engagement callback. Both runtime flags and migrated PostgreSQL
tables are mandatory. The existing synchronous CSV API remains unchanged.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from io import BytesIO

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import operations_customer_csv_jobs as csvjobs
from . import operations_postgres_leases as leases
from .operations_csv_cleanup import clean_csv_text
from .operations_private_input import (
    PrivateInputBlocked, persist_private_csv_input, load_private_csv_input,
)
from .operations_lease_worker import OutputUncertain, run_one

Authorization = Callable[[str, str, str, str], bool]


class QueuedCSVBlocked(ValueError):
    pass


def _authorized(callback: Authorization, org: str, owner: str,
                engagement: str, task: str) -> None:
    # There is no implicit authorization or permissive default.
    if not callable(callback):
        raise QueuedCSVBlocked("Independent saved-task authorization required")
    try:
        approved = callback(org, owner, engagement, task)
    except Exception as exc:
        raise QueuedCSVBlocked("Saved-task authorization unavailable") from exc
    if approved is not True:
        raise QueuedCSVBlocked("Saved task is not authorized")


def _runtime(db: Session) -> None:
    csvjobs.require_runtime(db)
    leases._guard(db)


def _load_csv_row(db: Session, org: str, owner: str, job_id: str):
    return db.execute(sa.select(csvjobs.jobs).where(
        csvjobs.jobs.c.id == job_id,
        csvjobs.jobs.c.organization_id == org,
        csvjobs.jobs.c.owner_user_id == owner,
    )).mappings().first()


def submit_queued_csv(
    session_factory: Callable[[], Session], *, organization_id: str,
    owner_user_id: str, engagement_id: str, task_id: str,
    request_key: str, raw: bytes, store, authorize: Authorization,
) -> dict:
    """Reserve an idempotent job, persist private input, then bind its lease.

    A transient failure after reserving leaves a non-claimable, observable
    PROCESSING record; never silently reupload/overwrite an uncertain object.
    A separate stale-record/orphan recovery procedure is required.
    """
    _authorized(authorize, organization_id, owner_user_id, engagement_id, task_id)
    if (not isinstance(request_key, str) or not 0 < len(request_key) <= 120
            or not request_key.isascii()
            or any(ord(c) < 33 or ord(c) > 126 for c in request_key)):
        raise QueuedCSVBlocked("Invalid idempotency key")
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 1_000_000:
        raise QueuedCSVBlocked("Input must be a bounded CSV byte string")
    fingerprint = hashlib.sha256(raw).hexdigest()
    job_id = secrets.token_hex(16)
    with session_factory() as db:
        _runtime(db)
        try:
            db.execute(sa.insert(csvjobs.jobs).values(
                id=job_id, organization_id=organization_id,
                owner_user_id=owner_user_id, engagement_id=engagement_id,
                task_id=task_id, request_key=request_key,
                input_sha256=fingerprint, status="PROCESSING",
                created_at=csvjobs._utc(), updated_at=csvjobs._utc(),
            ))
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.execute(sa.select(csvjobs.jobs).where(
                csvjobs.jobs.c.organization_id == organization_id,
                csvjobs.jobs.c.owner_user_id == owner_user_id,
                csvjobs.jobs.c.request_key == request_key,
            )).mappings().first()
            if row is None:
                raise QueuedCSVBlocked("Request collision")
            if (row["input_sha256"], row["engagement_id"], row["task_id"]) != (
                fingerprint, engagement_id, task_id
            ):
                raise QueuedCSVBlocked("Request key reused for different work")
            return {"job_id": row["id"], "status": row["status"],
                    "replayed": True, "delivered": False}

    # The reserved job is NOT visible to strict claimers until its input has
    # been privately stored, fingerprinted, and durably bound.
    _authorized(authorize, organization_id, owner_user_id, engagement_id, task_id)
    receipt = persist_private_csv_input(
        organization_id=organization_id, owner_user_id=owner_user_id,
        job_id=job_id, raw=raw, store=store,
    )
    if not hmac.compare_digest(receipt.sha256, fingerprint):
        raise QueuedCSVBlocked("Private storage returned incorrect fingerprint")
    with session_factory() as db:
        _runtime(db)
        leases.enqueue(
            db, job_id=job_id, organization_id=organization_id,
            owner_user_id=owner_user_id, input_sha256=fingerprint,
        )
        leases.bind_private_input(
            db, job_id=job_id, organization_id=organization_id,
            owner_user_id=owner_user_id, input_sha256=fingerprint,
            storage_ref=receipt.storage_ref, input_size=receipt.size,
        )
    return {"job_id": job_id, "status": "QUEUED",
            "replayed": False, "delivered": False}


def process_one_queued_csv(
    session_factory: Callable[[], Session], *, store,
    authorize: Authorization,
) -> dict:
    """Execute one bounded queued CSV using private storage; never deliver.

    The saved-task authorizer is checked on every execution. A repeat after a
    prior successful CSV finalize reuses and verifies the existing artifact.
    No automatic external messages or paid provider calls occur.
    """
    if not callable(authorize):
        raise QueuedCSVBlocked("Saved-task authorization required")

    def handler(claim: leases.LeaseClaim) -> str:
        with session_factory() as db:
            _runtime(db)
            row = _load_csv_row(db, claim.organization_id,
                                claim.owner_user_id, claim.job_id)
            if row is None or row["input_sha256"] != claim.input_sha256:
                raise QueuedCSVBlocked("Job and lease identity mismatch")
            _authorized(authorize, claim.organization_id,
                        claim.owner_user_id, row["engagement_id"], row["task_id"])
            if row["status"] in ("AWAITING_REVIEW", "APPROVED_FOR_DOWNLOAD"):
                # A previous attempt committed the output but lost its lease
                # confirmation. Validate the existing output, do not process
                # or store it again.
                if not row["output_ref"] or not leases._sha(row["output_sha256"]):
                    raise QueuedCSVBlocked("Previously finalized artifact is incomplete")
                data, _kind = store.retrieve(storage_ref=row["output_ref"])
                if (not isinstance(data, bytes) or len(data) > 1_000_000
                        or not hmac.compare_digest(
                            hashlib.sha256(data).hexdigest(), row["output_sha256"])):
                    raise QueuedCSVBlocked("Previously finalized output failed integrity")
                return row["output_sha256"]
            if row["status"] != "PROCESSING":
                raise QueuedCSVBlocked("Job is not eligible for processing")
            storage_ref, expected_size = leases.read_bound_input_metadata(
                db, claimed=claim)
        original = load_private_csv_input(
            organization_id=claim.organization_id,
            owner_user_id=claim.owner_user_id, job_id=claim.job_id,
            storage_ref=storage_ref, expected_sha256=claim.input_sha256,
            store=store,
        )
        if len(original) != expected_size:
            raise PrivateInputBlocked("Private input size mismatch")
        cleaned = clean_csv_text(
            original.decode("utf-8-sig", errors="strict"),
            max_bytes=1_000_000, max_rows=10_000,
        )
        output = cleaned.cleaned_csv.encode("utf-8")
        digest = hashlib.sha256(output).hexdigest()
        # Deterministic object identity is required of the injected store for
        # retry safety. No automatic delete on ambiguous DB commit.
        # From this point onward an object may have been written, even when
        # the storage call fails. Never automatically retry ambiguous output.
        try:
            saved = store.store(
                organization_id=claim.organization_id,
                application_id=claim.job_id, category="nova-csv-review",
                filename="cleaned.csv", content_type="text/csv",
                stream=BytesIO(output),
            )
            if (not isinstance(saved, (tuple, list)) or len(saved) < 3
                    or not isinstance(saved[1], str) or not saved[1]
                    or saved[2] != len(output)):
                raise QueuedCSVBlocked("Private output write size mismatch")
            with session_factory() as db:
                _runtime(db)
                _authorized(authorize, claim.organization_id, claim.owner_user_id,
                            row["engagement_id"], row["task_id"])
                updated = db.execute(sa.update(csvjobs.jobs).where(
                    csvjobs.jobs.c.id == claim.job_id,
                    csvjobs.jobs.c.organization_id == claim.organization_id,
                    csvjobs.jobs.c.owner_user_id == claim.owner_user_id,
                    csvjobs.jobs.c.status == "PROCESSING",
                    csvjobs.jobs.c.input_sha256 == claim.input_sha256,
                    sa.exists().where(
                        leases.lease_jobs.c.job_id == claim.job_id,
                        leases.lease_jobs.c.organization_id == claim.organization_id,
                        leases.lease_jobs.c.owner_user_id == claim.owner_user_id,
                        leases.lease_jobs.c.state == "RUNNING",
                        leases.lease_jobs.c.lease_token == claim.token,
                        leases.lease_jobs.c.lease_until > leases._now(),
                    ),
                ).values(status="AWAITING_REVIEW", output_ref=saved[1],
                         output_sha256=digest, updated_at=csvjobs._utc()))
                if updated.rowcount != 1:
                    db.rollback()
                    raise QueuedCSVBlocked("Lease changed before review finalize")
                db.commit()
        except Exception as exc:
            raise OutputUncertain(digest) from exc
        return digest

    return run_one(session_factory, handler, require_bound_input=True,
                   lease_seconds=300, retry_delay_seconds=30)


def review_processed_csv(
    session_factory: Callable[[], Session], *, organization_id: str,
    owner_user_id: str, job_id: str, approve: bool,
    authorize: Authorization,
) -> dict:
    """Require completed lease, valid task authorization and explicit review."""
    with session_factory() as db:
        _runtime(db)
        row = _load_csv_row(db, organization_id, owner_user_id, job_id)
        if row is None:
            raise QueuedCSVBlocked("Customer job not found")
        _authorized(authorize, organization_id, owner_user_id,
                    row["engagement_id"], row["task_id"])
        held = db.execute(sa.select(leases.lease_jobs.c.state,
                                    leases.lease_jobs.c.output_sha256).where(
            leases.lease_jobs.c.job_id == job_id,
            leases.lease_jobs.c.organization_id == organization_id,
            leases.lease_jobs.c.owner_user_id == owner_user_id,
        )).first()
        if (held is None or held.state != "COMPLETED"
                or not row["output_sha256"]
                or held.output_sha256 != row["output_sha256"]):
            raise QueuedCSVBlocked("Completed lease and artifact are required for review")
        return csvjobs.review_job(
            db, org=organization_id, owner=owner_user_id,
            job_id=job_id, approve=approve,
        )
