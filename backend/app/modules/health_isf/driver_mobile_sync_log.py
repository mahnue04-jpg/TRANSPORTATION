"""Permanent rotating diagnostics for Driver Mobile assignment synchronization."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.logging_utils import get_request_id
from app.modules.health_isf import service

_LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
_LOG_PATH = _LOG_DIR / "driver_mobile_assignment_sync.log"
_LOGGER_NAME = "health_isf.driver_mobile_assignment_sync"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 12

_sync_logger: logging.Logger | None = None


def _ensure_logger() -> logging.Logger:
    global _sync_logger
    if _sync_logger is not None:
        return _sync_logger
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            _LOG_PATH,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    _sync_logger = logger
    return logger


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in list(value)[:40]]
    return _json_safe(str(value))


def resolve_driver_session_id(
    db: Session,
    *,
    driver_id: str,
    request: Request | None = None,
    session_token: str | None = None,
) -> str | None:
    token = safe_text(session_token)
    if not token and request is not None:
        token = safe_text(
            request.headers.get("X-Driver-Session-Token")
            or request.headers.get("x-driver-session-token")
        )
    if not token or not driver_id:
        return None
    session = service.validate_driver_session_token(db, driver_id=driver_id, session_token=token)
    return str(session.id) if session else None


def safe_text(value: Any, default: str = "") -> str:
    text = str(value or default).strip()
    return text


def record_driver_mobile_assignment_sync(
    *,
    source: str,
    event: str,
    authenticated_driver_id: str | None = None,
    driver_session_id: str | None = None,
    requested_ride_id: str | None = None,
    assignment_state: str | None = None,
    api_response: Any = None,
    frontend_state_transition: str | None = None,
    http_status: int | None = None,
    route: str | None = None,
    http_method: str | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": safe_text(source, "unknown"),
        "event": safe_text(event, "assignment_sync"),
        "request_id": get_request_id(),
        "authenticated_driver_id": safe_text(authenticated_driver_id) or None,
        "driver_session_id": safe_text(driver_session_id) or None,
        "requested_ride_id": safe_text(requested_ride_id) or None,
        "assignment_state": safe_text(assignment_state) or None,
        "api_response": _json_safe(api_response),
        "frontend_state_transition": safe_text(frontend_state_transition) or None,
        "http_status": http_status,
        "route": safe_text(route) or None,
        "http_method": safe_text(http_method) or None,
        "error": safe_text(error) or None,
    }
    if extra:
        payload["extra"] = _json_safe(extra)
    try:
        _ensure_logger().info(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    except Exception:
        logging.getLogger(__name__).exception("driver_mobile_assignment_sync_write_failed")


def record_backend_assignment_sync(
    db: Session,
    *,
    request: Request,
    event: str,
    driver_id: str,
    ride_id: str | None = None,
    assignment_state: str | None = None,
    api_response: Any = None,
    http_status: int = 200,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    record_driver_mobile_assignment_sync(
        source="backend",
        event=event,
        authenticated_driver_id=driver_id,
        driver_session_id=resolve_driver_session_id(db, driver_id=driver_id, request=request),
        requested_ride_id=ride_id,
        assignment_state=assignment_state,
        api_response=api_response,
        http_status=http_status,
        route=request.url.path,
        http_method=request.method,
        error=error,
        extra=extra,
    )
