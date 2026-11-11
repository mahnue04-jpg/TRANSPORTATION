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


# Bookkeeping endpoints: separate from CSV cleanup. STRICT default-OFF and
# fail-closed unless the server independently verifies current signed contract,
# client AI-use approval, owner scope and a structured eligible Work task.
# Header/checkbox assertions are NOT substitutes for those records.
from . import bookkeeping_durable_jobs as bk_jobs
from .bookkeeping_scope import resolve_bookkeeping_assignment, ConsentNotVerified


def _accounting_unavailable(exc: Exception):
    if isinstance(exc, ConsentNotVerified):
        raise HTTPException(403, "Verified client consent and accounting task scope required") from exc
    if isinstance(exc, bk_jobs.base.CustomerCSVBlocked):
        raise HTTPException(exc.code, str(exc)) from exc
    raise exc


def _require_accounting_job_scope(
    db: Session, *, owner: UserContext, job_id: str,
    lock_consent: bool = False,
) -> dict:
    # Always revalidate consent on each read, review or download. Revoke
    # permission -> block all access; no previously issued download token.
    info = bk_jobs.bookkeeping_status(
        db, org=str(owner.organization_id), owner=str(owner.user_id), job_id=job_id,
    )
    resolve_bookkeeping_assignment(
        db, owner=owner, engagement_id=info["engagement_id"],
        task_id=info["task_id"], work_type=info["work_type"],
        lock_consent=lock_consent,
    )
    return info


@router.post(
    "/durable/bookkeeping/engagements/{engagement_id}/tasks/{task_id}/{work_type}/jobs",
    status_code=202,
)
async def create_bookkeeping_review_job(
    engagement_id: str, task_id: str, work_type: str, request: Request,
    request_key: str | None = Header(default=None, alias="Idempotency-Key"),
    filename: str | None = Header(default=None, alias="X-Nova-File-Name"),
    as_of: str | None = Header(default=None, alias="X-Nova-As-Of"),
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    try:
        bk_jobs.require_bookkeeping_runtime(db)
        # Strict single-source CSV transport. Bank-match secondary file needs
        # separately verified private storage and explicit contract scope.
        if not isinstance(filename, str) or not filename.lower().endswith(".csv") or len(filename) > 180 or any(
            ord(c) < 32 or ord(c) == 127 or c in "/\\"
            for c in filename
        ):
            raise HTTPException(400, "Safe CSV filename required")
        mime = (request.headers.get("content-type") or "").split(";")[0].lower().strip()
        if mime not in CSV_MIME_TYPES:
            raise HTTPException(415, "CSV input required")
        assignment = resolve_bookkeeping_assignment(
            db, owner=owner, engagement_id=engagement_id, task_id=task_id, work_type=work_type,
        )
        content = bytearray()
        async for part in request.stream():
            if len(content) + len(part) > LIMIT_BYTES:
                raise HTTPException(413, "Bookkeeping CSV exceeds 1 MB")
            content.extend(part)
        # Uploads can be slow: consent may expire or be revoked while the
        # request body is streamed. Recheck trusted server scope immediately
        # before creating any job or private artifact.
        assignment = resolve_bookkeeping_assignment(
            db, owner=owner, engagement_id=engagement_id,
            task_id=task_id, work_type=work_type,
        )
        def final_authorization(session: Session) -> None:
            resolve_bookkeeping_assignment(
                session, owner=owner, engagement_id=engagement_id,
                task_id=task_id, work_type=work_type, lock_consent=True,
            )

        result = bk_jobs.submit_bookkeeping_review(
            db, assignment=assignment, request_id=request_key or "",
            primary=bytes(content), as_of=as_of,
            final_authorization=final_authorization,
        )
        return {**result, "delivery_allowed": False}
    except (ConsentNotVerified, bk_jobs.base.CustomerCSVBlocked) as exc:
        _accounting_unavailable(exc)


@router.get("/durable/bookkeeping/jobs/{job_id}")
def bookkeeping_review_job_status(
    job_id: str,
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    try:
        return _require_accounting_job_scope(db, owner=owner, job_id=job_id)
    except (ConsentNotVerified, bk_jobs.base.CustomerCSVBlocked) as exc:
        _accounting_unavailable(exc)


@router.post("/durable/bookkeeping/jobs/{job_id}/review")
async def bookkeeping_owner_review(
    job_id: str, request: Request,
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or type(payload.get("approve")) is not bool:
            raise HTTPException(400, "Explicit Boolean review decision required")
        _require_accounting_job_scope(db, owner=owner, job_id=job_id, lock_consent=True)
        return bk_jobs.review_bookkeeping(
            db, org=str(owner.organization_id), owner=str(owner.user_id),
            job_id=job_id, approve=payload["approve"],
        )
    except (ConsentNotVerified, bk_jobs.base.CustomerCSVBlocked) as exc:
        _accounting_unavailable(exc)


@router.get("/durable/bookkeeping/jobs/{job_id}/download")
def bookkeeping_private_review_download(
    job_id: str,
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    try:
        _require_accounting_job_scope(db, owner=owner, job_id=job_id, lock_consent=True)
        output = bk_jobs.download_bookkeeping(
            db, org=str(owner.organization_id), owner=str(owner.user_id),
            job_id=job_id,
        )
        return Response(content=output, media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="nova-bookkeeping-review.csv"',
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "X-Nova-Delivery-Status": "not-delivered",
            "X-Nova-Owner-Review-Required": "true",
        })
    except (ConsentNotVerified, bk_jobs.base.CustomerCSVBlocked) as exc:
        _accounting_unavailable(exc)


@router.post("/durable/bookkeeping/jobs/{job_id}/recover")
def bookkeeping_owner_recover_stale_job(
    job_id: str,
    owner: UserContext = Depends(require_work_revenue_owner),
    db: Session = Depends(get_db),
):
    """Explicit owner recovery only; no reprocessing, payment or client send."""
    try:
        _require_accounting_job_scope(db, owner=owner, job_id=job_id)
        return bk_jobs.recover_stale_bookkeeping(
            db, org=str(owner.organization_id), owner=str(owner.user_id),
            job_id=job_id,
        )
    except (ConsentNotVerified, bk_jobs.base.CustomerCSVBlocked) as exc:
        _accounting_unavailable(exc)
