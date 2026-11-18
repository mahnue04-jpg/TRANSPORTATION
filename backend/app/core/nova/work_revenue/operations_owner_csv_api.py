"""Owner-only, limited Operations Agent CSV cleanup endpoint.

Processes a bounded direct CSV body in memory. No app file persistence, no
background jobs, no external providers, and no customer contract acceptance.
This is NOT a generalized customer upload or delivery service.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.nova.work_revenue import service

from app.auth import UserContext
from app.core.nova.router import require_nova_access
from app.core.nova.work_revenue.owner_auth import require_work_revenue_owner
from app.core.nova.work_revenue.operations_csv_cleanup import (
    SpreadsheetInputError, clean_csv_text,
)

router = APIRouter(
    prefix="/operations",
    tags=["nova-operations-owner-csv"],
    dependencies=[Depends(require_nova_access), Depends(require_work_revenue_owner)],
)

LIMIT_BYTES = 1_000_000
CSV_MIME_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel"}


def _eligible_engagement(engagement: dict, org: str, owner_id: str) -> bool:
    """Same fail-closed gate for owner task listing and processing."""
    return (
        str(engagement.get("organization_id") or "") == org
        and str(engagement.get("owner_user_id") or "") == owner_id
        and str(engagement.get("status") or "").strip().upper() == "ACTIVE"
        and not str(engagement.get("blockers") or "").strip()
    )


def _csv_task_scope(task: dict) -> bool:
    """Only tasks explicitly described as CSV/spreadsheet cleanup are eligible.

    General Nova administrative work is not authorization to transform files.
    This label gate is intentionally narrow; a future structured work-type
    authorization should replace text labels before customer production.
    """
    description = " ".join(
        str(task.get(field) or "").strip().lower()
        for field in ("title", "description", "deliverable")
    )
    return any(
        label in description
        for label in (
            "csv", "spreadsheet cleanup", "spreadsheet cleaning",
            "data cleanup", "data cleaning", "data validation",
            "data reconciliation",
        )
    )


def _eligible_task(task: dict, completed_task_ids: set[str]) -> bool:
    """Restrict CSV work to unblocked, explicitly scoped supervised Nova tasks."""
    dependency = str(task.get("depends_on_task_id") or "").strip()
    return (
        _csv_task_scope(task)
        and str(task.get("classification") or "").strip().upper() == "NOVA"
        and str(task.get("responsible_party") or "").strip().upper() == "NOVA"
        and task.get("review_required") is True
        and str(task.get("status") or "").strip().upper()
        in {"READY", "NOT_STARTED", "IN_PROGRESS"}
        and not str(task.get("blocked_reason") or "").strip()
        and not str(task.get("required_owner_input") or "").strip()
        and (not dependency or dependency in completed_task_ids)
    )


def _completed_task_ids(engagement: dict) -> set[str]:
    return {
        str(task.get("task_id") or "")
        for task in engagement.get("tasks") or []
        if isinstance(task, dict)
        and str(task.get("status") or "").strip().upper() == "COMPLETE"
    }


@router.post("/csv-clean")
async def owner_csv_cleanup(
    request: Request,
    owner_action: str | None = Header(default=None, alias="X-Nova-Owner-Action"),
    filename: str | None = Header(default=None, alias="X-Nova-File-Name"),
    owner: UserContext = Depends(require_work_revenue_owner),
) -> Response:
    """Return a non-persisted CSV candidate for explicit owner inspection."""
    if os.getenv("NOVA_OPERATIONS_OWNER_CSV_ENABLED", "").strip().lower() != "true":
        raise HTTPException(status_code=503, detail="Operations CSV processing not enabled")
    if owner_action != "process-csv-for-owner-review":
        raise HTTPException(status_code=403, detail="Explicit owner action header required")
    org = getattr(owner, "organization_id", None)
    if not isinstance(org, str) or not org.strip() or org.strip().lower() == "global":
        raise HTTPException(status_code=403, detail="Specific owner organization required")
    name = filename or ""
    if not name or len(name) > 180 or not name.lower().endswith(".csv") or any(
        ord(char) < 32 or ord(char) == 127 or char in "/\\" for char in name
    ):
        raise HTTPException(status_code=400, detail="Valid CSV filename required")
    mime = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if mime not in CSV_MIME_TYPES:
        raise HTTPException(status_code=415, detail="Only CSV files supported")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            amount = int(length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid request size") from exc
        if amount > LIMIT_BYTES:
            raise HTTPException(status_code=413, detail="CSV exceeds 1 MB limit")
        if amount < 0:
            raise HTTPException(status_code=400, detail="Invalid request size")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > LIMIT_BYTES:
            raise HTTPException(status_code=413, detail="CSV exceeds 1 MB limit")
        content.extend(chunk)
    try:
        raw = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must use UTF-8") from exc
    try:
        cleaned = clean_csv_text(raw, max_bytes=LIMIT_BYTES, max_rows=10_000)
    except SpreadsheetInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        cleaned.cleaned_csv.encode("utf-8"), media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="nova-cleaned-review.csv"',
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "X-Nova-Input-Rows": str(cleaned.input_rows),
            "X-Nova-Output-Rows": str(cleaned.output_rows),
            "X-Nova-Output-SHA256": cleaned.output_sha256,
            "X-Nova-Owner-Review-Required": "true",
        },
    )


@router.post("/engagements/{engagement_id}/tasks/{task_id}/csv-clean")
async def scoped_owner_csv_cleanup(
    engagement_id: str,
    task_id: str,
    request: Request,
    filename: str | None = Header(default=None, alias="X-Nova-File-Name"),
    owner_action: str | None = Header(default=None, alias="X-Nova-Owner-Action"),
    scope_confirmed: str | None = Header(default=None, alias="X-Nova-Scope-Confirmed"),
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
) -> Response:
    """Process a CSV only for an existing, active, owner-visible Nova task.

    The owner confirms contractual authority; the system does NOT independently
    verify a signed agreement and does NOT mark work delivered or completed.
    """
    if os.getenv("NOVA_OPERATIONS_OWNER_CSV_ENABLED", "").strip().lower() != "true":
        raise HTTPException(status_code=503, detail="Operations CSV processing not enabled")
    if scope_confirmed != "owner-confirmed-client-authorization":
        raise HTTPException(status_code=403, detail="Owner must confirm contract and data-processing authority")
    if not engagement_id or not task_id or len(engagement_id) > 120 or len(task_id) > 120:
        raise HTTPException(status_code=400, detail="Valid engagement and task IDs required")
    org = str(getattr(owner, "organization_id", "") or "").strip()
    if not org or org.lower() == "global":
        raise HTTPException(status_code=403, detail="Owner organization scope required")
    try:
        engagement = service.get_engagement(
            db, engagement_id, organization_id=org, user=owner,
        )
    except service.NovaWorkError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if (
        str(engagement.get("engagement_id") or "") != engagement_id
        or not _eligible_engagement(engagement, org, str(owner.user_id))
    ):
        raise HTTPException(status_code=409, detail="Engagement must be active, owner-scoped and unblocked")
    task = next(
        (item for item in (engagement.get("tasks") or [])
         if isinstance(item, dict) and str(item.get("task_id") or "") == task_id),
        None,
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found on authorized engagement")
    if not _eligible_task(task, _completed_task_ids(engagement)):
        raise HTTPException(status_code=409, detail="Task is not ready for supervised Nova processing")
    result = await owner_csv_cleanup(
        request, owner_action=owner_action, filename=filename, owner=owner,
    )
    result.headers["X-Nova-Engagement-ID"] = engagement_id
    result.headers["X-Nova-Task-ID"] = task_id
    result.headers["X-Nova-Delivery-Status"] = "owner-review-only-not-delivered"
    return result



# Durable customer-job endpoints are independent of the legacy in-memory
# cleanup endpoint. They are default-off and require PostgreSQL + private S3.
from . import operations_customer_csv_jobs as durable_csv


def _check_saved_csv_assignment(
    db: Session, *, owner: UserContext, engagement_id: str, task_id: str,
) -> None:
    org = str(getattr(owner, "organization_id", "") or "").strip()
    if not org or org.lower() == "global":
        raise HTTPException(403, "Specific owner organization required")
    try:
        engagement = service.get_engagement(
            db, engagement_id, organization_id=org, user=owner,
        )
    except service.NovaWorkError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if not _eligible_engagement(engagement, org, str(owner.user_id)):
        raise HTTPException(409, "Engagement no longer eligible")
    task = next(
        (item for item in engagement.get("tasks") or []
         if isinstance(item, dict) and item.get("task_id") == task_id),
        None,
    )
    if task is None:
        raise HTTPException(404, "Task not found on authorized engagement")
    if not _eligible_task(task, _completed_task_ids(engagement)):
        raise HTTPException(409, "Task not authorized for CSV processing")


def _durable_error(exc: durable_csv.CustomerCSVBlocked):
    raise HTTPException(exc.code, str(exc)) from exc


@router.post("/durable/engagements/{engagement_id}/tasks/{task_id}/jobs", status_code=202)
async def create_durable_csv_job(
    engagement_id: str,
    task_id: str,
    request: Request,
    request_key: str | None = Header(default=None, alias="Idempotency-Key"),
    filename: str | None = Header(default=None, alias="X-Nova-File-Name"),
    scope_confirmed: str | None = Header(default=None, alias="X-Nova-Scope-Confirmed"),
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    if scope_confirmed != "owner-confirmed-client-authorization":
        raise HTTPException(403, "Owner data processing authorization required")
    if not isinstance(filename, str) or not filename.lower().endswith(".csv") or len(filename) > 180 or any(
        ord(c) < 32 or ord(c) == 127 or c in "/\\\\"
        for c in filename
    ):
        raise HTTPException(400, "Safe CSV filename required")
    if (request.headers.get("content-type") or "").split(";")[0].strip().lower() not in CSV_MIME_TYPES:
        raise HTTPException(415, "Only CSV supported")
    try:
        durable_csv.require_runtime(db)
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)
    _check_saved_csv_assignment(
        db, owner=owner, engagement_id=engagement_id, task_id=task_id,
    )
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > LIMIT_BYTES:
            raise HTTPException(413, "CSV exceeds 1 MB")
        content.extend(chunk)
    try:
        return durable_csv.submit_review_job(
            db, org=str(owner.organization_id), owner=str(owner.user_id),
            engagement_id=engagement_id, task_id=task_id,
            request_key=request_key or "", raw=bytes(content),
        )
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)
    except (UnicodeDecodeError, SpreadsheetInputError) as exc:
        raise HTTPException(400, "CSV content invalid") from exc



def _reject_queued_job_in_legacy_path(
    db: Session, *, job_id: str, owner: UserContext,
) -> None:
    """Prevent legacy review/download/recover from bypassing queued lease gates.

    The original synchronous path remains available if the lease table has not
    been migrated. Database inspection errors fail closed instead of treating
    queued jobs as unguarded legacy work.
    """
    import sqlalchemy as sa
    from . import operations_postgres_leases as queued_leases

    try:
        if not sa.inspect(db.get_bind()).has_table(queued_leases.lease_jobs.name):
            return
        scoped = db.execute(sa.select(queued_leases.lease_jobs.c.job_id).where(
            queued_leases.lease_jobs.c.job_id == job_id,
            queued_leases.lease_jobs.c.organization_id == str(owner.organization_id),
            queued_leases.lease_jobs.c.owner_user_id == str(owner.user_id),
        )).first()
    except Exception as exc:
        raise HTTPException(503, "CSV job mode cannot be verified") from exc
    if scoped is not None:
        raise HTTPException(409, "Queued job requires supervised owner workflow")


@router.get("/durable/jobs/{job_id}")
def durable_csv_job_status(
    job_id: str,
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    try:
        data = durable_csv.job_status(
            db, org=str(owner.organization_id), owner=str(owner.user_id), job_id=job_id,
        )
        _check_saved_csv_assignment(
            db, owner=owner, engagement_id=data["engagement_id"], task_id=data["task_id"],
        )
        _reject_queued_job_in_legacy_path(db, job_id=job_id, owner=owner)
        return data
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)


@router.post("/durable/jobs/{job_id}/review")
async def durable_csv_review(
    job_id: str,
    request: Request,
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    try:
        data = durable_csv.job_status(
            db, org=str(owner.organization_id), owner=str(owner.user_id), job_id=job_id,
        )
        _check_saved_csv_assignment(
            db, owner=owner, engagement_id=data["engagement_id"], task_id=data["task_id"],
        )
        _reject_queued_job_in_legacy_path(db, job_id=job_id, owner=owner)
        payload = await request.json()
        if not isinstance(payload, dict) or type(payload.get("approve")) is not bool:
            raise HTTPException(400, "Boolean approve required")
        return durable_csv.review_job(
            db, org=str(owner.organization_id), owner=str(owner.user_id),
            job_id=job_id, approve=payload["approve"],
        )
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)


@router.post("/durable/jobs/{job_id}/recover")
def recover_durable_csv_job(
    job_id: str,
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    try:
        data = durable_csv.job_status(
            db, org=str(owner.organization_id), owner=str(owner.user_id), job_id=job_id,
        )
        _check_saved_csv_assignment(
            db, owner=owner, engagement_id=data["engagement_id"], task_id=data["task_id"],
        )
        _reject_queued_job_in_legacy_path(db, job_id=job_id, owner=owner)
        return durable_csv.recover_stale_job(
            db, org=str(owner.organization_id), owner=str(owner.user_id), job_id=job_id,
        )
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)


@router.get("/durable/jobs/{job_id}/download")
def durable_csv_download(
    job_id: str,
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    try:
        data = durable_csv.job_status(
            db, org=str(owner.organization_id), owner=str(owner.user_id), job_id=job_id,
        )
        _check_saved_csv_assignment(
            db, owner=owner, engagement_id=data["engagement_id"], task_id=data["task_id"],
        )
        _reject_queued_job_in_legacy_path(db, job_id=job_id, owner=owner)
        content = durable_csv.download_review(
            db, org=str(owner.organization_id), owner=str(owner.user_id), job_id=job_id,
        )
        return Response(content=content, media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="nova-cleaned-review.csv"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Nova-Delivery-Status": "not-delivered",
        })
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)


@router.get("/eligible-csv-tasks")
def eligible_csv_tasks(
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """List eligible saved Nova tasks only for the authenticated owner."""
    if os.getenv("NOVA_OPERATIONS_OWNER_CSV_ENABLED", "").strip().lower() != "true":
        raise HTTPException(status_code=503, detail="Operations CSV processing not enabled")
    org = str(getattr(owner, "organization_id", "") or "").strip()
    if not org or org.lower() == "global":
        raise HTTPException(status_code=403, detail="Owner organization scope required")
    engagements = service.list_engagements(db, organization_id=org, user=owner)
    eligible = []
    for engagement in engagements:
        if not _eligible_engagement(engagement, org, str(owner.user_id)):
            continue
        completed = _completed_task_ids(engagement)
        for task in engagement.get("tasks") or []:
            if not isinstance(task, dict) or not _eligible_task(task, completed):
                continue
            eligible.append({
                "engagement_id": engagement["engagement_id"],
                "engagement_title": str(engagement.get("title") or engagement.get("service") or "")[:120],
                "task_id": task["task_id"],
                "task_title": str(task.get("title") or "")[:120],
                "task_status": task["status"],
                "review_required": True,
            })
            if len(eligible) >= 100:
                break
        if len(eligible) >= 100:
            break
    return {"tasks": eligible, "count": len(eligible), "owner_only": True,
            "execution_authorized": False, "handoff_created": False}


# Supervised queued CSV routes. These are a new, separately gated path and do
# not change the legacy synchronous owner CSV API. No hosted worker is started.
import sqlalchemy as _sa
from sqlalchemy.orm import sessionmaker as _sessionmaker
from . import operations_postgres_leases as _ops_leases
from .operations_private_input import PrivateInputBlocked as _PrivateInputBlocked
from . import operations_queued_csv_pipeline as _queued_csv
from .operations_owner_task_authorizer import owner_task_authorizer as _owner_task_authorizer


def _queued_csv_gate(db: Session) -> None:
    if os.getenv("NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED", "").lower() != "true":
        raise HTTPException(503, "Supervised queued CSV workflow disabled")
    try:
        durable_csv.require_runtime(db)
        _ops_leases._guard(db)
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)
    except _ops_leases.LeaseBlocked as exc:
        raise HTTPException(503, "Supervised queue unavailable") from exc


def _queued_factory(db: Session):
    # SessionLocal would accidentally use the application's default database
    # in isolated tests; keep the exact injected, guarded PostgreSQL bind.
    return _sessionmaker(bind=db.get_bind(), expire_on_commit=False)


def _queued_error(exc: Exception) -> None:
    if isinstance(exc, durable_csv.CustomerCSVBlocked):
        _durable_error(exc)
    if isinstance(exc, (_queued_csv.QueuedCSVBlocked,
                        _ops_leases.LeaseBlocked, _PrivateInputBlocked)):
        raise HTTPException(409, "Queued Operations request blocked") from exc
    raise exc


@router.post("/queued/engagements/{engagement_id}/tasks/{task_id}/jobs", status_code=202)
async def create_supervised_queued_csv_job(
    engagement_id: str,
    task_id: str,
    request: Request,
    request_key: str | None = Header(default=None, alias="Idempotency-Key"),
    filename: str | None = Header(default=None, alias="X-Nova-File-Name"),
    scope_confirmed: str | None = Header(default=None, alias="X-Nova-Scope-Confirmed"),
    owner_action: str | None = Header(default=None, alias="X-Nova-Owner-Action"),
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    _queued_csv_gate(db)
    if (owner_action != "queue-csv-for-owner-review"
            or scope_confirmed != "owner-confirmed-client-authorization"):
        raise HTTPException(403, "Explicit owner action and processing authority required")
    if (not isinstance(filename, str) or len(filename) > 180
            or not filename.lower().endswith(".csv")
            or any(ord(c) < 32 or ord(c) == 127 or c in "/\\"
                   for c in filename)):
        raise HTTPException(400, "Safe CSV filename required")
    if (request.headers.get("content-type") or "").split(";")[0].strip().lower() not in CSV_MIME_TYPES:
        raise HTTPException(415, "Only CSV supported")
    _check_saved_csv_assignment(
        db, owner=owner, engagement_id=engagement_id, task_id=task_id)
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > LIMIT_BYTES:
            raise HTTPException(413, "CSV exceeds 1 MB limit")
        content.extend(chunk)
    factory = _queued_factory(db)
    authorize = _owner_task_authorizer(factory, authenticated_owner=owner)
    try:
        return _queued_csv.submit_queued_csv(
            factory,
            organization_id=str(owner.organization_id),
            owner_user_id=str(owner.user_id),
            engagement_id=engagement_id, task_id=task_id,
            request_key=request_key or "", raw=bytes(content),
            store=durable_csv._store(), authorize=authorize)
    except Exception as exc:
        _queued_error(exc)


@router.post("/queued/jobs/{job_id}/process")
def process_supervised_queued_csv_job(
    job_id: str,
    owner_action: str | None = Header(default=None, alias="X-Nova-Owner-Action"),
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    _queued_csv_gate(db)
    if owner_action != "process-queued-csv-for-owner-review":
        raise HTTPException(403, "Explicit supervised processing action required")
    org, owner_id = str(owner.organization_id), str(owner.user_id)
    try:
        row = durable_csv._owned(db, job_id, org, owner_id)
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)
    _check_saved_csv_assignment(
        db, owner=owner, engagement_id=row["engagement_id"], task_id=row["task_id"])
    factory = _queued_factory(db)
    try:
        result = _queued_csv.process_one_queued_csv(
            factory, store=durable_csv._store(),
            authorize=_owner_task_authorizer(factory, authenticated_owner=owner),
            job_id=job_id, organization_id=org, owner_user_id=owner_id)
        return {**result, "delivered": False}
    except Exception as exc:
        _queued_error(exc)


@router.post("/queued/jobs/{job_id}/review")
async def review_supervised_queued_csv_job(
    job_id: str,
    request: Request,
    owner_action: str | None = Header(default=None, alias="X-Nova-Owner-Action"),
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    _queued_csv_gate(db)
    if owner_action != "review-completed-queued-csv":
        raise HTTPException(403, "Explicit owner review action required")
    payload = await request.json()
    if not isinstance(payload, dict) or type(payload.get("approve")) is not bool:
        raise HTTPException(400, "Boolean approve required")
    org, owner_id = str(owner.organization_id), str(owner.user_id)
    try:
        row = durable_csv._owned(db, job_id, org, owner_id)
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)
    _check_saved_csv_assignment(
        db, owner=owner, engagement_id=row["engagement_id"], task_id=row["task_id"])
    factory = _queued_factory(db)
    try:
        return _queued_csv.review_processed_csv(
            factory, organization_id=org, owner_user_id=owner_id, job_id=job_id,
            approve=payload["approve"],
            authorize=_owner_task_authorizer(factory, authenticated_owner=owner),
            store=durable_csv._store())
    except Exception as exc:
        _queued_error(exc)


@router.get("/queued/jobs/{job_id}")
def supervised_queued_csv_status(
    job_id: str,
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    """Owner-scoped status without exposing private object references."""
    _queued_csv_gate(db)
    org, owner_id = str(owner.organization_id), str(owner.user_id)
    try:
        row = durable_csv._owned(db, job_id, org, owner_id)
        _check_saved_csv_assignment(
            db, owner=owner, engagement_id=row["engagement_id"],
            task_id=row["task_id"])
        lease = db.execute(_sa.select(
            _ops_leases.lease_jobs.c.state,
            _ops_leases.lease_jobs.c.attempts,
        ).where(
            _ops_leases.lease_jobs.c.job_id == job_id,
            _ops_leases.lease_jobs.c.organization_id == org,
            _ops_leases.lease_jobs.c.owner_user_id == owner_id,
        )).first()
        return {
            "job_id": job_id,
            "status": row["status"],
            "lease_status": lease.state if lease else "INPUT_NOT_BOUND",
            "attempts": lease.attempts if lease else 0,
            "delivered": False,
        }
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)


@router.get("/queued/jobs/{job_id}/download")
def supervised_queued_csv_download(
    job_id: str,
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    """No download until explicit approval and confirmed lease completion."""
    _queued_csv_gate(db)
    org, owner_id = str(owner.organization_id), str(owner.user_id)
    try:
        row = durable_csv._owned(db, job_id, org, owner_id)
        _check_saved_csv_assignment(
            db, owner=owner, engagement_id=row["engagement_id"],
            task_id=row["task_id"])
        if row["status"] != "APPROVED_FOR_DOWNLOAD":
            raise HTTPException(409, "Explicit owner approval required")
        lease = db.execute(_sa.select(
            _ops_leases.lease_jobs.c.state,
            _ops_leases.lease_jobs.c.output_sha256,
        ).where(
            _ops_leases.lease_jobs.c.job_id == job_id,
            _ops_leases.lease_jobs.c.organization_id == org,
            _ops_leases.lease_jobs.c.owner_user_id == owner_id,
        )).first()
        if (lease is None or lease.state != "COMPLETED"
                or lease.output_sha256 != row["output_sha256"]):
            raise HTTPException(409, "Verified completed job required")
        content = durable_csv.download_review(
            db, org=org, owner=owner_id, job_id=job_id)
        return Response(content=content, media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="nova-cleaned-review.csv"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Nova-Delivery-Status": "not-delivered",
        })
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)


@router.get("/queued/jobs/{job_id}/recovery")
def supervised_queued_csv_recovery(
    job_id: str,
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    """Read-only, scoped diagnostics; never retry, release or deliver."""
    from .operations_recovery_diagnostics import inspect_recovery
    _queued_csv_gate(db)
    org, owner_id = str(owner.organization_id), str(owner.user_id)
    try:
        row = durable_csv._owned(db, job_id, org, owner_id)
        _check_saved_csv_assignment(
            db, owner=owner, engagement_id=row["engagement_id"],
            task_id=row["task_id"])
        return inspect_recovery(
            db, organization_id=org, owner_user_id=owner_id,
            job_id=job_id)
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)
    except _ops_leases.LeaseBlocked as exc:
        raise HTTPException(409, "Queued job recovery unavailable") from exc


@router.post("/queued/jobs/{job_id}/cancel")
def cancel_supervised_queued_csv_job(
    job_id: str,
    owner_action: str | None = Header(default=None, alias="X-Nova-Owner-Action"),
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    """Explicit authorized cancellation fences an outstanding lease.

    Held/completed jobs cannot be silently canceled through this route:
    their private artifacts need separate owner reconciliation.
    """
    _queued_csv_gate(db)
    if owner_action != "cancel-queued-csv-job":
        raise HTTPException(403, "Explicit owner cancellation required")
    org, owner_id = str(owner.organization_id), str(owner.user_id)
    try:
        row = durable_csv._owned(db, job_id, org, owner_id)
        _check_saved_csv_assignment(
            db, owner=owner, engagement_id=row["engagement_id"],
            task_id=row["task_id"])
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)
    try:
        cancelled = _ops_leases.cancel(
            db, job_id=job_id, organization_id=org, owner_user_id=owner_id)
    except _ops_leases.LeaseBlocked as exc:
        raise HTTPException(409, "Queued cancellation unavailable") from exc
    if not cancelled:
        raise HTTPException(409, "Job cannot be canceled in its current state")
    return {"job_id": job_id, "lease_status": "CANCELLED",
            "delivered": False, "safe_to_auto_retry": False}


@router.post("/queued/jobs/{job_id}/restore-input")
async def restore_supervised_queued_csv_input(
    job_id: str,
    request: Request,
    filename: str | None = Header(default=None, alias="X-Nova-File-Name"),
    owner_action: str | None = Header(default=None, alias="X-Nova-Owner-Action"),
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    """Explicit owner reupload for the same unbound, never-claimed job.

    A past uncertain private upload may remain orphaned. This route never
    guesses its reference, lists objects or deletes anything.
    """
    _queued_csv_gate(db)
    if owner_action != "restore-unbound-csv-input":
        raise HTTPException(403, "Explicit owner input recovery required")
    if (not isinstance(filename, str) or len(filename) > 180
            or not filename.lower().endswith(".csv")
            or any(ord(c) < 32 or ord(c) == 127 or c in "/\\"
                   for c in filename)):
        raise HTTPException(400, "Safe CSV filename required")
    if (request.headers.get("content-type") or "").split(";")[0].strip().lower() not in CSV_MIME_TYPES:
        raise HTTPException(415, "Only CSV supported")
    org, owner_id = str(owner.organization_id), str(owner.user_id)
    try:
        row = durable_csv._owned(db, job_id, org, owner_id)
    except durable_csv.CustomerCSVBlocked as exc:
        _durable_error(exc)
    _check_saved_csv_assignment(
        db, owner=owner, engagement_id=row["engagement_id"],
        task_id=row["task_id"])
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > LIMIT_BYTES:
            raise HTTPException(413, "CSV exceeds 1 MB limit")
        content.extend(chunk)
    factory = _queued_factory(db)
    try:
        return _queued_csv.restore_unbound_queued_csv(
            factory, organization_id=org, owner_user_id=owner_id,
            job_id=job_id, raw=bytes(content), store=durable_csv._store(),
            authorize=_owner_task_authorizer(factory, authenticated_owner=owner))
    except Exception as exc:
        _queued_error(exc)
