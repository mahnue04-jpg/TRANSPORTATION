"""
Security middleware and helpers.

Provides:
  - SecurityHeadersMiddleware : adds OWASP-recommended response headers
  - RequestTracingMiddleware  : injects X-Request-ID, times requests, structured audit log
  - sanitize_user_id()       : strips dangerous characters from user_id strings
  - log_provider_call()      : records provider latency to platform_provider_logs table
"""
import logging
import re
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app import observability
from app import logging_utils

logger = logging.getLogger("amicor.middleware")
audit_logger = logging.getLogger("amicor.audit")

# ── User-ID sanitisation ──────────────────────────────────────────────────────
_SAFE_USER_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")


def sanitize_user_id(user_id: str) -> str:
    """
    Strip whitespace and validate that the user_id contains only safe characters.
    Raises ValueError on invalid input.
    """
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id is empty")
    if not _SAFE_USER_ID_RE.match(uid):
        raise ValueError(f"user_id contains invalid characters: {uid!r}")
    return uid


# ── Security headers ──────────────────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Injects OWASP-recommended HTTP security headers on every response.
    Does not override headers already set by the route handler.
    """
    _HEADERS = {
        "X-Content-Type-Options":    "nosniff",
        "X-Frame-Options":           "DENY",
        "X-XSS-Protection":          "1; mode=block",
        "Referrer-Policy":           "strict-origin-when-cross-origin",
        "Permissions-Policy":        "camera=(), microphone=(), geolocation=()",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        ),
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        for header, value in self._HEADERS.items():
            response.headers.setdefault(header, value)
        return response


# ── Request tracing + audit logging ───────────────────────────────────────────

class RequestTracingMiddleware(BaseHTTPMiddleware):
    """
    - Injects X-Request-ID header (client may pre-supply it).
    - Times every request.
    - Emits structured audit log entry after each response.
    - Optionally writes to platform_audit_logs table if DB is available.
    """
    # Paths that are too noisy to audit at INFO level
    _QUIET_PATHS = frozenset({"/api/health", "/api/health/detail", "/static", "/favicon.ico"})

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = req_id
        request_id_token = logging_utils.set_request_id(req_id)

        t0 = time.monotonic()
        path = request.url.path
        method = request.method

        try:
            response = await call_next(request)
            latency_ms = int((time.monotonic() - t0) * 1000)

            response.headers["X-Request-ID"] = req_id
            response.headers["X-Response-Time"] = f"{latency_ms}ms"

            is_quiet = any(path.startswith(p) for p in self._QUIET_PATHS)

            observability.increment("http.requests.total")
            observability.increment(f"http.requests.method.{method}")
            observability.increment(f"http.responses.status.{response.status_code}")
            observability.record_latency("http.requests.latency_ms", float(latency_ms))

            log_level = logging.DEBUG if is_quiet else logging.INFO
            logging_utils.log_event(
                audit_logger,
                log_level,
                event="http.request.complete",
                message="HTTP request completed",
                method=method,
                path=path,
                status_code=response.status_code,
                latency_ms=latency_ms,
            )

            # Best-effort write to audit table
            if not is_quiet and response.status_code >= 400:
                observability.increment("http.requests.errors")
                observability.record_error(path, response.status_code, "request failed")
                _write_audit_log(req_id, request, response.status_code, latency_ms)

            return response
        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            observability.increment("http.requests.total")
            observability.increment(f"http.requests.method.{method}")
            observability.increment("http.requests.errors")
            observability.record_latency("http.requests.latency_ms", float(latency_ms))
            observability.record_error(path, 500, logging_utils.safe_exception_message(exc))
            logging_utils.log_event(
                logger,
                logging.ERROR,
                event="http.request.exception",
                message="Unhandled request exception",
                method=method,
                path=path,
                latency_ms=latency_ms,
                error=logging_utils.safe_exception_message(exc),
            )
            raise
        finally:
            logging_utils.reset_request_id(request_id_token)


def _write_audit_log(
    req_id: str,
    request: Request,
    status_code: int,
    latency_ms: int,
) -> None:
    """Write an audit entry. Silently ignores DB errors."""
    try:
        from app.db.session import SessionLocal
        from app.db.models import AuditLog

        ip = (
            request.headers.get("X-Forwarded-For", "")
            or (request.client.host if request.client else "unknown")
        ).split(",")[0].strip()

        entry = AuditLog(
            request_id=req_id,
            action="http_request",
            path=str(request.url.path)[:512],
            method=request.method,
            status_code=status_code,
            ip_address=ip[:45],
            latency_ms=latency_ms,
        )
        db = SessionLocal()
        try:
            db.add(entry)
            db.commit()
        finally:
            db.close()
    except Exception:
        pass  # Never let audit logging crash the app


# ── Provider call logging ──────────────────────────────────────────────────────

def log_provider_call(
    provider_name: str,
    success: bool,
    latency_ms: int | None = None,
    error_msg: str | None = None,
    endpoint: str | None = None,
) -> None:
    """
    Record a provider invocation to platform_provider_logs.
    Call this from weather.py, web_search.py, etc. after each provider attempt.
    Silently ignores errors so it never disrupts the caller.
    """
    try:
        from app.db.session import SessionLocal
        from app.db.models import ProviderLog

        entry = ProviderLog(
            provider_name=provider_name[:64],
            success=success,
            latency_ms=latency_ms,
            error_msg=(error_msg or "")[:512] if error_msg else None,
            endpoint=(endpoint or "")[:256] if endpoint else None,
        )
        db = SessionLocal()
        try:
            db.add(entry)
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def log_upload(
    filename: str | None,
    content_type: str,
    size_bytes: int,
    ocr_method: str | None = None,
    ocr_confidence: float | None = None,
    ocr_word_count: int | None = None,
    user_id: str | None = None,
) -> None:
    """Persist an upload record to platform_uploads."""
    try:
        from app.db.session import SessionLocal
        from app.db.models import Upload

        entry = Upload(
            user_id=user_id,
            filename=(filename or "")[:512] if filename else None,
            content_type=content_type[:128],
            size_bytes=size_bytes,
            ocr_method=ocr_method,
            ocr_confidence=ocr_confidence,
            ocr_word_count=ocr_word_count,
        )
        db = SessionLocal()
        try:
            db.add(entry)
            db.commit()
        finally:
            db.close()
    except Exception:
        pass
