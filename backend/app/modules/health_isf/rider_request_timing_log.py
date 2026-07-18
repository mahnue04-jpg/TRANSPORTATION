"""Structured timing diagnostics for rider customer-request intake."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.logging_utils import get_request_id

_LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
_LOG_PATH = _LOG_DIR / "rider_request_timing.log"
_LOGGER_NAME = "health_isf.rider_request_timing"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 12

_timing_logger: logging.Logger | None = None


def _ensure_logger() -> logging.Logger:
    global _timing_logger
    if _timing_logger is not None:
        return _timing_logger
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
    _timing_logger = logger
    return logger


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in list(value.items())[:30]}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in list(value)[:30]]
    return _json_safe(str(value))


def record_rider_request_timing(
    *,
    stage: str,
    duration_ms: int | None = None,
    idempotency_key: str | None = None,
    ride_id: str | None = None,
    request_id: str | None = None,
    organization_id: str | None = None,
    http_status: int | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "stage": str(stage or "unknown"),
        "request_id": get_request_id(),
        "duration_ms": duration_ms,
        "idempotency_key": (idempotency_key or "")[:128] or None,
        "ride_id": ride_id,
        "customer_request_id": request_id,
        "organization_id": organization_id,
        "http_status": http_status,
        "error": (error or "")[:500] or None,
    }
    if extra:
        payload["extra"] = _json_safe(extra)
    try:
        _ensure_logger().info(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    except Exception:
        logging.getLogger(__name__).exception("rider_request_timing_write_failed")
