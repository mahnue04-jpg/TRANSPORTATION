"""Dev-only routes for the mock CIGO validation demo."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from app.core.cigo_validation.service import CigoValidationDemo, demo_enabled

router = APIRouter(prefix="/dev/cigo-validation", tags=["cigo-validation-demo"])
STORE = CigoValidationDemo()
_STATIC = Path(__file__).resolve().parents[3] / "static" / "cigo-validation"
_NOINDEX = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store", "X-Cigo-Outbound-Sends": "0"}


def _json(body: dict, status: int) -> JSONResponse:
    body["outbound_sends"] = STORE.outbound_sends
    return JSONResponse(status_code=status, content=body, headers=_NOINDEX)


@router.get("")
def page() -> FileResponse:
    return FileResponse(_STATIC / "index.html", media_type="text/html", headers=_NOINDEX)


@router.get("/demo.js")
def script() -> FileResponse:
    return FileResponse(_STATIC / "demo.js", media_type="text/javascript", headers=_NOINDEX)


@router.get("/demo.css")
def styles() -> FileResponse:
    return FileResponse(_STATIC / "demo.css", media_type="text/css", headers=_NOINDEX)


@router.post("/submissions")
async def submit(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = None
    result = STORE.submit(payload, force_failure=request.headers.get("x-cigo-force-failure"))
    status = int(result.pop("http_status"))
    return _json(result, status)


@router.get("/records")
def records() -> JSONResponse:
    return _json({"records": STORE.snapshot()["records"]}, 200)


@router.get("/alerts")
def alerts() -> JSONResponse:
    return _json({"alerts": STORE.snapshot()["alerts"]}, 200)


@router.get("/failures")
def failures() -> JSONResponse:
    return _json({"failures": STORE.snapshot()["failures"]}, 200)


@router.get("/export.json")
def export_json() -> JSONResponse:
    return _json(STORE.snapshot(), 200)


@router.get("/export.csv")
def export_csv() -> Response:
    return Response(
        content=STORE.export_csv(),
        media_type="text/csv",
        headers={**_NOINDEX, "Content-Disposition": "attachment; filename=cigo-validation-mock.csv"},
    )


@router.post("/reset")
def reset() -> JSONResponse:
    STORE.reset()
    return _json({"ok": True, "status": "reset"}, 200)


__all__ = ["STORE", "demo_enabled", "router"]
