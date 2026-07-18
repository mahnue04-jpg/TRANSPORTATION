"""Permanent rotating diagnostics for ops-shell hydration."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
_LOG_PATH = _LOG_DIR / "ops_shell_hydration.log"
_LOGGER_NAME = "health_isf.ops_shell_hydration"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 12

_hydration_logger: logging.Logger | None = None


def _ensure_logger() -> logging.Logger:
    global _hydration_logger
    if _hydration_logger is not None:
        return _hydration_logger
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
    _hydration_logger = logger
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


def record_ops_shell_hydration(payload: dict[str, Any]) -> None:
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **{k: _json_safe(v) for k, v in payload.items()},
    }
    try:
        _ensure_logger().info(json.dumps(row, ensure_ascii=True, separators=(",", ":")))
    except Exception:
        logging.getLogger(__name__).exception("ops_shell_hydration_write_failed")
