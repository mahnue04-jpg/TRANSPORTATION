"""Isolated, local-only AMICOR Nova Operations Agent demonstration server.

Launch explicitly with demo-only credentials and no application database:
  APP_ENV=demo AMICOR_ENVIRONMENT=demo NOVA_DEMO_STANDALONE=true \
  NOVA_DEMO_OWNER_USER=demo-owner NOVA_DEMO_OWNER_PASSWORD=<random-secret> \
  uvicorn scripts.nova_operations_standalone_demo:app --host 127.0.0.1 --port 8765

Never mount in app.main, deploy as production app, or accept customer uploads.
This server uses a private temporary SQLite ledger and only hardcoded CSV
fixture data. Restarting the process resets review decisions.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sqlite3
import tempfile
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from scripts.nova_operations_synthetic_demo import run as offline_demo

BASE = "/api/nova/work/operations/synthetic-acceptance"
app = FastAPI(title="Nova Operations synthetic local demo", docs_url=None, redoc_url=None, openapi_url=None)
_private_directory = tempfile.TemporaryDirectory(prefix="nova-local-demo-")
_ledger = Path(_private_directory.name) / "owner-review.sqlite"
_HTML = Path(__file__).resolve().parents[1] / "app/core/nova/work_revenue/operations_synthetic_review.html"


def _safe_environment() -> None:
    if not (
        os.getenv("NOVA_DEMO_STANDALONE") == "true"
        and os.getenv("APP_ENV") == "demo"
        and os.getenv("AMICOR_ENVIRONMENT") == "demo"
        and not os.getenv("DATABASE_URL")
        and not os.getenv("RENDER_EXTERNAL_URL")
        and not os.getenv("RENDER_SERVICE_NAME")
        and not os.getenv("RENDER")
    ):
        raise HTTPException(status_code=503, detail="Isolated local demo is not enabled")
    username = os.getenv("NOVA_DEMO_OWNER_USER") or ""
    password = os.getenv("NOVA_DEMO_OWNER_PASSWORD") or ""
    if not username or len(password) < 24 or any(c.isspace() for c in username):
        raise HTTPException(status_code=503, detail="Strong dedicated demo credentials not configured")


def _owner(authorization: str | None = Header(default=None)) -> str:
    _safe_environment()
    try:
        if not authorization or not authorization.startswith("Basic "):
            raise ValueError("Basic credentials required")
        raw = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
        actual_user, divider, actual_password = raw.partition(":")
        if not divider:
            raise ValueError("Missing separator")
        allowed = (
            hmac.compare_digest(actual_user, os.environ["NOVA_DEMO_OWNER_USER"])
            and hmac.compare_digest(actual_password, os.environ["NOVA_DEMO_OWNER_PASSWORD"])
        )
    except (ValueError, UnicodeDecodeError, KeyError):
        allowed = False
    if not allowed:
        raise HTTPException(
            status_code=401, detail="Demo owner sign-in required",
            headers={"WWW-Authenticate": 'Basic realm="Nova Synthetic Demo"'},
        )
    return actual_user


def _csv() -> tuple[bytes, str]:
    with tempfile.TemporaryDirectory(prefix="nova-demo-work-") as directory:
        result = offline_demo(Path(directory))
        data = (Path(directory) / "nova_synthetic_cleaned.csv").read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if result.get("review_state") != "approved_by_synthetic_fixture" or digest != result.get("sha256"):
            raise HTTPException(status_code=503, detail="Synthetic output integrity failed")
        return data, digest


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_ledger, timeout=5)
    conn.execute("""CREATE TABLE IF NOT EXISTS review (
        owner TEXT NOT NULL, digest TEXT NOT NULL,
        decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),
        PRIMARY KEY(owner,digest))""")
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


class Review(BaseModel):
    approve: bool


@app.get(BASE + "/ui")
def ui(owner: str = Depends(_owner)) -> HTMLResponse:
    # The standalone demo has no AMICOR session manager and uses Basic login.
    html = _HTML.read_text(encoding="utf-8")
    html = html.replace('<script src="/static/ux/sessionManager.js"></script>', "")
    html = html.replace('method: "POST", body: JSON.stringify({ approve: approve })',
                        'method: "POST", headers: Object.assign(headers(), { "X-Nova-Demo-Action": "review" }), body: JSON.stringify({ approve: approve })')
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.get(BASE + "/preview")
def preview(owner: str = Depends(_owner)) -> dict[str, str]:
    data, digest = _csv()
    with _db() as db:
        row = db.execute("SELECT decision FROM review WHERE owner=? AND digest=?", (owner, digest)).fetchone()
    return {"csv_text": data.decode("utf-8"), "sha256": digest,
            "review_state": row[0] if row else "awaiting_owner_review", "data_class": "synthetic_only"}


@app.post(BASE + "/review")
def review(
    payload: Review, request: Request,
    owner: str = Depends(_owner),
    demo_action: str | None = Header(default=None, alias="X-Nova-Demo-Action"),
) -> dict[str, str]:
    # A custom same-origin header prevents a cross-site form from recording a
    # review using cached browser Basic credentials.
    origin = request.headers.get("origin")
    if (
        demo_action != "review"
        or not request.headers.get("content-type", "").lower().startswith("application/json")
        or (origin is not None and origin.rstrip("/") != str(request.base_url).rstrip("/"))
    ):
        raise HTTPException(status_code=403, detail="Demo review request rejected")
    _, digest = _csv()
    decision = "approved" if payload.approve else "rejected"
    with _db() as db:
        db.execute(
            "INSERT INTO review(owner,digest,decision) VALUES (?,?,?) ON CONFLICT(owner,digest) DO NOTHING",
            (owner, digest, decision),
        )
        recorded = db.execute(
            "SELECT decision FROM review WHERE owner=? AND digest=?", (owner, digest),
        ).fetchone()
        if recorded is None or recorded[0] != decision:
            db.rollback()
            raise HTTPException(status_code=409, detail="Prior demo decision cannot be changed")
        db.commit()
    return {"review_state": decision, "sha256": digest}


@app.get(BASE + "/download")
def download(owner: str = Depends(_owner)) -> Response:
    data, digest = _csv()
    with _db() as db:
        decision = db.execute(
            "SELECT decision FROM review WHERE owner=? AND digest=?", (owner, digest),
        ).fetchone()
    if decision is None or decision[0] != "approved":
        raise HTTPException(status_code=403, detail="Explicit demo owner approval required")
    return Response(
        data, media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="nova-synthetic-cleaned.csv"',
                 "Cache-Control": "no-store", "X-Nova-Data-Class": "synthetic-only"},
    )
