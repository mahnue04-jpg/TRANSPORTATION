"""Unmounted, owner-only HTTP adapter for the synthetic Operations acceptance CSV.

This module MUST NOT be registered in the production application. It cannot
accept customer files and never uses the application database or real customer
records. Enable it only in a separately configured, isolated staging app.
"""
from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import urlsplit
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.auth import UserContext
from app.core.nova.router import require_nova_access
from app.core.nova.work_revenue.router import require_work_revenue_owner
from scripts.nova_operations_synthetic_demo import run as run_synthetic_demo

router = APIRouter(
    prefix="/api/nova/work/operations/synthetic-acceptance",
    tags=["nova-operations-synthetic-acceptance-disabled"],
    dependencies=[Depends(require_nova_access), Depends(require_work_revenue_owner)],
)


def _require_isolated_demo() -> None:
    """Do not accidentally enable demo downloads on production or by default."""
    staging = (
        str(os.getenv("APP_ENV") or "").strip().lower() == "staging"
        and str(os.getenv("AMICOR_ENVIRONMENT") or "").strip().lower() == "staging"
    )
    opted_in = str(os.getenv("NOVA_OPERATIONS_SYNTHETIC_HTTP_ENABLED") or "").strip().lower() == "true"
    host = (urlsplit(str(os.getenv("RENDER_EXTERNAL_URL") or "")).hostname or "").lower()
    branch = str(os.getenv("RENDER_GIT_BRANCH") or "").strip().lower()
    is_preview = bool(re.fullmatch(r".+-pr-\d+\.onrender\.com", host))
    if not (staging and opted_in and is_preview and branch not in {"", "main", "master"}):
        raise HTTPException(
            status_code=503,
            detail="Synthetic acceptance download disabled; isolated staging opt-in required.",
        )


@router.get("/download")
def download_synthetic_acceptance(
    user: UserContext = Depends(require_work_revenue_owner),
) -> Response:
    """Return only the built-in synthetic CSV after its offline approval gate.

    The real owner dependency must authenticate/authorize the request. The
    synthetic fixture's reviewer is NOT the authenticated owner, and this
    endpoint is NOT a real customer artifact delivery implementation.
    """
    _require_isolated_demo()
    if not str(getattr(user, "user_id", "") or "").strip():
        raise HTTPException(status_code=403, detail="Verified owner identity required")
    with tempfile.TemporaryDirectory(prefix="nova-synthetic-http-") as folder:
        root = Path(folder)
        report = run_synthetic_demo(root)
        if report.get("review_state") != "approved_by_synthetic_fixture":
            raise HTTPException(status_code=503, detail="Synthetic approval not complete")
        csv_bytes = (root / "nova_synthetic_cleaned.csv").read_bytes()
        if hashlib.sha256(csv_bytes).hexdigest() != report.get("sha256"):
            raise HTTPException(status_code=503, detail="Synthetic CSV integrity check failed")
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="nova-synthetic-cleaned.csv"',
                "Cache-Control": "no-store",
                "X-Nova-Data-Class": "synthetic-only",
            },
        )
