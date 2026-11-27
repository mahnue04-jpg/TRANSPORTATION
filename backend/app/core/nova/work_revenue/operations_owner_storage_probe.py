"""Owner-only synthetic round trip for the dedicated Operations private bucket."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from app.auth import UserContext
from app.core.nova.work_revenue.operations_private_storage import run_synthetic_storage_probe
from app.core.nova.work_revenue.owner_auth import require_work_revenue_owner
from app.modules.platform_ops.secure_storage import SecureStorageNotConfigured

router = APIRouter(
    prefix="/api/nova/work/operations/owner",
    tags=["nova-operations-owner-storage"],
)

_OWNER_ACTION = "run-synthetic-storage-probe"


@router.post("/storage-probe")
def owner_synthetic_storage_probe(
    owner_action: str | None = Header(default=None, alias="X-Nova-Owner-Action"),
    owner: UserContext = Depends(require_work_revenue_owner),
) -> dict:
    """Upload, verify, and delete one synthetic object. Customers are rejected."""
    del owner
    if owner_action != _OWNER_ACTION:
        raise HTTPException(status_code=403, detail="Explicit owner storage probe required")
    try:
        report = run_synthetic_storage_probe()
    except SecureStorageNotConfigured:
        raise HTTPException(status_code=503, detail="Operations storage probe is unavailable")
    except Exception:
        raise HTTPException(status_code=503, detail="Operations storage probe failed")
    return report
