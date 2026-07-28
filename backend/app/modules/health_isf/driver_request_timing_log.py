"""Structured timing diagnostics for Driver Mobile read endpoints."""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterator

from app.logging_utils import get_request_id

_LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
_LOG_PATH = _LOG_DIR / "driver_mobile_read_timing.log"
_LOGGER_NAME = "health_isf.driver_mobile_read_timing"
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
        return {str(k): _json_safe(v) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in list(value)[:40]]
    return _json_safe(str(value))


class DriverReadStageTimer:
    """Collect per-stage millisecond timings for a single driver read request."""

    def __init__(self) -> None:
        self.stages: dict[str, int] = {}
        self._started = time.perf_counter()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.stages[str(name)] = int((time.perf_counter() - started) * 1000)

    def total_ms(self) -> int:
        return int((time.perf_counter() - self._started) * 1000)


def record_driver_read_timing(
    *,
    endpoint: str,
    driver_id: str,
    organization_id: str,
    stages: dict[str, int],
    total_ms: int,
    http_status: int = 200,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "endpoint": str(endpoint or "unknown"),
        "request_id": get_request_id(),
        "driver_id": driver_id,
        "organization_id": organization_id,
        "total_ms": total_ms,
        "stages_ms": stages,
        "http_status": http_status,
    }
    if extra:
        payload["extra"] = _json_safe(extra)
    try:
        _ensure_logger().info(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    except Exception:
        logging.getLogger(__name__).exception("driver_read_timing_write_failed")
