"""AMICOR digital marketplace file administration and delivery gates."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, require_any_role

from .manifest import PRODUCT_FILES
from .service import MarketplaceFileError, product_path, store_verified_pdf, verified_file_status

router = APIRouter(prefix="/api/nova/marketplace", tags=["nova-marketplace"])
require_marketplace_admin = require_any_role(ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT)


@router.get("/status")
def marketplace_status():
    rows = []
    for slug in PRODUCT_FILES:
        rows.append(verified_file_status(slug))
    return {
        "products": rows,
        "free_download_ready": any(
            row["slug"] == "ai-side-income-checklist" and row.get("verified")
            for row in rows
        ),
        "paid_checkout_enabled": False,
        "paid_entitlement_enabled": False,
    }


@router.post("/admin/products/{slug}/file")
async def upload_marketplace_file(
    slug: str,
    file: UploadFile = File(...),
    _admin=Depends(require_marketplace_admin),
):
    if slug not in PRODUCT_FILES:
        raise HTTPException(status_code=404, detail="Unknown marketplace product")
    try:
        data = await file.read()
        result = store_verified_pdf(slug, data)
    except MarketplaceFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()
    return {"ok": True, "product": result}


@router.get("/products/{slug}/download")
def download_marketplace_product(slug: str):
    if slug not in PRODUCT_FILES:
        raise HTTPException(status_code=404, detail="Unknown marketplace product")
    spec = PRODUCT_FILES[slug]
    status = verified_file_status(slug)
    if not status.get("verified"):
        raise HTTPException(status_code=503, detail="Product file is not ready")
    if spec["access"] != "free":
        raise HTTPException(
            status_code=403,
            detail="Paid product download requires a verified purchase entitlement.",
        )
    return FileResponse(
        product_path(slug),
        media_type="application/pdf",
        filename=str(spec["filename"]),
    )
