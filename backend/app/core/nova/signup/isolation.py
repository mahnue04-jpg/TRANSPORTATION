"""Nova SaaS customer product-scope guard. Does not modify Health/Freight routers."""
from __future__ import annotations

from typing import Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.auth import decode_access_token
from app.db.session import SessionLocal

BLOCKED_PREFIXES = (
    "/api/admin",
    "/api/health-isf",
    "/api/payments",
    "/api/platform-ops",
    "/api/nova/freight",
    "/api/approval-engine",
    "/app",
    "/workspace",
    "/platform-ops",
    "/nova/freight",
    "/admin",
)
ALLOWED_OVERRIDES = ("/nova/workspace",)


def is_nova_saas_customer_org(db, organization_id: str | None) -> bool:
    org_id = str(organization_id or "").strip()
    if not org_id:
        return False
    from app.core.nova.signup.models import NovaCustomerTenant
    from app.core.nova.signup.schema_ensure import ensure_nova_signup_schema

    ensure_nova_signup_schema()
    row = (
        db.query(NovaCustomerTenant)
        .filter(NovaCustomerTenant.organization_id == org_id)
        .first()
    )
    return row is not None and str(row.product_scope or "nova") == "nova"


def path_blocked_for_nova_customer(path: str) -> bool:
    normalized = str(path or "")
    if any(normalized == override or normalized.startswith(override + "/") for override in ALLOWED_OVERRIDES):
        return False
    return any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in BLOCKED_PREFIXES)


class NovaCustomerProductGuardMiddleware(BaseHTTPMiddleware):
    """Block frozen-product APIs/pages for Nova founding/SaaS customers only."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[override]
        path = request.url.path
        if not path_blocked_for_nova_customer(path):
            return await call_next(request)  # type: ignore[misc]

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return await call_next(request)  # type: ignore[misc]
        token = auth_header[7:].strip()
        if not token:
            return await call_next(request)  # type: ignore[misc]
        try:
            payload = decode_access_token(token)
        except Exception:
            return await call_next(request)  # type: ignore[misc]
        org_id = str(payload.get("organization_id") or "").strip()
        if not org_id:
            return await call_next(request)  # type: ignore[misc]
        try:
            with SessionLocal() as db:
                blocked = is_nova_saas_customer_org(db, org_id)
        except Exception:
            return await call_next(request)  # type: ignore[misc]
        if not blocked:
            return await call_next(request)  # type: ignore[misc]
        return JSONResponse(
            status_code=403,
            content={"detail": "Nova customer access is limited to AMICOR Nova."},
        )
