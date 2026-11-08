"""Owner-only, zero-retention Operations Agent CSV cleanup endpoint.

Single-request bounded processing: no customer artifact persistence, no queued
workers, no external provider calls and no claims of contract completion.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import Response

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
CSV_MIME_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel", "application/octet-stream"}


@router.post("/csv-clean")
async def owner_csv_cleanup(
    file: UploadFile = File(...),
    owner_action: str | None = Header(default=None, alias="X-Nova-Owner-Action"),
    owner: UserContext = Depends(require_work_revenue_owner),
):
    """Return owner-reviewed CSV candidate, without saving original or output."""
    if os.getenv("NOVA_OPERATIONS_OWNER_CSV_ENABLED", "").lower() != "true":
        raise HTTPException(status_code=503, detail="Operations CSV processing not enabled")
    if owner_action != "process-csv-for-owner-review":
        raise HTTPException(status_code=403, detail="Explicit owner action header required")
    if not getattr(owner, "organization_id", None) or str(owner.organization_id).lower() == "global":
        raise HTTPException(status_code=403, detail="Specific owner organization required")
    name = file.filename or ""
    if not name or len(name) > 180 or not name.lower().endswith(".csv") or any(
        ord(char) < 32 or ord(char) == 127 for char in name
    ):
        raise HTTPException(status_code=400, detail="Valid CSV filename required")
    mime = (file.content_type or "").split(";", 1)[0].strip().lower()
    if mime not in CSV_MIME_TYPES:
        raise HTTPException(status_code=415, detail="Only CSV files supported")
    try:
        content = await file.read(LIMIT_BYTES + 1)
        if len(content) > LIMIT_BYTES:
            raise HTTPException(status_code=413, detail="CSV exceeds 1 MB limit")
        try:
            raw = content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="CSV must use UTF-8") from exc
        try:
            cleaned = clean_csv_text(raw, max_bytes=LIMIT_BYTES, max_rows=10_000)
        except SpreadsheetInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # No client-controlled filename in response. No server-side file output.
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
    finally:
        await file.close()
