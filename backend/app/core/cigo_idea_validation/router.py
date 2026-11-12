"""Dev-only routes for the fictional consumer idea-validation worksheet."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from app.core.cigo_idea_validation.service import IdeaValidationDemo, demo_enabled

router = APIRouter(prefix="/dev/cigo-idea-validation", tags=["cigo-idea-validation"])
STORE = IdeaValidationDemo()
_STATIC = Path(__file__).resolve().parents[3] / "static" / "cigo-idea-validation"
_NOINDEX = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store", "X-Cigo-Outbound-Sends": "0"}


def _json(body: dict, status: int) -> JSONResponse:
    body["outbound_sends"] = STORE.outbound_sends
    return JSONResponse(status_code=status, content=body, headers=_NOINDEX)


@router.get("")
def page() -> FileResponse:
    return FileResponse(_STATIC / "index.html", media_type="text/html", headers=_NOINDEX)


@router.get("/demo.js")
def script_file() -> FileResponse:
    return FileResponse(_STATIC / "demo.js", media_type="text/javascript", headers=_NOINDEX)


@router.get("/demo.css")
def styles() -> FileResponse:
    return FileResponse(_STATIC / "demo.css", media_type="text/css", headers=_NOINDEX)


@router.get("/evidence")
def evidence() -> JSONResponse:
    return _json(STORE.evidence(), 200)


@router.post("/worksheets")
async def submit(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = None
    result = STORE.submit(payload, force_failure=request.headers.get("x-cigo-force-failure"))
    status = int(result.pop("http_status"))
    return _json(result, status)


@router.get("/worksheets")
def worksheets() -> JSONResponse:
    return _json({"records": STORE.snapshot()["records"]}, 200)


@router.get("/export.json")
def export_json() -> JSONResponse:
    body = STORE.snapshot()
    body["assessment_ready"] = False
    return _json(body, 200)


@router.get("/export.csv")
def export_csv() -> Response:
    return Response(
        content=STORE.export_csv(),
        media_type="text/csv",
        headers={**_NOINDEX, "Content-Disposition": "attachment; filename=cigo-idea-validation-fictional.csv"},
    )


@router.post("/reset")
def reset() -> JSONResponse:
    STORE.reset()
    return _json({"ok": True, "status": "reset", "assessment_ready": False}, 200)


__all__ = ["STORE", "demo_enabled", "router"]
