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
from app.core.nova.work_revenue.router import require_work_revenue_owner
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
        or str(engagement.get("organization_id") or "") != org
        or str(engagement.get("status") or "").strip().upper() != "ACTIVE"
        or str(engagement.get("blockers") or "").strip()
    ):
        raise HTTPException(status_code=409, detail="Engagement must be active, owner-scoped and unblocked")
    task = next(
        (item for item in (engagement.get("tasks") or [])
         if isinstance(item, dict) and str(item.get("task_id") or "") == task_id),
        None,
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found on authorized engagement")
    if (
        str(task.get("classification") or "").upper() != "NOVA"
        or str(task.get("responsible_party") or "").upper() != "NOVA"
        or not bool(task.get("review_required"))
        or str(task.get("status") or "").upper() not in {"READY", "NOT_STARTED", "IN_PROGRESS"}
        or str(task.get("blocked_reason") or "").strip()
    ):
        raise HTTPException(status_code=409, detail="Task is not ready for supervised Nova processing")
    result = await owner_csv_cleanup(
        request, owner_action=owner_action, filename=filename, owner=owner,
    )
    result.headers["X-Nova-Engagement-ID"] = engagement_id
    result.headers["X-Nova-Task-ID"] = task_id
    result.headers["X-Nova-Delivery-Status"] = "owner-review-only-not-delivered"
    return result
