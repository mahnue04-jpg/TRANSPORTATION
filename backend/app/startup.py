"""startup.py — Production startup validation and graceful shutdown for Amicor.

Responsibilities:
  - Validate required environment variables before accepting traffic.
  - Verify database connectivity independently of the ORM layer.
  - Register SIGTERM / SIGINT handlers for graceful shutdown.
  - Expose startup_report() so the /api/health/detail endpoint can surface it.
  - Provide startup_recovery() that retries DB validation on transient failures.
"""

import os
import signal
import sqlite3
import logging
import time
from typing import Optional

logger = logging.getLogger("amicor.startup")

_DEFAULT_DB = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "chat.db")
)

# ── Required / optional env-var declarations ───────────────────────────────────
REQUIRED_VARS: list[str] = [
    "OPENAI_API_KEY",
]

OPTIONAL_VARS: dict[str, str] = {
    "ALLOWED_ORIGINS":  "Defaults to * — unsafe for production, set to your domain.",
    "LOG_LEVEL":        "Defaults to INFO.",
    "DB_FILENAME":      f"Defaults to {_DEFAULT_DB}.",
    "MAX_HISTORY":      "Defaults to 10 messages.",
    "APP_VERSION":      "Defaults to 'dev'.",
}

# ── Runtime state ─────────────────────────────────────────────────────────────
_startup_report: dict = {}
_shutdown_requested: bool = False


def is_shutdown_requested() -> bool:
    """Return True if a SIGTERM/SIGINT has been received."""
    return _shutdown_requested


def _handle_shutdown(signum: int, frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Shutdown signal received (signal %s) — draining requests…", signum)


def register_shutdown_handlers() -> None:
    """Register SIGTERM and SIGINT handlers for graceful shutdown."""
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT,  _handle_shutdown)
    logger.info("Shutdown handlers registered (SIGTERM, SIGINT).")


# ── Environment validation ─────────────────────────────────────────────────────
def validate_environment() -> dict:
    """Check required and optional env vars. Returns a status dict."""
    missing  = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    warnings = []
    for var, note in OPTIONAL_VARS.items():
        if not os.environ.get(var):
            warnings.append(f"{var} not set — {note}")
    return {
        "ok":               len(missing) == 0,
        "missing_required": missing,
        "warnings":         warnings,
    }


# ── Database validation ────────────────────────────────────────────────────────
def validate_database(db_path: Optional[str] = None) -> dict:
    """Check that the SQLite database path is accessible and writable."""
    if db_path is None:
        db_path = os.environ.get("DB_FILENAME", _DEFAULT_DB)

    try:
        # Ensure parent directory exists (mirrors database.py behaviour)
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("SELECT 1")
        conn.execute("PRAGMA integrity_check")
        conn.close()
        return {"ok": True, "db_path": db_path}
    except Exception as exc:
        return {"ok": False, "db_path": db_path, "error": str(exc)}


def startup_recovery(max_retries: int = 3, delay_s: float = 1.0) -> bool:
    """Retry database validation up to max_retries times.

    Returns True on first success, False if all attempts fail.
    """
    for attempt in range(1, max_retries + 1):
        result = validate_database()
        if result["ok"]:
            logger.info("Database ready (attempt %d/%d).", attempt, max_retries)
            return True
        logger.warning(
            "Database not ready (attempt %d/%d): %s",
            attempt, max_retries, result.get("error"),
        )
        if attempt < max_retries:
            time.sleep(delay_s)
    logger.error("Database unavailable after %d attempts.", max_retries)
    return False


# ── Full startup validation ────────────────────────────────────────────────────
def run_startup_validation() -> dict:
    """Run full startup validation and cache the report globally.

    Always returns the report dict — callers decide whether to abort on failure.
    """
    global _startup_report

    env_result = validate_environment()
    db_result  = validate_database()

    report: dict = {
        "timestamp":   time.time(),
        "environment": env_result,
        "database":    db_result,
        "ok":          env_result["ok"] and db_result["ok"],
        "version":     os.environ.get("APP_VERSION", "dev"),
        "log_level":   os.environ.get("LOG_LEVEL", "INFO"),
    }

    # Log issues
    if env_result["missing_required"]:
        logger.error(
            "Startup validation — missing required env vars: %s",
            env_result["missing_required"],
        )
    for warning in env_result.get("warnings", []):
        logger.warning("Startup warning: %s", warning)
    if not db_result["ok"]:
        logger.error("Startup validation — database error: %s", db_result.get("error"))

    if report["ok"]:
        logger.info(
            "Startup validation passed. version=%s log_level=%s",
            report["version"], report["log_level"],
        )

    _startup_report = report
    return report


def startup_report() -> dict:
    """Return the cached startup report (set by run_startup_validation)."""
    return dict(_startup_report)
