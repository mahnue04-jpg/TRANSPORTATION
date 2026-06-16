"""
backend/app/core/error_boundary.py

ErrorBoundaryMiddleware — catch-all unhandled exception handler.

Responsibilities:
- Intercepts exceptions that escape all route handlers and inner middleware.
- Returns a structured JSON fallback with a correlation_id.  Never leaks
  internal details (stack traces, DB errors) in production responses.
- Reads request.state.request_id (set by RequestTracingMiddleware) as
  correlation_id when available; generates a fresh UUID otherwise.
- Tracks active request count via system_metrics counters.
- Fail-safe: the dispatch method itself never raises.

Note: placed in app.core rather than app.middleware to avoid conflicting
with the existing flat app.middleware module (middleware.py).
"""
from __future__ import annotations

import logging
import os
import traceback
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("amicor.error_boundary")

_PRODUCTION_ENVS: frozenset[str] = frozenset({"production", "prod", "staging"})


def _is_production() -> bool:
    return os.environ.get("APP_ENV", "development").strip().lower() in _PRODUCTION_ENVS


class ErrorBoundaryMiddleware(BaseHTTPMiddleware):
    """
    Outermost error boundary middleware.

    Wraps the entire middleware stack so unhandled exceptions from any
    inner middleware or route handler produce a safe, structured JSON
    response rather than an unhandled 500 with no body.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore
        # Import deferred to avoid circular imports at module load time
        try:
            from app.monitoring.system_metrics import (
                decrement_active_requests,
                increment_active_requests,
            )
            _tracking = True
        except Exception:
            _tracking = False

        if _tracking:
            increment_active_requests()  # type: ignore[possibly-undefined]

        try:
            return await call_next(request)  # type: ignore
        except Exception as exc:
            correlation_id: str = (
                getattr(request.state, "request_id", None) or str(uuid.uuid4())
            )

            logger.error(
                "Unhandled exception intercepted by ErrorBoundaryMiddleware | "
                "correlation_id=%s path=%s method=%s exc_type=%s",
                correlation_id,
                request.url.path,
                request.method,
                type(exc).__name__,
            )

            # Include traceback hint in non-production logs only
            if not _is_production():
                logger.debug(
                    "Full traceback [correlation_id=%s]:\n%s",
                    correlation_id,
                    traceback.format_exc(),
                )

            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "message": "Internal server error",
                    "correlation_id": correlation_id,
                },
                headers={"X-Correlation-ID": correlation_id},
            )
        finally:
            if _tracking:
                decrement_active_requests()  # type: ignore[possibly-undefined]
