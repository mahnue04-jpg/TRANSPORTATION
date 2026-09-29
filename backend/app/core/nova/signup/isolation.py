"""Nova SaaS customer product-scope guard. Does not modify Health/Freight routers."""
from __future__ import annotations

from datetime import timedelta
from typing import Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.auth import decode_access_token
from app.db.session import SessionLocal
from app.helpers import now

BLOCKED_PREFIXES = (
    "/api/admin",
    "/api/marketing/admin",
    "/api/health-isf",
    "/api/ops",
    "/api/payments",
    "/api/platform-ops",
    "/api/nova/freight",
    "/api/nova/work",
    "/api/nova/payments",
    "/api/nova/autonomy",
    "/api/nova/v3",
    "/api/approval-engine",
    "/app",
    "/workspace",
    "/platform-ops",
    "/nova/freight",
    "/nova/work",
    "/nova/payments",
    "/admin",
)
ALLOWED_OVERRIDES = ("/nova/workspace",)

FREE_BLOCKED_PREFIXES = (
    "/api/nova/communications",
    "/api/nova/government",
    "/api/nova/business",
    "/api/nova/accounting",
    "/nova/communications",
    "/nova/government",
    "/nova/business",
    "/nova/accounting",
)


def nova_customer_tenant(db, organization_id: str | None):
    org_id = str(organization_id or "").strip()
    if not org_id:
        return None
    from app.core.nova.signup.models import NovaCustomerTenant
    from app.core.nova.signup.schema_ensure import ensure_nova_signup_schema

    ensure_nova_signup_schema()
    row = (
        db.query(NovaCustomerTenant)
        .filter(NovaCustomerTenant.organization_id == org_id)
        .first()
    )
    if row is None or str(row.product_scope or "nova") != "nova":
        return None
    return row


def is_nova_saas_customer_org(db, organization_id: str | None) -> bool:
    return nova_customer_tenant(db, organization_id) is not None


def migrate_legacy_free_tenant(db, tenant) -> bool:
    """Move pre-launch permanent-free Nova accounts onto the unified 7-day no-card trial."""
    if tenant is None or str(tenant.subscription_status or "").lower() != "free":
        return False
    from app.core.nova.signup.models import NovaSignupAccount
    signup = db.get(NovaSignupAccount, tenant.signup_id)
    if signup is None or signup.stripe_subscription_id:
        return False
    stamp = now()
    tenant.subscription_status = "trialing"
    tenant.updated_at = stamp
    signup.status = "trialing"
    signup.intro_started_at = stamp
    signup.intro_ends_at = stamp + timedelta(days=7)
    signup.updated_at = stamp
    db.commit()
    return True


def path_blocked_for_nova_customer(path: str) -> bool:
    normalized = str(path or "")
    if any(normalized == override or normalized.startswith(override + "/") for override in ALLOWED_OVERRIDES):
        return False
    return any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in BLOCKED_PREFIXES)


class NovaCustomerProductGuardMiddleware(BaseHTTPMiddleware):
    """Block frozen-product APIs/pages for Nova founding/SaaS customers only."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[override]
        path = request.url.path
        global_block = path_blocked_for_nova_customer(path)
        free_candidate = any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in FREE_BLOCKED_PREFIXES
        )
        trial_candidate = (
            path.startswith("/api/nova/")
            or path == "/api/search"
            or path.startswith("/api/search/")
        )
        if not global_block and not free_candidate and not trial_candidate:
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
                tenant = nova_customer_tenant(db, org_id)
                migrate_legacy_free_tenant(db, tenant)
                trial_expired = False
                if tenant is not None and str(tenant.subscription_status or "").lower() == "trialing":
                    from app.core.nova.signup.models import NovaSignupAccount
                    signup = db.get(NovaSignupAccount, tenant.signup_id)
                    trial_expired = bool(
                        signup is not None
                        and signup.intro_ends_at is not None
                        and now() >= signup.intro_ends_at
                    )
        except Exception:
            return await call_next(request)  # type: ignore[misc]
        if tenant is None:
            return await call_next(request)  # type: ignore[misc]
        if trial_expired and trial_candidate:
            write_like = request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
            live_search = path == "/api/search" or path.startswith("/api/search/")
            if write_like or live_search:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            "Your 7-day AMICOR Nova trial has ended. "
                            "Your account and prior work remain available to review; upgrade to continue new Nova work."
                        )
                    },
                )
        if global_block:
            return JSONResponse(
                status_code=403,
                content={"detail": "Nova customer access is limited to AMICOR Nova."},
            )
        if free_candidate and str(tenant.subscription_status or "").lower() == "free":
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "This module is available on paid AMICOR Nova plans. "
                        "Free accounts include Ask Nova, Today, Workspace, and live search."
                    )
                },
            )
        return await call_next(request)  # type: ignore[misc]
