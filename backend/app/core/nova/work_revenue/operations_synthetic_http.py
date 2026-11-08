"""Unmounted, owner-only HTTP adapter for the synthetic Operations acceptance CSV.

This module MUST NOT be registered in the production application. It cannot
accept customer files and never uses the application database or real customer
records. Enable it only in a separately configured, isolated staging app.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import re
from urllib.parse import urlsplit
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
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


class SyntheticReviewDecision(BaseModel):
    approve: bool


def _review_db() -> sqlite3.Connection:
    """Synthetic-only review ledger separate from all application databases."""
    configured = str(os.getenv("NOVA_OPERATIONS_SYNTHETIC_LEDGER") or "").strip()
    p = Path(configured) if configured else None
    if (
        p is None or not p.is_absolute() or p.suffix != ".sqlite"
        or p.is_symlink() or not p.parent.is_dir()
    ):
        raise HTTPException(status_code=503, detail="Isolated synthetic review ledger missing")
    db = sqlite3.connect(str(p), timeout=5)
    db.execute("""CREATE TABLE IF NOT EXISTS synthetic_owner_reviews (
        reviewer_id TEXT NOT NULL,
        csv_sha256 TEXT NOT NULL,
        decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),
        PRIMARY KEY(reviewer_id, csv_sha256)
    )""")
    db.commit()
    return db


def _reviewer(user: UserContext) -> str:
    reviewer = str(getattr(user, "user_id", "") or "").strip()
    if not reviewer or len(reviewer) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in reviewer):
        raise HTTPException(status_code=403, detail="Verified owner identity required")
    return reviewer


def _synthetic_csv() -> tuple[bytes, str]:
    with tempfile.TemporaryDirectory(prefix="nova-synthetic-http-") as directory:
        root = Path(directory)
        report = run_synthetic_demo(root)
        if report.get("review_state") != "approved_by_synthetic_fixture":
            raise HTTPException(status_code=503, detail="Synthetic fixture incomplete")
        data = (root / "nova_synthetic_cleaned.csv").read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != report.get("sha256"):
            raise HTTPException(status_code=503, detail="Synthetic CSV integrity failure")
        return data, digest


@router.get("/preview")
def preview_synthetic_acceptance(
    user: UserContext = Depends(require_work_revenue_owner),
) -> dict[str, str]:
    _require_isolated_demo()
    reviewer = _reviewer(user)
    data, digest = _synthetic_csv()
    with _review_db() as db:
        row = db.execute(
            "SELECT decision FROM synthetic_owner_reviews WHERE reviewer_id=? AND csv_sha256=?",
            (reviewer, digest),
        ).fetchone()
    return {"csv_text": data.decode("utf-8"), "sha256": digest,
            "review_state": row[0] if row else "awaiting_owner_review",
            "data_class": "synthetic_only"}


@router.post("/review")
def review_synthetic_acceptance(
    decision: SyntheticReviewDecision,
    user: UserContext = Depends(require_work_revenue_owner),
) -> dict[str, str]:
    _require_isolated_demo()
    reviewer = _reviewer(user)
    _, digest = _synthetic_csv()
    status = "approved" if decision.approve else "rejected"
    with _review_db() as db:
        db.execute(
            "INSERT INTO synthetic_owner_reviews (reviewer_id,csv_sha256,decision) "
            "VALUES (?,?,?) ON CONFLICT(reviewer_id,csv_sha256) DO NOTHING",
            (reviewer, digest, status),
        )
        recorded = db.execute(
            "SELECT decision FROM synthetic_owner_reviews WHERE reviewer_id=? AND csv_sha256=?",
            (reviewer, digest),
        ).fetchone()
        if recorded is None or recorded[0] != status:
            raise HTTPException(status_code=409, detail="Conflicting prior review decision")
    return {"review_state": status, "sha256": digest}


@router.get("/download")
def download_synthetic_acceptance(
    user: UserContext = Depends(require_work_revenue_owner),
) -> Response:
    """Download the built-in synthetic CSV only after explicit owner review."""
    _require_isolated_demo()
    reviewer = _reviewer(user)
    data, digest = _synthetic_csv()
    with _review_db() as db:
        recorded = db.execute(
            "SELECT decision FROM synthetic_owner_reviews WHERE reviewer_id=? AND csv_sha256=?",
            (reviewer, digest),
        ).fetchone()
    if recorded is None or recorded[0] != "approved":
        raise HTTPException(status_code=403, detail="Explicit owner approval required")
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="nova-synthetic-cleaned.csv"',
            "Cache-Control": "no-store",
            "X-Nova-Data-Class": "synthetic-only",
        },
    )
