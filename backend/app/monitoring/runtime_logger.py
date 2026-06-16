from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger("amicor.monitoring.runtime_logger")

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs" / "supervision"
_LOG_PREFIX = "supervision-"
_LOG_RETENTION_FILES = 5
_RECENT_FALLBACK_MAX = 100

_log_lock = Lock()
_recent_fallback: deque[dict[str, Any]] = deque(maxlen=_RECENT_FALLBACK_MAX)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_log_file() -> Path:
    day_key = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _LOG_DIR / f"{_LOG_PREFIX}{day_key}.log"


def _cleanup_old_logs() -> None:
    try:
        if not _LOG_DIR.exists():
            return
        files = sorted(_LOG_DIR.glob(f"{_LOG_PREFIX}*.log"), key=lambda p: p.name)
        if len(files) <= _LOG_RETENTION_FILES:
            return
        for old_file in files[: len(files) - _LOG_RETENTION_FILES]:
            try:
                old_file.unlink(missing_ok=True)
            except Exception:
                # Safe cleanup only; retention failure must not affect runtime behavior.
                continue
    except Exception:
        # Defensive boundary for all retention logic.
        return


def _build_entry(level: str, subsystem: str, event: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "timestamp": _utc_now_iso(),
        "level": str(level or "INFO").upper(),
        "subsystem": str(subsystem or "unknown"),
        "event": str(event or "unspecified"),
        "details": details or {},
    }


def record_supervision_event(
    *,
    level: str = "INFO",
    subsystem: str,
    event: str,
    details: dict[str, Any] | None = None,
) -> bool:
    """Append-only supervision event logger.

    This helper is intentionally non-invasive: failures are swallowed and reported via fallback memory.
    """
    entry = _build_entry(level=level, subsystem=subsystem, event=event, details=details)
    with _log_lock:
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            target = _current_log_file()
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str, ensure_ascii=True) + "\n")
            _cleanup_old_logs()
            _recent_fallback.append(entry)
            return True
        except Exception as exc:
            _recent_fallback.append(
                {
                    **entry,
                    "event": "supervision_log_write_failed",
                    "details": {
                        **entry.get("details", {}),
                        "error": type(exc).__name__,
                    },
                }
            )
            logger.debug("supervision event logging failed: %s", exc)
            return False


def get_recent_supervision_events(limit: int = 20) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(int(limit), 100))
    with _log_lock:
        try:
            target = _current_log_file()
            if not target.exists():
                return list(_recent_fallback)[-bounded_limit:]

            events: list[dict[str, Any]] = []
            with target.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                        if isinstance(payload, dict):
                            events.append(payload)
                    except json.JSONDecodeError:
                        continue
            if not events:
                return list(_recent_fallback)[-bounded_limit:]
            return events[-bounded_limit:]
        except Exception:
            return list(_recent_fallback)[-bounded_limit:]


def get_supervision_log_status() -> dict[str, Any]:
    with _log_lock:
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            files = sorted(_LOG_DIR.glob(f"{_LOG_PREFIX}*.log"), key=lambda p: p.name)
            current = _current_log_file()
            writable = False
            try:
                with current.open("a", encoding="utf-8"):
                    writable = True
            except Exception:
                writable = False
            return {
                "status": "healthy" if writable else "degraded",
                "directory": str(_LOG_DIR),
                "current_file": str(current),
                "retained_files": len(files),
                "retention_limit": _LOG_RETENTION_FILES,
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "detail": f"supervision_log_status_failed:{type(exc).__name__}",
            }
