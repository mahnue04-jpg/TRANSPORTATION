"""Tenant-aware token validation middleware for Health ISF endpoints."""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app import observability
from app.auth import decode_access_token
from app import logging_utils

logger = logging.getLogger("amicor.tenant_auth")


class TenantAuthValidationMiddleware(BaseHTTPMiddleware):
    """Validate bearer tokens early for tenant-sensitive API paths.

    This middleware is additive and keeps existing dependency auth checks intact.
    It improves invalid-token monitoring and request-level auth trace context.
    """

    def __init__(self, app, protected_prefixes: tuple[str, ...] = ("/api/health-isf",)): # type: ignore
        super().__init__(app) # type: ignore
        self.protected_prefixes = protected_prefixes

    async def dispatch(self, request: Request, call_next: Callable) -> Response: # type: ignore
        path = request.url.path
        if not any(path.startswith(prefix) for prefix in self.protected_prefixes):
            return await call_next(request) # type: ignore

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            observability.increment("security.invalid_token.missing")
            return JSONResponse(status_code=401, content={"detail": "Missing Bearer token"})

        token = auth_header[7:].strip()
        if not token:
            observability.increment("security.invalid_token.empty")
            return JSONResponse(status_code=401, content={"detail": "Empty Bearer token"})

        try:
            payload = decode_access_token(token)
            request.state.auth_context = {
                "user_id": payload.get("sub"),
                "role": payload.get("role"),
                "organization_id": payload.get("organization_id"),
            }
            logging_utils.log_event(
                logger,
                logging.INFO,
                event="auth.token.validated",
                message="Token validated for tenant path",
                path=path,
                user_id=payload.get("sub"),
                role=payload.get("role"),
                organization_id=payload.get("organization_id"),
            )
            return await call_next(request) # type: ignore
        except HTTPException as exc:
            detail_text = str(exc.detail or "invalid token")
            observability.increment("security.invalid_token")
            if "expired" in detail_text.lower():
                observability.increment("security.token_expired")
                return JSONResponse(
                    status_code=401,
                    headers={"X-Auth-Refresh-Hint": "/api/auth/refresh"},
                    content={"detail": "Token expired", "refresh_hint": "/api/auth/refresh"},
                )

            logging_utils.log_event(
                logger,
                logging.WARNING,
                event="auth.token.rejected",
                message="Token validation failed for tenant path",
                path=path,
                error=detail_text,
            )
            return JSONResponse(status_code=401, content={"detail": "Invalid token"})
